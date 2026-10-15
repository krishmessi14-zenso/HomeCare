import threading
from io import BytesIO
from pathlib import Path

import pytest

from conftest import PW, future_date, login, make_booking, make_service, make_user
from models import booking as booking_model
from models import service as service_model
from models import user as user_model
from services import booking_service as bs


@pytest.fixture()
def admin(client, ctx):
    make_user("admin", "admin@example.com")
    login(client, "admin@example.com")


def test_non_admin_forbidden_everywhere(client, ctx):
    make_user("customer", "c@example.com")
    login(client, "c@example.com")
    for path in ("/admin/dashboard", "/admin/services", "/admin/users", "/admin/bookings", "/admin/reviews", "/admin/reports",
                 "/admin/services/new", "/admin/providers/new"):
        assert client.get(path).status_code == 403, path
    assert client.post("/admin/services/new", data={"name": "X"}).status_code == 403


def test_admin_dashboard_stats(client, admin):
    make_user("customer"), make_user("provider"), make_service()
    r = client.get("/admin/dashboard")
    assert r.status_code == 200 and b"Total customers" in r.data


def test_service_create_edit_deactivate(client, admin):
    form = {"name": "Roof Repair", "category": "Carpentry", "description": "Fix roofs and leaks properly.", "price": "1500",
            "duration_minutes": "120", "image": "", "is_active": "on"}
    assert client.post("/admin/services/new", data=form).status_code == 302
    s = service_model.search(active_only=False, q="Roof")[0]
    assert s["is_active"] and s["price"] == 1500.0
    assert client.post("/admin/services/new", data=form).status_code == 400  # duplicate name
    assert client.post("/admin/services/new", data={**form, "name": "Bad", "price": "-5"}).status_code == 400
    assert client.post("/admin/services/new", data={**form, "name": "Bad2", "image": "../../etc/passwd"}).status_code == 400
    assert client.post(f"/admin/services/{s['_id']}/edit", data={**form, "price": "1800", "is_active": "on"}).status_code == 302
    assert service_model.get_service(s["_id"])["price"] == 1800.0
    client.post(f"/admin/services/{s['_id']}/toggle")
    assert service_model.get_service(s["_id"])["is_active"] is False
    assert b"Roof Repair" not in client.get("/services").data  # hidden from customers
    assert client.get("/admin/services/zzz/edit").status_code == 404


def test_admin_uploads_service_image(client, admin):
    form = {"name": "Window Cleaning", "category": "House Cleaning", "description": "Clean interior and exterior windows.",
            "price": "800", "duration_minutes": "60", "is_active": "on"}
    image = (BytesIO(b"\x89PNG\r\n\x1a\nimage-data"), "windows.png", "image/png")
    response = client.post("/admin/services/new", data={**form, "image_file": image}, content_type="multipart/form-data")
    assert response.status_code == 302
    service = service_model.search(active_only=False, q="Window Cleaning")[0]
    assert service["image"].startswith("images/uploads/")
    uploaded_file = Path(client.application.static_folder) / service["image"]
    assert uploaded_file.is_file()
    assert client.get("/static/" + service["image"]).status_code == 200
    uploaded_file.unlink()

    invalid = (BytesIO(b"not-an-image"), "fake.png", "image/png")
    response = client.post("/admin/services/new", data={**form, "name": "Fake Image Service", "image_file": invalid},
                           content_type="multipart/form-data")
    assert response.status_code == 400
    assert service_model.search(active_only=False, q="Fake Image Service") == []


def test_admin_creates_and_approves_provider(client, admin):
    r = client.post("/admin/providers/new", data={"name": "Ravi P", "email": "ravi@example.com", "phone": "9876543210", "password": PW})
    assert r.status_code == 302
    p = user_model.find_by_email("ravi@example.com")
    assert p["role"] == "provider" and p["provider"]["approved"] is False
    assert user_model.get_assignable_provider(p["_id"]) is None  # unapproved: not assignable
    client.post(f"/admin/providers/{p['_id']}/approve")
    assert user_model.get_assignable_provider(p["_id"]) is not None
    client.post(f"/admin/providers/{p['_id']}/edit", data={"name": "Ravi Prakash", "email": "ravi@example.com", "phone": "9876543210"})
    assert user_model.find_by_email("ravi@example.com")["name"] == "Ravi Prakash"
    client.post(f"/admin/users/{p['_id']}/toggle")
    assert user_model.get_assignable_provider(p["_id"]) is None  # inactive: not assignable


def test_admin_assignment_via_http_and_validation(client, admin):
    s, c = make_service(), make_user("customer")
    good, unapproved, inactive = make_user("provider"), make_user("provider", approved=False), make_user("provider", active=False)
    b = make_booking(c, s)
    assert b"Select provider" in client.get("/admin/bookings").data
    for bad in (unapproved, inactive):
        client.post(f"/admin/bookings/{b['_id']}/assign", data={"provider_id": str(bad["_id"])})
        assert booking_model.get_booking(b["_id"])["status"] == "Pending"
    client.post(f"/admin/bookings/{b['_id']}/assign", data={"provider_id": "not-an-id"})
    assert client.post(f"/admin/bookings/{b['_id']}/assign", data={"provider_id": str(c["_id"])}).status_code == 302  # customer id is not a provider
    assert booking_model.get_booking(b["_id"])["status"] == "Pending"
    client.post(f"/admin/bookings/{b['_id']}/assign", data={"provider_id": str(good["_id"])})
    got = booking_model.get_booking(b["_id"])
    assert got["status"] == "Assigned" and got["provider_id"] == good["_id"]


def test_reassignment_only_when_status_permits(ctx):
    from models.user import User
    s, c = make_service(), make_user("customer")
    p1, p2 = make_user("provider"), make_user("provider")
    b = make_booking(c, s)
    bs.assign_provider(b["_id"], p1["_id"])
    assert bs.assign_provider(b["_id"], p2["_id"])["provider_id"] == p2["_id"]  # Assigned -> reassign ok
    bs.provider_action(b["_id"], User(p2), "accept")
    with pytest.raises(bs.BookingError) as e:  # Accepted -> locked
        bs.assign_provider(b["_id"], p1["_id"])
    assert e.value.status_code == 409


def test_overlapping_assignments_blocked(ctx):
    s60, c, p = make_service(minutes=60), make_user("customer"), make_user("provider")
    s120 = make_service("Long Job", minutes=120)
    long_job = make_booking(c, s120, time="10:00")      # 10:00-12:00
    overlap = make_booking(c, s60, time="11:00")        # 11:00-12:00 overlaps
    adjacent = make_booking(c, s60, time="12:00")       # 12:00-13:00 touches, no overlap
    bs.assign_provider(long_job["_id"], p["_id"])
    with pytest.raises(bs.BookingError) as e:
        bs.assign_provider(overlap["_id"], p["_id"])
    assert e.value.status_code == 409
    assert booking_model.get_booking(overlap["_id"])["status"] == "Pending"
    assert bs.assign_provider(adjacent["_id"], p["_id"])["status"] == "Assigned"
    assert p["_id"] not in [x["_id"] for x in bs.available_providers_for(booking_model.get_booking(overlap["_id"]))]


def test_cancel_frees_provider_time(ctx):
    s, c, p = make_service(), make_user("customer"), make_user("provider")
    b1, b2 = make_booking(c, s), make_booking(make_user("customer"), s)
    bs.assign_provider(b1["_id"], p["_id"])
    with pytest.raises(bs.BookingError):
        bs.assign_provider(b2["_id"], p["_id"])
    bs.cancel_booking(b1["_id"], "admin")
    assert bs.assign_provider(b2["_id"], p["_id"])["status"] == "Assigned"


def test_concurrent_conflicting_assignments_only_one_wins(app):
    with app.app_context():
        s, p = make_service(), make_user("provider")
        bookings = [make_booking(make_user("customer"), s) for _ in range(8)]  # all same slot
    results, lock = [], threading.Lock()

    def worker(b):
        with app.app_context():
            try:
                bs.assign_provider(b["_id"], p["_id"])
                outcome = "ok"
            except bs.BookingError as exc:
                outcome = exc.status_code
        with lock:
            results.append(outcome)

    threads = [threading.Thread(target=worker, args=(b,)) for b in bookings]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert results.count("ok") == 1 and results.count(409) == 7


def test_admin_cannot_assign_completed_or_cancelled(ctx):
    s, c, p = make_service(), make_user("customer"), make_user("provider")
    b = make_booking(c, s)
    bs.cancel_booking(b["_id"], "admin")
    with pytest.raises(bs.BookingError) as e:
        bs.assign_provider(b["_id"], p["_id"])
    assert e.value.status_code == 409


def test_cannot_deactivate_provider_with_active_jobs(client, admin):
    from models.user import User
    s, c, p = make_service(), make_user("customer"), make_user("provider")
    b = make_booking(c, s)
    bs.assign_provider(b["_id"], p["_id"])
    bs.provider_action(b["_id"], User(p), "accept")
    client.post(f"/admin/users/{p['_id']}/toggle")
    assert user_model.find_by_id(p["_id"])["active"] is True


def test_admin_pages_render(client, admin):
    s, c, p = make_service(), make_user("customer"), make_user("provider")
    make_booking(c, s)
    for path in ("/admin/dashboard", "/admin/services", "/admin/services/new", f"/admin/services/{s['_id']}/edit", "/admin/users",
                 "/admin/providers/new", f"/admin/providers/{p['_id']}/edit", "/admin/bookings", "/admin/bookings?status=Pending",
                 "/admin/reviews", "/admin/reports"):
        assert client.get(path).status_code == 200, path
