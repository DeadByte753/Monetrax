import logging
import os
import re
import types

from app import _instance_secret_key, create_app
from config import TestConfig
from extensions import db

EMAIL, PASSWORD = "juan@school.edu.ph", "Budget2026"


def _login(client, password=PASSWORD, email=EMAIL, **extra):
    return client.post("/login", data={"email": email, "password": password, **extra})


def test_login_locks_after_repeated_wrong_passwords(client, register):
    register()
    client.post("/logout")
    for _ in range(5):
        assert _login(client, "wrong-pass1").status_code == 400
    # Locked: even the right password is refused without being checked.
    locked = _login(client)
    assert locked.status_code == 429 and b"Too many attempts" in locked.data
    assert locked.headers["Retry-After"]
    assert client.get("/dashboard").status_code == 302


def test_lockout_also_covers_unknown_emails(client):
    for _ in range(5):
        _login(client, "whatever1", email="ghost@school.edu.ph")
    assert _login(client, "whatever1", email="ghost@school.edu.ph").status_code == 429


def test_successful_login_resets_the_counter(client, register):
    register()
    client.post("/logout")
    for _ in range(4):
        _login(client, "wrong-pass1")
    assert _login(client).status_code == 302
    client.post("/logout")
    for _ in range(4):
        _login(client, "wrong-pass1")
    assert _login(client).status_code == 302


def test_lock_expires(app, client, register):
    from datetime import timedelta
    from models import AuthThrottle

    register()
    client.post("/logout")
    for _ in range(5):
        _login(client, "wrong-pass1")
    assert _login(client).status_code == 429
    with app.app_context():
        for row in db.session.query(AuthThrottle).all():
            if row.locked_until:
                row.locked_until -= timedelta(minutes=16)
        db.session.commit()
    assert _login(client).status_code == 302


def test_settings_password_checks_lock_out(user_client):
    for _ in range(5):
        r = user_client.post("/settings/delete-account", data={"password": "wrong-pass1", "confirm": "DELETE"})
        assert b"Your password is incorrect" in r.data
    r = user_client.post("/settings/delete-account", data={"password": PASSWORD, "confirm": "DELETE"})
    assert b"Too many attempts" in r.data
    assert user_client.get("/dashboard").status_code == 200  # account still there


def test_password_change_signs_out_other_devices(app, user_client):
    other = app.test_client()
    assert _login(other, remember="on").status_code == 302
    assert other.get("/dashboard").status_code == 200

    r = user_client.post("/settings/password", data={"current_password": PASSWORD, "new_password": "NewPass2027",
                                                     "confirm_password": "NewPass2027"})
    assert r.status_code == 302
    assert user_client.get("/dashboard").status_code == 200  # this browser stays signed in

    other.delete_cookie("session")  # even falling back to the old "remember me" cookie fails
    assert other.get("/dashboard").status_code == 302


def test_old_style_session_ids_are_rejected(app):
    from models import load_user

    with app.test_request_context():
        assert load_user("1") is None
        assert load_user("1.deadbeef") is None
        assert load_user("abc.def") is None


def test_login_starts_a_fresh_session(client, register):
    register()
    client.post("/logout")
    with client.session_transaction() as s:
        s["planted"] = "x"
    _login(client)
    with client.session_transaction() as s:
        assert "planted" not in s


def test_security_headers_and_csp_nonce(user_client):
    r = user_client.get("/dashboard")
    h = r.headers
    assert h["X-Frame-Options"] == "DENY" and h["X-Content-Type-Options"] == "nosniff"
    csp = h["Content-Security-Policy"]
    assert "frame-ancestors 'none'" in csp and "object-src 'none'" in csp and "'unsafe-inline'" not in csp.split(";")[1]
    nonce = re.search(r"'nonce-([^']+)'", csp).group(1)
    html = r.get_data(as_text=True)
    inline = re.findall(r"<script(?![^>]*\bsrc=)(?![^>]*application/json)([^>]*)>", html)
    assert inline and all(f'nonce="{nonce}"' in attrs for attrs in inline)
    assert user_client.get("/dashboard").headers["Content-Security-Policy"] != csp  # fresh per response
    assert "Strict-Transport-Security" not in h  # only on HTTPS deployments


def test_hsts_when_secure_cookies():
    class Secure(TestConfig):
        SESSION_COOKIE_SECURE = True
    app = create_app(Secure)
    try:
        assert "max-age" in app.test_client().get("/login").headers["Strict-Transport-Security"]
    finally:
        with app.app_context():
            db.drop_all()


def test_oversized_request_rejected(client):
    r = client.post("/login", data={"email": "a@school.edu", "password": "x" * (1024 * 1024 + 10)})
    assert r.status_code == 413


def test_instance_secret_key_is_created_once(tmp_path):
    fake = types.SimpleNamespace(instance_path=str(tmp_path), logger=logging.getLogger("t"))
    first = _instance_secret_key(fake)
    assert len(first) == 64 and _instance_secret_key(fake) == first
    assert os.stat(tmp_path / "secret_key").st_mode & 0o077 == 0
