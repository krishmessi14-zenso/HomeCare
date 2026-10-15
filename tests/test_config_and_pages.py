import mongomock
import pytest

from conftest import login, make_booking, make_service, make_user
from config import ConfigError, load_config


def test_missing_env_vars_give_clear_error(monkeypatch):
    monkeypatch.delenv("MONGO_URI", raising=False)
    monkeypatch.delenv("SECRET_KEY", raising=False)
    monkeypatch.setattr("config.load_dotenv", lambda *a, **k: None, raising=False)
    with pytest.raises(ConfigError) as e:
        load_config()
    assert "MONGO_URI" in str(e.value) and "SECRET_KEY" in str(e.value)


def test_placeholder_secret_rejected(monkeypatch):
    monkeypatch.setenv("MONGO_URI", "mongodb://127.0.0.1:27017/")
    monkeypatch.setenv("SECRET_KEY", "replace_with_a_secure_random_secret")
    with pytest.raises(ConfigError):
        load_config()


def test_valid_config_loads(monkeypatch):
    monkeypatch.setenv("MONGO_URI", "mongodb://127.0.0.1:27017/")
    monkeypatch.setenv("SECRET_KEY", "a" * 40)
    assert load_config()["SESSION_COOKIE_HTTPONLY"] is True


def test_customer_pages_render(client, ctx):
    s, c = make_service(), make_user("customer", "c@example.com")
    b = make_booking(c, s)
    login(client, "c@example.com")
    r = client.get("/customer/dashboard")
    assert r.status_code == 200 and b"Unpaid" in r.data and b"Cancel" in r.data
    assert client.get(f"/customer/book/{s['_id']}").status_code == 200
    assert client.get(f"/customer/bookings/{b['_id']}/review").status_code == 302  # not completed yet


def test_provider_pages_render(client, ctx):
    make_user("provider", "p@example.com")
    login(client, "p@example.com")
    for path in ("/provider/dashboard", "/provider/dashboard?tab=history", "/provider/reviews"):
        assert client.get(path).status_code == 200


def test_security_headers_and_no_debug_leak(client, ctx):
    r = client.get("/")
    assert r.headers["X-Frame-Options"] == "DENY" and "Content-Security-Policy" in r.headers
    assert b"Traceback" not in client.get("/services/" + "f" * 24).data
