from pymongo.errors import DuplicateKeyError

from .db import get_db, utcnow


class ReviewError(Exception):
    def __init__(self, message, status_code=400):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def create_review(booking, customer_id, rating, comment):
    """Eligibility: own booking, Completed, has a provider, not yet reviewed."""
    if booking is None or booking["customer_id"] != customer_id:
        raise ReviewError("Booking not found.", 404)
    if booking["status"] != "Completed" or not booking.get("provider_id"):
        raise ReviewError("Only completed bookings can be reviewed.", 409)
    if not isinstance(rating, int) or not 1 <= rating <= 5:
        raise ReviewError("Rating must be a whole number from 1 to 5.")
    if len(comment) > 1000:
        raise ReviewError("Comment must be at most 1000 characters.")
    doc = {"booking_id": booking["_id"], "customer_id": customer_id, "provider_id": booking["provider_id"],
           "service_id": booking["service_id"], "rating": rating, "comment": comment, "created_at": utcnow()}
    try:
        doc["_id"] = get_db().reviews.insert_one(doc).inserted_id
    except DuplicateKeyError:
        raise ReviewError("This booking has already been reviewed.", 409)
    return doc


def booking_ids_reviewed(booking_ids):
    return {r["booking_id"] for r in get_db().reviews.find({"booking_id": {"$in": list(booking_ids)}}, {"booking_id": 1})}


def recent(limit=50, **flt):
    return list(get_db().reviews.find(flt).sort("created_at", -1).limit(limit))


def rating_summary(**flt):
    rows = list(get_db().reviews.aggregate([{"$match": flt}, {"$group": {"_id": None, "avg": {"$avg": "$rating"}, "n": {"$sum": 1}}}]))
    if not rows or not rows[0].get("n") or rows[0].get("avg") is None:
        return (None, 0)
    return (round(rows[0]["avg"], 1), rows[0]["n"])
