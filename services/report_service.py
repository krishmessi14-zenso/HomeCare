from models import user as user_model
from models.db import get_db


def dashboard_stats():
    db = get_db()
    return {
        "customers": user_model.count("customer"),
        "providers": user_model.count("provider", active=True, **{"provider.approved": True}),
        "services": db.services.count_documents({"is_active": True}),
        "pending": db.bookings.count_documents({"status": "Pending"}),
        "completed": db.bookings.count_documents({"status": "Completed"}),
        "unapproved_providers": user_model.count("provider", **{"provider.approved": False}),
    }


def reports():
    db = get_db()
    by_status = {r["_id"]: r["n"] for r in db.bookings.aggregate([{"$group": {"_id": "$status", "n": {"$sum": 1}}}])}
    by_service = list(db.bookings.aggregate([
        {"$group": {"_id": "$service_name", "total": {"$sum": 1},
                    "completed": {"$sum": {"$cond": [{"$eq": ["$status", "Completed"]}, 1, 0]}},
                    "value": {"$sum": {"$cond": [{"$eq": ["$status", "Completed"]}, "$price", 0]}}}},
        {"$sort": {"total": -1}}]))
    ratings = list(db.reviews.aggregate([
        {"$group": {"_id": "$provider_id", "avg": {"$avg": "$rating"}, "n": {"$sum": 1}}}, {"$sort": {"avg": -1}}]))
    names = user_model.names_by_ids([r["_id"] for r in ratings])
    for r in ratings:
        r["name"] = names.get(r["_id"], {}).get("name", "Unknown")
        r["avg"] = round(r["avg"], 2)
    return {"by_status": by_status, "by_service": by_service, "ratings": ratings}
