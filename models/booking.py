from .db import BOOKING_STATUSES, get_db  # noqa: F401

PAYMENT_STATUSES = ("Unpaid", "Paid", "Refunded")
ACTIVE_JOB_STATUSES = ("Assigned", "Accepted", "In Progress")
HISTORY_STATUSES = ("Completed", "Rejected", "Cancelled")


def get_booking(oid):
    return get_db().bookings.find_one({"_id": oid})


def for_customer(customer_id, limit=200):
    return list(get_db().bookings.find({"customer_id": customer_id}).sort("start_dt", -1).limit(limit))


def for_provider(provider_id, statuses, limit=200, ascending=True):
    return list(get_db().bookings.find({"provider_id": provider_id, "status": {"$in": list(statuses)}})
                .sort("start_dt", 1 if ascending else -1).limit(limit))


def list_all(status=None, limit=300):
    flt = {"status": status} if status in BOOKING_STATUSES else {}
    return list(get_db().bookings.find(flt).sort("created_at", -1).limit(limit))


def count(**flt):
    return get_db().bookings.count_documents(flt)
