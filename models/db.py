"""MongoDB connection, indexes and schema validators."""
from datetime import datetime, timezone

from flask import current_app
from pymongo import ASCENDING, DESCENDING, MongoClient
from pymongo.errors import OperationFailure


def utcnow():
    """Naive UTC datetime (PyMongo stores/returns naive UTC by default)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def get_db():
    return current_app.extensions["homecare_db"]


def connect(uri, db_name):
    client = MongoClient(uri, serverSelectionTimeoutMS=5000)
    client.admin.command("ping")  # fail fast with a clear error
    return client.get_default_database(default=db_name)


NUM = ["double", "int", "long", "decimal"]
BOOKING_STATUSES = ["Pending", "Assigned", "Accepted", "In Progress", "Completed", "Cancelled", "Rejected"]

VALIDATORS = {
    "users": {"bsonType": "object",
              "required": ["name", "email", "password_hash", "role", "active", "created_at"],
              "properties": {"role": {"enum": ["customer", "provider", "admin"]},
                             "active": {"bsonType": "bool"},
                             "email": {"bsonType": "string"}}},
    "services": {"bsonType": "object",
                 "required": ["name", "category", "price", "duration_minutes", "is_active"],
                 "properties": {"price": {"bsonType": NUM, "minimum": 0},
                                "duration_minutes": {"bsonType": ["int", "long"], "minimum": 15},
                                "is_active": {"bsonType": "bool"}}},
    "bookings": {"bsonType": "object",
                 "required": ["customer_id", "service_id", "booking_date", "booking_time", "status", "payment_status"],
                 "properties": {"customer_id": {"bsonType": "objectId"},
                                "service_id": {"bsonType": "objectId"},
                                "provider_id": {"bsonType": ["objectId", "null"]},
                                "status": {"enum": BOOKING_STATUSES},
                                "payment_status": {"enum": ["Unpaid", "Paid", "Refunded"]}}},
    "reviews": {"bsonType": "object",
                "required": ["booking_id", "customer_id", "provider_id", "rating"],
                "properties": {"rating": {"bsonType": ["int", "long"], "minimum": 1, "maximum": 5}}},
}


def ensure_indexes(db):
    db.users.create_index([("email", ASCENDING)], unique=True, name="uniq_email")
    db.users.create_index([("role", ASCENDING), ("active", ASCENDING)], name="role_active")
    db.services.create_index([("name", ASCENDING)], unique=True, name="uniq_service_name")
    db.services.create_index([("is_active", ASCENDING), ("category", ASCENDING)], name="active_category")
    db.bookings.create_index([("customer_id", ASCENDING), ("start_dt", DESCENDING)], name="customer_history")
    db.bookings.create_index([("provider_id", ASCENDING), ("start_dt", ASCENDING)], name="provider_schedule")
    db.bookings.create_index([("status", ASCENDING)], name="status")
    db.reviews.create_index([("booking_id", ASCENDING)], unique=True, name="uniq_review_per_booking")
    db.reviews.create_index([("provider_id", ASCENDING)], name="review_provider")
    db.notifications.create_index([("user_id", ASCENDING), ("created_at", DESCENDING)], name="user_notifications")
    db.notifications.create_index([("user_id", ASCENDING), ("read_at", ASCENDING)], name="unread_notifications")
    # One document per (provider, 30-minute block). The unique index is what makes
    # double-booking impossible even under concurrent requests.
    db.provider_slots.create_index([("provider_id", ASCENDING), ("block", ASCENDING)],
                                   unique=True, name="uniq_provider_block")
    db.provider_slots.create_index([("booking_id", ASCENDING)], name="slot_booking")


def apply_validators(db):
    existing = set(db.list_collection_names())
    for name, schema in VALIDATORS.items():
        try:
            if name in existing:
                db.command("collMod", name, validator={"$jsonSchema": schema}, validationLevel="moderate")
            else:
                db.create_collection(name, validator={"$jsonSchema": schema}, validationLevel="moderate")
        except OperationFailure as exc:  # e.g. restricted Atlas tier
            current_app.logger.warning("Could not apply validator for %s: %s", name, exc)


def init_db(app, db=None):
    if db is None:
        db = connect(app.config["MONGO_URI"], app.config["MONGO_DB_NAME"])
        with app.app_context():
            apply_validators(db)
    ensure_indexes(db)
    app.extensions["homecare_db"] = db
    return db
