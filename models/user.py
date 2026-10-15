from datetime import datetime, timedelta

from flask_login import UserMixin
from pymongo.errors import DuplicateKeyError
from werkzeug.security import check_password_hash, generate_password_hash

from utils.validators import normalize_email

from .db import get_db, utcnow

ROLES = ("customer", "provider", "admin")
DEFAULT_PROVIDER_AVAILABILITY = {"days": list(range(7)), "start": "08:00", "end": "18:00"}


class DuplicateEmailError(Exception):
    pass


class User(UserMixin):
    """Thin Flask-Login wrapper around a users document."""

    def __init__(self, doc):
        self.doc = doc
        self.id = str(doc["_id"])

    name = property(lambda self: self.doc["name"])
    email = property(lambda self: self.doc["email"])
    role = property(lambda self: self.doc["role"])
    is_active = property(lambda self: bool(self.doc.get("active", False)))

    @property
    def is_approved_provider(self):
        return self.role == "provider" and bool(self.doc.get("provider", {}).get("approved"))


def create_user(name, email, phone, password, role="customer", active=True, approved=False, approved_by=None):
    if role not in ROLES:
        raise ValueError("invalid role")
    now = utcnow()
    doc = {"name": name, "email": normalize_email(email), "password_hash": generate_password_hash(password),
           "phone": phone, "role": role, "active": bool(active), "created_at": now}
    if role == "provider":
        doc["provider"] = {"approved": bool(approved),
                           "approved_by": approved_by if approved else None,
                           "approved_at": now if approved else None}
    try:
        doc["_id"] = get_db().users.insert_one(doc).inserted_id
    except DuplicateKeyError:
        raise DuplicateEmailError(email)
    return doc


def find_by_email(email):
    return get_db().users.find_one({"email": normalize_email(email)})


def find_by_id(oid, role=None):
    flt = {"_id": oid}
    if role:
        flt["role"] = role
    return get_db().users.find_one(flt)


def list_by_role(role, limit=500):
    return list(get_db().users.find({"role": role}).sort("created_at", -1).limit(limit))


def names_by_ids(ids):
    ids = list({i for i in ids if i})
    return {u["_id"]: u for u in get_db().users.find({"_id": {"$in": ids}})} if ids else {}


def update_user(oid, role, fields):
    try:
        return get_db().users.update_one({"_id": oid, "role": role}, {"$set": fields}).matched_count == 1
    except DuplicateKeyError:
        raise DuplicateEmailError(fields.get("email"))


def set_active(oid, role, active):
    return update_user(oid, role, {"active": bool(active)})


def approve_provider(oid, admin_oid):
    res = get_db().users.update_one(
        {"_id": oid, "role": "provider"},
        {"$set": {"provider.approved": True, "provider.approved_by": admin_oid, "provider.approved_at": utcnow()}})
    return res.matched_count == 1


def provider_availability(provider_doc):
    saved = provider_doc.get("provider", {}).get("availability") or DEFAULT_PROVIDER_AVAILABILITY
    return {"days": saved.get("days", list(range(7))), "start": saved.get("start", "08:00"),
            "end": saved.get("end", "18:00")}


def provider_available_for(provider_doc, booking):
    start = booking.get("start_dt")
    if start is None:
        return False
    if not provider_doc.get("provider", {}).get("availability"):
        return True
    availability = provider_availability(provider_doc)
    end = start + timedelta(minutes=int(booking.get("duration_minutes", 0)))
    return (start.weekday() in availability["days"] and end.date() == start.date()
            and start.strftime("%H:%M") >= availability["start"]
            and end.strftime("%H:%M") <= availability["end"])


def save_provider_availability(provider_id, days, start_time, end_time):
    try:
        normalized_days = sorted({int(day) for day in days})
        start = datetime.strptime(start_time, "%H:%M").strftime("%H:%M")
        end = datetime.strptime(end_time, "%H:%M").strftime("%H:%M")
    except (TypeError, ValueError):
        raise ValueError("Choose at least one valid weekday and valid working hours.")
    if not normalized_days or any(day < 0 or day > 6 for day in normalized_days) or start >= end:
        raise ValueError("Choose at least one valid weekday and an end time after the start time.")

    provider = find_by_id(provider_id, role="provider")
    if provider is None:
        return False
    proposed = {**provider, "provider": {**provider.get("provider", {}),
                                           "availability": {"days": normalized_days, "start": start, "end": end}}}
    active = get_db().bookings.find({"provider_id": provider_id,
                                     "status": {"$in": ["Assigned", "Accepted", "In Progress"]}})
    if any(not provider_available_for(proposed, booking) for booking in active):
        return False
    return get_db().users.update_one({"_id": provider_id, "role": "provider"},
                                     {"$set": {"provider.availability": proposed["provider"]["availability"]}}).matched_count == 1


def get_assignable_provider(oid):
    """Provider that exists, is active AND approved - otherwise None."""
    return get_db().users.find_one({"_id": oid, "role": "provider", "active": True, "provider.approved": True})


def assignable_providers():
    return list(get_db().users.find({"role": "provider", "active": True, "provider.approved": True}).sort("name", 1))


def count(role, **extra):
    return get_db().users.count_documents({"role": role, **extra})


def verify_password(doc, password):
    return check_password_hash(doc["password_hash"], password or "")
