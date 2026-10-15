import re

from pymongo.errors import DuplicateKeyError

from utils.validators import clean_text, parse_int, parse_price

from .db import get_db, utcnow

DEFAULT_CATEGORIES = ["Plumbing", "Electrical Repairs", "House Cleaning", "Deep Cleaning", "Carpentry",
                      "Painting", "AC Repair", "Appliance Repair", "Gardening", "Pest Control"]
IMAGE_RE = re.compile(r"^[A-Za-z0-9_\-./]{1,200}$")


class DuplicateServiceError(Exception):
    pass


def parse_service_form(form):
    errors = []
    data = {
        "name": clean_text(form.get("name")),
        "category": clean_text(form.get("category")),
        "description": clean_text(form.get("description"), multiline=True),
        "image": clean_text(form.get("image")),
        "price": parse_price(form.get("price")),
        "duration_minutes": parse_int(form.get("duration_minutes"), 15, 720),
        "is_active": form.get("is_active") == "on",
    }
    if not 2 <= len(data["name"]) <= 100:
        errors.append("Service name must be 2-100 characters.")
    if not 2 <= len(data["category"]) <= 50:
        errors.append("Category must be 2-50 characters.")
    if not 10 <= len(data["description"]) <= 1000:
        errors.append("Description must be 10-1000 characters.")
    if data["price"] is None:
        errors.append("Price must be a number greater than 0 (max 1,000,000).")
    if data["duration_minutes"] is None:
        errors.append("Duration must be a whole number of minutes between 15 and 720.")
    img = data["image"]
    if img and (not IMAGE_RE.match(img) or ".." in img or img.startswith("/")):
        errors.append("Image must be a relative path inside static/ (e.g. images/placeholder.svg).")
    return data, errors


def create_service(data):
    now = utcnow()
    doc = {**data, "created_at": now, "updated_at": now}
    try:
        doc["_id"] = get_db().services.insert_one(doc).inserted_id
    except DuplicateKeyError:
        raise DuplicateServiceError(data["name"])
    return doc


def update_service(oid, data):
    try:
        res = get_db().services.update_one({"_id": oid}, {"$set": {**data, "updated_at": utcnow()}})
    except DuplicateKeyError:
        raise DuplicateServiceError(data["name"])
    return res.matched_count == 1


def set_active(oid, active):
    return get_db().services.update_one({"_id": oid}, {"$set": {"is_active": bool(active), "updated_at": utcnow()}}).matched_count == 1


def get_service(oid):
    return get_db().services.find_one({"_id": oid})


def _search_filter(active_only=True, q=None, category=None, min_price=None, max_price=None):
    flt = {"is_active": True} if active_only else {}
    if q:
        rx = {"$regex": re.escape(q[:60]), "$options": "i"}
        flt["$or"] = [{"name": rx}, {"description": rx}, {"category": rx}]
    if category:
        flt["category"] = category
    price = {}
    if min_price is not None:
        price["$gte"] = min_price
    if max_price is not None:
        price["$lte"] = max_price
    if price:
        flt["price"] = price
    return flt


def search(active_only=True, q=None, category=None, min_price=None, max_price=None, sort="name", limit=200, skip=0):
    flt = _search_filter(active_only, q, category, min_price, max_price)
    order = {"price_asc": [("price", 1)], "price_desc": [("price", -1)]}.get(sort, [("name", 1)])
    return list(get_db().services.find(flt).sort(order).skip(max(0, skip)).limit(limit))


def count_search(active_only=True, q=None, category=None, min_price=None, max_price=None):
    return get_db().services.count_documents(_search_filter(active_only, q, category, min_price, max_price))


def category_counts():
    pipeline = [{"$match": {"is_active": True}}, {"$group": {"_id": "$category", "n": {"$sum": 1}}}, {"$sort": {"_id": 1}}]
    return [(r["_id"], r["n"]) for r in get_db().services.aggregate(pipeline)]


def count_active():
    return get_db().services.count_documents({"is_active": True})
