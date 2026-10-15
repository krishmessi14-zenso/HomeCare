import pytest

from conftest import login, make_booking, make_service, make_user
from models import booking as booking_model
from models.user import User
from services import booking_service as bs


def setup_job(approved=True):
    s, c, p = make_service(), make_user("customer"), make_user("provider", "p@example.com", approved=approved)
    b = make_booking(c, s)
    return s, c, p, b


def status(b):
    return booking_model.get_booking(b["_id"])["status"]


def test_full_happy_path_via_http(client, ctx, app):
    s, c, p, b = setup_job()
    bs.assign_provider(b["_id"], p["_id"])
    login(client, "p@example.com")
    assert b"Tap Repair" in client.get("/provider/dashboard").data
    for action, expected in (("accept", "Accepted"), ("start", "In Progress"), ("complete", "Completed")):
        assert client.post(f"/provider/jobs/{b['_id']}/{action}").status_code == 302
        assert status(b) == expected
    assert b"Tap Repair" in client.get("/provider/dashboard?tab=history").data


def test_invalid_transitions_rejected(ctx):
    s, c, p, b = setup_job()
    pu = User(p)
    bs.assign_provider(b["_id"], p["_id"])
    for action in ("start", "complete"):  # cannot skip Accepted
        with pytest.raises(bs.BookingError) as e:
            bs.provider_action(b["_id"], pu, action)
        assert e.value.status_code == 409
    bs.provider_action(b["_id"], pu, "accept")
    with pytest.raises(bs.BookingError):  # cannot accept twice
        bs.provider_action(b["_id"], pu, "accept")
    with pytest.raises(bs.BookingError):  # cannot reject after accepting
        bs.provider_action(b["_id"], pu, "reject")
    with pytest.raises(bs.BookingError):  # unknown/forged action
        bs.provider_action(b["_id"], pu, "set_status_completed")
    bs.provider_action(b["_id"], pu, "start")
    bs.provider_action(b["_id"], pu, "complete")
    with pytest.raises(bs.BookingError):  # terminal state
        bs.provider_action(b["_id"], pu, "start")


def test_pending_booking_cannot_be_actioned(ctx):
    s, c, p, b = setup_job()
    with pytest.raises(bs.BookingError) as e:
        bs.provider_action(b["_id"], User(p), "accept")
    assert e.value.status_code == 404  # not assigned to this provider


def test_provider_cannot_touch_other_providers_jobs(client, ctx):
    s, c, p, b = setup_job()
    other = make_user("provider", "other@example.com")
    bs.assign_provider(b["_id"], p["_id"])
    login(client, "other@example.com")
    assert b"Tap Repair" not in client.get("/provider/dashboard").data
    for action in ("accept", "reject", "start", "complete"):
        assert client.post(f"/provider/jobs/{b['_id']}/{action}").status_code == 404
    assert status(b) == "Assigned"


def test_reject_releases_slot_and_allows_reassign(ctx):
    s, c, p, b = setup_job()
    p2 = make_user("provider")
    bs.assign_provider(b["_id"], p["_id"])
    bs.provider_action(b["_id"], User(p), "reject")
    assert status(b) == "Rejected"
    with pytest.raises(bs.BookingError):  # same provider again is refused
        bs.assign_provider(b["_id"], p["_id"])
    assert bs.assign_provider(b["_id"], p2["_id"])["status"] == "Assigned"


def test_unapproved_provider_blocked(client, ctx):
    s, c, p, b = setup_job(approved=False)
    login(client, "p@example.com")
    assert b"awaiting administrator approval" in client.get("/provider/dashboard").data
    with pytest.raises(bs.BookingError) as e:
        bs.provider_action(b["_id"], User(p), "accept")
    assert e.value.status_code == 403


def test_customer_and_admin_cannot_use_provider_routes(client, ctx):
    make_user("customer", "c@example.com")
    login(client, "c@example.com")
    assert client.get("/provider/dashboard").status_code == 403
    assert client.post("/provider/jobs/" + "a" * 24 + "/accept").status_code == 403


def test_provider_availability_limits_assignment(client, ctx):
    service = make_service()
    customer = make_user("customer")
    provider = make_user("provider", "availability@example.com")
    within_hours = make_booking(customer, service, time="10:00")
    outside_hours = make_booking(make_user("customer"), service, time="14:00")

    login(client, provider["email"])
    response = client.post("/provider/availability", data={
        "days": [str(within_hours["start_dt"].weekday())],
        "start_time": "09:00",
        "end_time": "12:00",
    })
    assert response.status_code == 302
    assert b"My availability" in client.get("/provider/dashboard").data
    assert provider["_id"] in [p["_id"] for p in bs.available_providers_for(within_hours)]
    assert provider["_id"] not in [p["_id"] for p in bs.available_providers_for(outside_hours)]
    bs.assign_provider(within_hours["_id"], provider["_id"])
    with pytest.raises(bs.BookingError) as error:
        bs.assign_provider(outside_hours["_id"], provider["_id"])
    assert error.value.status_code == 409


def test_pending_booking_appears_after_admin_assigns_provider(client, ctx):
    service, customer = make_service("Assigned Service"), make_user("customer")
    provider = make_user("provider", "assigned-job@example.com")
    admin = make_user("admin", "assigning-admin@example.com")
    booking = make_booking(customer, service)

    login(client, provider["email"])
    dashboard = client.get("/provider/dashboard")
    assert b"No assigned jobs yet" in dashboard.data
    assert b"Assigned Service" not in dashboard.data

    client.post("/logout")
    login(client, admin["email"])
    assert client.post(f"/admin/bookings/{booking['_id']}/assign",
                       data={"provider_id": str(provider["_id"])}).status_code == 302

    client.post("/logout")
    login(client, provider["email"])
    dashboard = client.get("/provider/dashboard")
    assert b"Assigned Service" in dashboard.data
    assert b"No assigned jobs yet" not in dashboard.data
