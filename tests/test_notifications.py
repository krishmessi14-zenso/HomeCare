from conftest import login, make_booking, make_service, make_user
from models import notification as notification_model
from services import booking_service as bs
from models.user import User


def test_booking_events_notify_users_and_enforce_ownership(client, ctx):
    admin = make_user("admin", "notify-admin@example.com")
    customer = make_user("customer", "notify-customer@example.com")
    provider = make_user("provider", "notify-provider@example.com")
    booking = make_booking(customer, make_service())

    assert len(notification_model.for_user(admin["_id"])) == 1
    bs.assign_provider(booking["_id"], provider["_id"])
    provider_items = notification_model.for_user(provider["_id"])
    customer_items = notification_model.for_user(customer["_id"])
    assert len(provider_items) == 1 and "New job assigned" in provider_items[0]["message"]
    assert len(customer_items) == 1 and "provider was assigned" in customer_items[0]["message"]

    login(client, customer["email"])
    assert client.get("/notifications").status_code == 200
    assert client.post(f"/notifications/{provider_items[0]['_id']}/read").status_code == 404
    assert client.post(f"/notifications/{customer_items[0]['_id']}/read").status_code == 302
    assert notification_model.unread_count(customer["_id"]) == 0

    bs.provider_action(booking["_id"], User(provider), "accept")
    assert notification_model.unread_count(customer["_id"]) == 1