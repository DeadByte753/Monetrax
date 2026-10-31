from sqlalchemy import select

from extensions import db
from models import Category, User


def test_dashboard_requires_login(client):
    resp = client.get("/dashboard")
    assert resp.status_code == 302 and "/login" in resp.headers["Location"]


def test_auth_pages_render(client):
    for path in ("/login", "/register", "/forgot-password"):
        assert client.get(path).status_code == 200


def test_register_hashes_password_seeds_categories_and_signs_in(app, client, register):
    resp = register()
    assert resp.status_code == 302 and resp.headers["Location"].endswith("/dashboard")
    with app.app_context():
        user = db.session.scalar(select(User).where(User.email == "juan@school.edu.ph"))
        assert user.password_hash != "Budget2026" and user.password_hash.startswith(("scrypt:", "pbkdf2:"))
        names = set(db.session.scalars(select(Category.name).where(Category.user_id == user.id)))
    assert {"Food", "Transportation", "Education", "School Supplies", "Personal Needs", "Entertainment",
            "Others", "Allowance", "Scholarship", "Part-time Income", "Other Income"} <= names
    page = client.get("/dashboard")
    assert page.status_code == 200 and b"Good day, Juan!" in page.data


def test_duplicate_email_rejected(client, register):
    register()
    client.post("/logout")
    resp = register(email="JUAN@school.edu.ph")
    assert resp.status_code == 400 and b"already exists" in resp.data


def test_registration_validation(client, register):
    resp = register(name="", email="not-an-email", password="short", confirm="nope", terms=None)
    assert resp.status_code == 400
    for msg in (b"Enter your full name", b"valid email", b"at least 8", b"match", b"Terms and Conditions to continue"):
        assert msg in resp.data


def test_school_email_required(client, register):
    assert b"school email" in register(email="juan@gmail.com").data


def test_login_logout_flow(client, register):
    register()
    client.post("/logout")
    assert client.get("/dashboard").status_code == 302
    bad = client.post("/login", data={"email": "juan@school.edu.ph", "password": "wrong-pass1"})
    assert bad.status_code == 400 and b"Incorrect email or password" in bad.data
    unknown = client.post("/login", data={"email": "nobody@school.edu.ph", "password": "whatever1"})
    assert b"Incorrect email or password" in unknown.data
    ok = client.post("/login", data={"email": "Juan@School.edu.ph", "password": "Budget2026", "remember": "on"})
    assert ok.status_code == 302 and ok.headers["Location"].endswith("/dashboard")
    assert client.get("/dashboard").status_code == 200
    client.post("/logout")
    assert client.get("/dashboard").status_code == 302


def test_safe_next_redirect(client, register):
    register()
    client.post("/logout")
    ok = client.post("/login?next=/budgets/", data={"email": "juan@school.edu.ph", "password": "Budget2026"})
    assert ok.headers["Location"].endswith("/budgets/")
    client.post("/logout")
    evil = client.post("/login", data={"email": "juan@school.edu.ph", "password": "Budget2026",
                                       "next": "https://evil.example.com"})
    assert "evil" not in evil.headers["Location"]


def test_csrf_blocks_post_without_token():
    from app import create_app
    from config import TestConfig

    class Cfg(TestConfig):
        CSRF_ENABLED = True

    client = create_app(Cfg).test_client()
    resp = client.post("/login", data={"email": "a@b.edu", "password": "x"})
    assert resp.status_code == 302
    page = client.get("/login")
    token = page.data.split(b'name="csrf_token" value="')[1].split(b'"')[0].decode()
    resp = client.post("/login", data={"csrf_token": token, "email": "a@school.edu", "password": "x1234567"})
    assert resp.status_code == 400
