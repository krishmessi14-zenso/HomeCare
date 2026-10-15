"""Booking workflow: creation, assignment, provider actions, cancellation.

Status machine (validated on the server only):

    Pending -> Assigned -> Accepted -> In Progress -> Completed
    Assigned -> Rejected -> (admin reassigns) Assigned
    Pending/Assigned/Accepted/Rejected -> Cancelled

Double-booking prevention
-------------------------
Each time an admin assigns a provider, we "claim" one document per 30-minute block
in `provider_slots`. A UNIQUE index on (provider_id, block) makes the database itself
reject any overlapping claim, even for simultaneous requests. The booking document is
then changed with find_one_and_update() whose filter includes the status we expect
(compare-and-set). If either step loses a race, claims are rolled back and the caller
gets HTTP 409. Limitation: without multi-document transactions (needs a replica set)
the claim + status update are two writes; a crash between them could leave orphaned
claims. See docs/ARCHITECTURE.md.
"""
import math
import re
from datetime import datetime, timedelta

from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from models import user as user_model
from models import notification as notification_model
from models.db import get_db, utcnow
from utils.validators import clean_text

TIME_SLOTS = [f"{h:02d}:00" for h in range(8, 18)]  # 08:00 .. 17:00 start times
BLOCK_MINUTES = 30
MAX_DAYS_AHEAD = 90
MIN_LEAD_HOURS = 1
CUSTOMER_CANCEL_CUTOFF_HOURS = 2
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

ASSIGNABLE_FROM = ("Pending", "Assigned", "Rejected")
CANCELLABLE_FROM = ("Pending", "Assigned", "Accepted", "Rejected")
PROVIDER_ACTIONS = {  # action -> (required current status, new status)
    "accept": ("Assigned", "Accepted"),
    "reject": ("Assigned", "Rejected"),
    "start": ("Accepted", "In Progress"),
    "complete": ("In Progress", "Completed"),
}


class BookingError(Exception):
    def __init__(self, message, status_code=400):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


# ---------------------------------------------------------------- helpers
def blocks_for(start, duration_minutes):
    n = max(1, math.ceil(duration_minutes / BLOCK_MINUTES))
    return [start + timedelta(minutes=BLOCK_MINUTES * i) for i in range(n)]


def parse_start(date_str, time_str):
    date_str, time_str = (date_str or "").strip(), (time_str or "").strip()
    if not DATE_RE.match(date_str):
        raise BookingError("Please choose a valid date.")
    try:
        day = datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        raise BookingError("Please choose a valid date.")
    if time_str not in TIME_SLOTS:
        raise BookingError("Please choose one of the available time slots.")
    start = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
    now = datetime.now()
    if start < now + timedelta(hours=MIN_LEAD_HOURS):
        raise BookingError(f"Bookings must be made at least {MIN_LEAD_HOURS} hour(s) in advance.")
    if day.date() > (now + timedelta(days=MAX_DAYS_AHEAD)).date():
        raise BookingError(f"Bookings can be made at most {MAX_DAYS_AHEAD} days ahead.")
    return start


def claim_slots(provider_id, booking_id, start, duration_minutes):
    """Atomically claim every block; roll back own claims on conflict. Returns True/False."""
    col = get_db().provider_slots
    inserted = []
    try:
        for block in blocks_for(start, duration_minutes):
            res = col.insert_one({"provider_id": provider_id, "block": block, "booking_id": booking_id})
            inserted.append(res.inserted_id)
        return True
    except DuplicateKeyError:
        if inserted:
            col.delete_many({"_id": {"$in": inserted}})
        return False


def release_slots(booking_id, except_provider_id=None):
    flt = {"booking_id": booking_id}
    if except_provider_id is not None:
        flt["provider_id"] = {"$ne": except_provider_id}
    get_db().provider_slots.delete_many(flt)


def available_providers_for(booking):
    """Approved+active providers with no claimed block overlapping this booking."""
    blocks = blocks_for(booking["start_dt"], booking["duration_minutes"])
    busy = set(get_db().provider_slots.distinct("provider_id", {"block": {"$in": blocks}}))
    return [p for p in user_model.assignable_providers()
            if p["_id"] not in busy and user_model.provider_available_for(p, booking)]


def _transition(flt, new_status, extra=None):
    update = {"status": new_status, "updated_at": utcnow(), **(extra or {})}
    return get_db().bookings.find_one_and_update(flt, {"$set": update}, return_document=ReturnDocument.AFTER)


# ---------------------------------------------------------------- customer
def create_booking(customer_id, service, date_str, time_str, address, notes):
    if not service or not service.get("is_active"):
        raise BookingError("This service is not available.", 400)
    start = parse_start(date_str, time_str)
    address, notes = clean_text(address, multiline=True), clean_text(notes, multiline=True)
    if not 10 <= len(address) <= 300:
        raise BookingError("Address must be 10-300 characters.")
    if not 5 <= len(notes) <= 1000:
        raise BookingError("Problem description must be 5-1000 characters.")
    db = get_db()
    if db.bookings.find_one({"customer_id": customer_id, "service_id": service["_id"], "start_dt": start,
                             "status": {"$nin": ["Cancelled", "Rejected", "Completed"]}}):
        raise BookingError("You already have this service booked for that time slot.", 409)
    now = utcnow()
    doc = {"customer_id": customer_id, "service_id": service["_id"], "service_name": service["name"],
           "price": service["price"], "duration_minutes": int(service["duration_minutes"]), "provider_id": None,
           "booking_date": start.strftime("%Y-%m-%d"), "booking_time": start.strftime("%H:%M"), "start_dt": start,
           "address": address, "notes": notes, "status": "Pending", "payment_status": "Unpaid",
           "created_at": now, "updated_at": now}
    doc["_id"] = db.bookings.insert_one(doc).inserted_id
    notification_model.create_for_role("admin", f"New booking request: {service['name']}.", "/admin/bookings", doc["_id"])
    return doc


def can_customer_cancel(booking):
    if booking["status"] not in CANCELLABLE_FROM:
        return False
    if booking["status"] == "Accepted":
        return booking["start_dt"] - datetime.now() >= timedelta(hours=CUSTOMER_CANCEL_CUTOFF_HOURS)
    return True


def cancel_booking(booking_id, actor_role, customer_id=None):
    flt = {"_id": booking_id}
    if actor_role == "customer":
        flt["customer_id"] = customer_id  # ownership enforced in the query itself
    booking = get_db().bookings.find_one(flt)
    if booking is None:
        raise BookingError("Booking not found.", 404)
    if booking["status"] not in CANCELLABLE_FROM:
        raise BookingError(f"A booking that is {booking['status']} cannot be cancelled.", 409)
    if actor_role == "customer" and not can_customer_cancel(booking):
        raise BookingError(f"Accepted bookings can only be cancelled at least "
                           f"{CUSTOMER_CANCEL_CUTOFF_HOURS} hours before the start time.", 409)
    updated = _transition({**flt, "status": booking["status"]}, "Cancelled", {"cancelled_by": actor_role})
    if updated is None:
        raise BookingError("The booking was changed by someone else. Please refresh.", 409)
    release_slots(booking_id)
    if actor_role == "customer":
        notification_model.create_for_role("admin", f"A customer cancelled {booking['service_name']}.", "/admin/bookings", booking_id)
        notification_model.create_for_user(booking.get("provider_id"), "A customer cancelled your assigned booking.",
                                           "/provider/dashboard", booking_id)
    else:
        notification_model.create_for_user(booking["customer_id"], "Your booking was cancelled by an administrator.",
                                           "/customer/dashboard", booking_id)
        notification_model.create_for_user(booking.get("provider_id"), "An assigned booking was cancelled.",
                                           "/provider/dashboard", booking_id)
    return updated


# ---------------------------------------------------------------- admin
def assign_provider(booking_id, provider_id):
    db = get_db()
    booking = db.bookings.find_one({"_id": booking_id})
    if booking is None:
        raise BookingError("Booking not found.", 404)
    if booking["status"] not in ASSIGNABLE_FROM:
        raise BookingError(f"A booking that is {booking['status']} cannot be (re)assigned.", 409)
    provider = user_model.get_assignable_provider(provider_id)
    if provider is None:
        raise BookingError("Selected provider does not exist, is inactive, or is not approved.", 400)
    if not user_model.provider_available_for(provider, booking):
        raise BookingError("The provider is not available for this booking time.", 409)
    if booking.get("provider_id") == provider_id:
        raise BookingError("This provider is already assigned to the booking.", 409)
    if not claim_slots(provider_id, booking_id, booking["start_dt"], booking["duration_minutes"]):
        raise BookingError("That provider already has a job overlapping this time slot.", 409)
    updated = db.bookings.find_one_and_update(
        {"_id": booking_id, "status": booking["status"], "provider_id": booking.get("provider_id")},
        {"$set": {"provider_id": provider_id, "status": "Assigned", "updated_at": utcnow()}},
        return_document=ReturnDocument.AFTER)
    if updated is None:  # lost a race: undo our claims only
        db.provider_slots.delete_many({"booking_id": booking_id, "provider_id": provider_id})
        raise BookingError("The booking was changed by someone else. Please refresh.", 409)
    release_slots(booking_id, except_provider_id=provider_id)  # free previous provider
    notification_model.create_for_user(updated["customer_id"], "A provider was assigned to your booking.",
                                       "/customer/dashboard", booking_id)
    notification_model.create_for_user(provider_id, f"New job assigned: {updated['service_name']}.",
                                       "/provider/dashboard", booking_id)
    return updated


# ---------------------------------------------------------------- provider
def provider_action(booking_id, provider_user, action):
    if action not in PROVIDER_ACTIONS:
        raise BookingError("Unknown action.", 400)
    if not provider_user.is_approved_provider:
        raise BookingError("Your provider account is not approved.", 403)
    pid = provider_user.doc["_id"]
    required, new_status = PROVIDER_ACTIONS[action]
    updated = _transition({"_id": booking_id, "provider_id": pid, "status": required}, new_status)
    if updated is None:
        existing = get_db().bookings.find_one({"_id": booking_id, "provider_id": pid})
        if existing is None:  # not theirs / not found: same answer, no information leak
            raise BookingError("Booking not found.", 404)
        raise BookingError(f"Cannot {action} a booking that is {existing['status']}.", 409)
    if new_status in ("Rejected", "Completed"):
        release_slots(booking_id)
    notification_model.create_for_user(updated["customer_id"],
                                       f"Your provider updated the booking to {new_status.lower()}.",
                                       "/customer/dashboard", booking_id)
    if new_status == "Rejected":
        notification_model.create_for_role("admin", f"A provider rejected {updated['service_name']}.",
                                            "/admin/bookings", booking_id)
    return updated
