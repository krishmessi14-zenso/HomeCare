from datetime import datetime, timedelta

import pytest

from conftest import future_date, login, make_booking, make_service, make_user
from models import booking as booking_model
from models import review as review_model
from services import booking_service as bs


def test_public_pages_render(client, ctx):
    s = make_service()
    for path in ("/", "/services", f"/services/{s['_id']}", "/reviews", "/login", "/register"):
        assert client.get(path).status_code == 200, path
    assert b"Tap Repair" in client.get("/services?q=tap").data
    assert b"Tap Repair" not in client.get("/services?q=zzzz").data
    assert b"Tap Repair" not in client.get("/services?min_price=1000").data


def test_error_pages(client, ctx):
    assert client.get("/nope").status_code == 404
    assert b"Page not found" in client.get("/nope").data
    login(client, make_user("customer", "c@example.com")["email"])
    assert client.get("/admin/dashboard").status_code == 403
    assert b"Access denied" in client.get("/admin/dashboard").data


def test_invalid_object_ids_return_404(client, ctx):
    login(client, make_user("customer", "c@example.com")["email"])
    for path in ("/services/not-an-id", "/services/" + "z" * 24, "/customer/book/123", "/customer/bookings/xyz/review"):
        assert client.get(path).status_code == 404, path
    assert client.post("/customer/bookings/xyz/cancel").status_code == 404


def test_inactive_service_hidden(client, ctx):
    s = make_service(active=False)
    assert client.get(f"/services/{s['_id']}").status_code == 404
    assert b"Tap Repair" not in client.get("/services").data


def test_booking_creation_via_form(client, ctx):
    s = make_service()
    c = make_user("customer", "c@example.com")
    login(client, "c@example.com")
    r = client.post(f"/customer/book/{s['_id']}", data={"booking_date": future_date(), "booking_time": "10:00",
                                                         "address": "12 Green Street, Madurai", "notes": "Tap leaking"})
    assert r.status_code == 302
    b = booking_model.for_customer(c["_id"])[0]
    assert b["status"] == "Pending" and b["payment_status"] == "Unpaid" and b["price"] == 500.0 and b["service_name"] == "Tap Repair"


@pytest.mark.parametrize("kwargs", [
    {"date": "2001-01-01"}, {"date": "garbage"}, {"time": "03:00"}, {"time": "10:30"},
    {"address": "short"}, {"notes": "x"}, {"date": future_date(500)},
])
def test_booking_validation(ctx, kwargs):
    s, c = make_service(), make_user("customer")
    args = dict(date=future_date(), time="10:00", address="12 Green Street, Madurai", notes="Tap leaking")
    args.update(kwargs)
    with pytest.raises(bs.BookingError):
        bs.create_booking(c["_id"], s, args["date"], args["time"], args["address"], args["notes"])


def test_cannot_book_inactive_service(ctx):
    s, c = make_service(active=False), make_user("customer")
    with pytest.raises(bs.BookingError):
        bs.create_booking(c["_id"], s, future_date(), "10:00", "12 Green Street, Madurai", "Tap leaking")


def test_duplicate_booking_same_slot_rejected(ctx):
    s, c = make_service(), make_user("customer")
    make_booking(c, s)
    with pytest.raises(bs.BookingError) as e:
        make_booking(c, s)
    assert e.value.status_code == 409


def test_customer_cannot_cancel_or_view_others_bookings(client, ctx):
    s = make_service()
    owner, other = make_user("customer", "o@example.com"), make_user("customer", "x@example.com")
    b = make_booking(owner, s)
    login(client, "x@example.com")
    assert client.post(f"/customer/bookings/{b['_id']}/cancel").status_code == 404
    assert client.get(f"/customer/bookings/{b['_id']}/review").status_code == 404
    assert booking_model.get_booking(b["_id"])["status"] == "Pending"
    assert b"Tap Repair" not in client.get("/customer/dashboard").data  # dashboard lists own bookings only


def test_cancellation_rules(ctx):
    s, c = make_service(), make_user("customer")
    p = make_user("provider")
    b = make_booking(c, s)
    assert bs.cancel_booking(b["_id"], "customer", customer_id=c["_id"])["status"] == "Cancelled"
    with pytest.raises(bs.BookingError):  # already cancelled
        bs.cancel_booking(b["_id"], "customer", customer_id=c["_id"])
    # In Progress / Completed cannot be cancelled
    b2 = make_booking(c, s, time="12:00")
    bs.assign_provider(b2["_id"], p["_id"])
    from flask_login import UserMixin  # noqa
    from models.user import User
    pu = User(p)
    bs.provider_action(b2["_id"], pu, "accept")
    bs.provider_action(b2["_id"], pu, "start")
    with pytest.raises(bs.BookingError) as e:
        bs.cancel_booking(b2["_id"], "customer", customer_id=c["_id"])
    assert e.value.status_code == 409


def test_accepted_booking_cancellation_cutoff(ctx):
    from models.db import get_db
    from models.user import User
    s, c, p = make_service(), make_user("customer"), make_user("provider")
    b = make_booking(c, s)
    bs.assign_provider(b["_id"], p["_id"])
    bs.provider_action(b["_id"], User(p), "accept")
    assert bs.cancel_booking(b["_id"], "customer", customer_id=c["_id"])["status"] == "Cancelled"  # >2h ahead
    b2 = make_booking(c, s, time="14:00")
    bs.assign_provider(b2["_id"], p["_id"])
    bs.provider_action(b2["_id"], User(p), "accept")
    get_db().bookings.update_one({"_id": b2["_id"]}, {"$set": {"start_dt": datetime.now() + timedelta(minutes=30)}})
    with pytest.raises(bs.BookingError):
        bs.cancel_booking(b2["_id"], "customer", customer_id=c["_id"])


def _completed_booking():
    from models.user import User
    s, c, p = make_service(), make_user("customer", "rc@example.com"), make_user("provider")
    b = make_booking(c, s)
    bs.assign_provider(b["_id"], p["_id"])
    for a in ("accept", "start", "complete"):
        bs.provider_action(b["_id"], User(p), a)
    return b, c, p


def test_review_flow_uniqueness_and_eligibility(client, ctx):
    b, c, p = _completed_booking()
    login(client, "rc@example.com")
    assert client.post(f"/customer/bookings/{b['_id']}/review", data={"rating": "9", "comment": "x"}).status_code == 400  # bad rating
    assert client.post(f"/customer/bookings/{b['_id']}/review", data={"rating": "5", "comment": "Great"}).status_code == 302
    r = client.post(f"/customer/bookings/{b['_id']}/review", data={"rating": "4", "comment": "again"})
    assert r.status_code == 409  # unique per booking
    assert review_model.rating_summary(provider_id=p["_id"]) == (5.0, 1)
    assert b"Great" in client.get("/reviews").data


def test_review_requires_completed_booking(ctx):
    s, c = make_service(), make_user("customer")
    b = make_booking(c, s)
    with pytest.raises(review_model.ReviewError) as e:
        review_model.create_review(b, c["_id"], 5, "nope")
    assert e.value.status_code == 409


def test_other_customer_cannot_review(ctx):
    b, c, p = _completed_booking()
    other = make_user("customer")
    with pytest.raises(review_model.ReviewError) as e:
        review_model.create_review(b, other["_id"], 5, "hijack")
    assert e.value.status_code == 404


def test_calendar_is_scoped_to_logged_in_role(client, ctx):
    customer = make_user("customer", "calendar-customer@example.com")
    other_customer = make_user("customer", "calendar-other@example.com")
    provider = make_user("provider", "calendar-provider@example.com")
    own_booking = make_booking(customer, make_service("Calendar Plumbing"))
    other_booking = make_booking(other_customer, make_service("Private Cleaning"), time="12:00")
    bs.assign_provider(own_booking["_id"], provider["_id"])
    month_args = {"year": own_booking["start_dt"].year, "month": own_booking["start_dt"].month}

    login(client, customer["email"])
    customer_calendar = client.get("/calendar", query_string=month_args)
    assert customer_calendar.status_code == 200
    assert b"Calendar Plumbing" in customer_calendar.data and b"Private Cleaning" not in customer_calendar.data

    client.post("/logout")
    login(client, provider["email"])
    provider_calendar = client.get("/calendar", query_string=month_args)
    assert b"Calendar Plumbing" in provider_calendar.data and b"Private Cleaning" not in provider_calendar.data

    admin = make_user("admin", "calendar-admin@example.com")
    client.post("/logout")
    login(client, admin["email"])
    admin_calendar = client.get("/calendar", query_string=month_args)
    assert b"Calendar Plumbing" in admin_calendar.data and b"Private Cleaning" in admin_calendar.data


def test_calendar_requires_login_and_rejects_invalid_month(client, ctx):
    assert client.get("/calendar").status_code == 302
    login(client, make_user("customer", "calendar-invalid@example.com")["email"])
    assert client.get("/calendar?year=2026&month=13").status_code == 404


def test_service_search_pagination_preserves_filters(client, ctx):
    for number in range(11):
        make_service(f"Pageable Plumbing {number:02d}")

    first_page = client.get("/services?q=Pageable&category=Plumbing&page=1")
    second_page = client.get("/services?q=Pageable&category=Plumbing&page=2")
    assert first_page.status_code == second_page.status_code == 200
    assert b"Pageable Plumbing 00" in first_page.data and b"Pageable Plumbing 10" not in first_page.data
    assert b"Pageable Plumbing 10" in second_page.data and b"Pageable Plumbing 00" not in second_page.data
    assert b"q=Pageable" in second_page.data and b"category=Plumbing" in second_page.data
    assert b"Showing 10" in second_page.data and b"of 11 services" in second_page.data
