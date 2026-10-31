import hmac
import secrets
from urllib.parse import urlparse

from flask import Flask, current_app, flash, redirect, request, session

_CSRF_KEY = "_csrf_token"


def get_csrf_token() -> str:
    token = session.get(_CSRF_KEY)
    if not token:
        token = secrets.token_urlsafe(32)
        session[_CSRF_KEY] = token
    return token


def is_safe_redirect(target) -> bool:
    if not target or not isinstance(target, str):
        return False
    parsed = urlparse(target)
    return (not parsed.scheme and not parsed.netloc
            and target.startswith("/") and not target.startswith("//") and "\\" not in target)


def init_security(app: Flask) -> None:
    app.jinja_env.globals["csrf_token"] = get_csrf_token

    @app.before_request
    def csrf_protect():
        if not current_app.config.get("CSRF_ENABLED", True):
            return None
        if request.method not in {"POST", "PUT", "PATCH", "DELETE"}:
            return None
        sent = request.form.get("csrf_token") or request.headers.get("X-CSRF-Token", "")
        expected = session.get(_CSRF_KEY, "")
        if not expected or not hmac.compare_digest(expected, sent):
            flash("Your session expired. Please try again.", "error")
            return redirect(request.full_path if request.query_string else request.path)
        return None

    @app.after_request
    def security_headers(response):
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        if request.endpoint and request.endpoint != "static":
            response.headers.setdefault("Cache-Control", "no-store")
        return response
