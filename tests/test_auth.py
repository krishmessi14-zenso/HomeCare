from conftest import PW, login, make_user
from models import user as user_model


def test_register_and_duplicate_email(client, ctx):
    data = {"name": "Asha Kumar", "email": "Asha@Example.com", "phone": "9876543210", "password": PW, "confirm_password": PW}
    r = client.post("/register", data=data)
    assert r.status_code == 302
    doc = user_model.find_by_email("asha@example.com")  # normalised
    assert doc and doc["role"] == "customer"
    r2 = client.post("/register", data={**data, "email": "asha@example.com"})
    assert r2.status_code == 400 and b"already exists" in r2.data


def test_register_cannot_choose_role(client, ctx):
    client.post("/register", data={"name": "Evil User", "email": "evil@example.com", "phone": "9876543210", "password": PW,
                                   "confirm_password": PW, "role": "admin"})
    assert user_model.find_by_email("evil@example.com")["role"] == "customer"


def test_register_validation(client, ctx):
    r = client.post("/register", data={"name": "A", "email": "bad", "phone": "x", "password": "short", "confirm_password": "no"})
    assert r.status_code == 400
    assert user_model.find_by_email("bad") is None


def test_password_is_hashed(client, ctx):
    u = make_user("customer", "hash@example.com")
    stored = user_model.find_by_email("hash@example.com")
    assert stored["password_hash"] != PW and PW not in stored["password_hash"]
    assert user_model.verify_password(stored, PW) and not user_model.verify_password(stored, "wrong")


def test_login_correct_and_incorrect(client, ctx):
    make_user("customer", "ok@example.com")
    assert login(client, "ok@example.com", "WrongPass1").status_code == 401
    assert login(client, "nobody@example.com").status_code == 401
    r = login(client, "OK@example.com")
    assert r.status_code == 302 and r.headers["Location"].endswith("/customer/dashboard")


def test_roles_redirect_to_own_dashboards(client, ctx, app):
    for role, path in (("provider", "/provider/dashboard"), ("admin", "/admin/dashboard")):
        make_user(role, f"{role}@example.com")
        c = app.test_client()
        assert login(c, f"{role}@example.com").headers["Location"].endswith(path)


def test_inactive_user_cannot_login(client, ctx):
    make_user("customer", "off@example.com", active=False)
    assert login(client, "off@example.com").status_code == 403


def test_unauthorized_dashboard_access_redirects_to_login(client, ctx):
    for path in ("/customer/dashboard", "/provider/dashboard", "/admin/dashboard", "/admin/bookings"):
        r = client.get(path)
        assert r.status_code == 302 and "/login" in r.headers["Location"]


def test_open_redirect_blocked(client, ctx):
    make_user("customer", "redir@example.com")
    for evil in ("https://evil.example.com", "//evil.example.com", "/\\evil.com", "javascript:alert(1)"):
        c = client.application.test_client()
        r = c.post("/login", data={"email": "redir@example.com", "password": PW, "next": evil})
        assert r.headers["Location"].endswith("/customer/dashboard"), evil
    c = client.application.test_client()
    r = c.post("/login", data={"email": "redir@example.com", "password": PW, "next": "/services"})
    assert r.headers["Location"].endswith("/services")


def test_login_rate_limit(client, ctx):
    make_user("customer", "rate@example.com")
    for _ in range(5):
        assert login(client, "rate@example.com", "BadPass123").status_code == 401
    assert login(client, "rate@example.com", PW).status_code == 429  # even the right password is blocked


def test_logout_requires_post(client, ctx):
    make_user("customer", "lo@example.com")
    login(client, "lo@example.com")
    assert client.get("/logout").status_code == 405
    assert client.post("/logout").status_code == 302
    assert client.get("/customer/dashboard").status_code == 302


def test_csrf_enforced_when_enabled():
    import mongomock
    from app import create_app
    app = create_app({"TESTING": True, "SECRET_KEY": "x" * 32, "WTF_CSRF_ENABLED": True, "MONGO_DB": mongomock.MongoClient().db})
    r = app.test_client().post("/login", data={"email": "a@b.com", "password": "x"})
    assert r.status_code == 400
