import os
import sys
from datetime import date, timedelta

import mongomock
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app  # noqa: E402
from models import service as service_model  # noqa: E402
from models import user as user_model  # noqa: E402
from services import booking_service as bs  # noqa: E402

PW = "Passw0rdTest"


@pytest.fixture()
def app():
    # A brand-new in-memory mongomock database per test: no real data can ever be touched.
    app = create_app({"TESTING": True, "SECRET_KEY": "test-secret-key-not-for-production",
                      "WTF_CSRF_ENABLED": False, "MONGO_DB": mongomock.MongoClient().db})
    # Test-only: the shared `ctx` fixture keeps one app context open, so Flask-Login's cached
    # g._login_user would leak between test clients. In production every request gets its own context.
    from flask import g
    
    @app.before_request
    def _reset_login_cache():
        g.pop("_login_user", None)  # returns None -> request continues

    yield app


@pytest.fixture()
def ctx(app):
    with app.app_context():
        yield


@pytest.fixture()
def client(app):
    return app.test_client()


def make_user(role="customer", email=None, approved=True, active=True, name=None):
    email = email or f"{role}{os.urandom(3).hex()}@example.com"
    return user_model.create_user(name or role.title() + " Test", email, "9876543210", PW, role=role,
                                  approved=approved, active=active)


def make_service(name="Tap Repair", price=500.0, minutes=60, active=True):
    return service_model.create_service({"name": name, "category": "Plumbing", "description": "Fix leaking taps and pipes.",
                                         "price": price, "duration_minutes": minutes, "image": "", "is_active": active})


def login(client, email, password=PW):
    return client.post("/login", data={"email": email, "password": password})


def future_date(days=3):
    return (date.today() + timedelta(days=days)).isoformat()


def make_booking(customer, service, days=3, time="10:00"):
    return bs.create_booking(customer["_id"], service, future_date(days), time, "12 Green Street, Madurai", "Tap is leaking badly")
