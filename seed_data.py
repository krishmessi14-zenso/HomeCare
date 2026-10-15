"""Insert sample services. Safe to re-run: existing services (matched by name) are left untouched,
so edits made by an administrator are never overwritten. No users or passwords are created.

    python seed_data.py
"""
import sys

from pymongo.errors import PyMongoError

from app import create_app
from config import ConfigError
from models.db import get_db, utcnow

SAMPLE_SERVICES = [
    ("Plumbing", "Tap, pipe and leak repair", "Fix leaking taps, burst pipes, blocked drains and fittings.", 499, 60),
    ("Plumbing", "Bathroom Fitting Installation", "Installation of taps, showers, basins and bathroom fittings.", 899, 120),
    ("Electrical Repairs", "Switch, socket and wiring repair", "Diagnose and repair faulty switches, sockets, fans and wiring.", 399, 60),
    ("Electrical Repairs", "Light & Fan Installation", "Mount ceiling fans, tube lights and decorative lighting safely.", 349, 45),
    ("House Cleaning", "Regular House Cleaning", "Sweeping, mopping, dusting and bathroom/kitchen surface cleaning.", 799, 120),
    ("Deep Cleaning", "Full Home Deep Cleaning", "Intensive top-to-bottom cleaning including kitchen degreasing and bathroom descaling.", 2499, 300),
    ("Carpentry", "Furniture Repair & Assembly", "Repair wardrobes, doors and beds, or assemble flat-pack furniture.", 599, 90),
    ("Painting", "Single Room Painting", "Wall preparation and two coats of paint for one standard room.", 3499, 480),
    ("AC Repair", "AC Service & Gas Check", "Filter cleaning, cooling check, leak inspection and gas top-up assessment.", 649, 75),
    ("Appliance Repair", "Washing Machine / Refrigerator Repair", "Inspection and repair of common household appliance faults.", 549, 60),
    ("Gardening", "Garden Maintenance", "Lawn trimming, pruning, weeding and general garden tidy-up.", 449, 90),
    ("Pest Control", "General Pest Control", "Treatment for cockroaches, ants and other common household pests.", 999, 90),
]


def main():
    try:
        app = create_app()
    except ConfigError as exc:
        sys.exit(f"CONFIGURATION ERROR:\n{exc}")
    except PyMongoError:
        sys.exit("DATABASE ERROR: could not connect to MongoDB. Check MONGO_URI and that MongoDB is running.")
    added = 0
    with app.app_context():
        col = get_db().services
        for category, name, desc, price, minutes in SAMPLE_SERVICES:
            now = utcnow()
            res = col.update_one({"name": name}, {"$setOnInsert": {
                "name": name, "category": category, "description": desc, "price": float(price),
                "duration_minutes": minutes, "image": "images/placeholder.svg", "is_active": True,
                "created_at": now, "updated_at": now}}, upsert=True)
            added += 1 if res.upserted_id else 0
    print(f"Seed complete: {added} service(s) added, {len(SAMPLE_SERVICES) - added} already existed.")


if __name__ == "__main__":
    main()
