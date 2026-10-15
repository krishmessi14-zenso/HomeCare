from .db import get_db, utcnow


def create_for_user(user_id, message, href, booking_id=None):
    if user_id is None:
        return
    if not href.startswith("/") or href.startswith("//"):
        href = "/"
    get_db().notifications.insert_one({
        "user_id": user_id,
        "booking_id": booking_id,
        "message": message[:240],
        "href": href,
        "created_at": utcnow(),
        "read_at": None,
    })


def create_for_role(role, message, href, booking_id=None, exclude_user_id=None):
    users = get_db().users.find({"role": role, "active": True}, {"_id": 1})
    for user in users:
        if user["_id"] != exclude_user_id:
            create_for_user(user["_id"], message, href, booking_id)


def for_user(user_id, limit=100):
    return list(get_db().notifications.find({"user_id": user_id}).sort("created_at", -1).limit(limit))


def unread_count(user_id):
    return get_db().notifications.count_documents({"user_id": user_id, "read_at": None})


def mark_read(notification_id, user_id):
    return get_db().notifications.update_one(
        {"_id": notification_id, "user_id": user_id, "read_at": None},
        {"$set": {"read_at": utcnow()}}).modified_count == 1


def mark_all_read(user_id):
    return get_db().notifications.update_many(
        {"user_id": user_id, "read_at": None}, {"$set": {"read_at": utcnow()}}).modified_count