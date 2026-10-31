import hmac
import secrets
from urllib.parse import urlparse

from flask import Flask, current_app, flash, g, redirect, request, session

_CSRF_KEY = "_csrf_token"


def get_csrf_token() -> str:
    token = session.get(_CSRF_KEY)
    if not token:
        token = secrets.token_urlsafe(32)
        session[_CSRF_KEY] = token
    return token


def csp_nonce() -> str:
    """One random nonce per response; only inline <script> tags carrying it may run."""
    if "csp_nonce" not in g:
        g.csp_nonce = secrets.token_urlsafe(18)
    return g.csp_nonce


# Third-party hosts the templates load from: Tailwind's CDN build, Chart.js, Google Fonts.
_SCRIPT_HOSTS = "https://cdn.tailwindcss.com https://cdn.jsdelivr.net"


def content_security_policy() -> str:
    return "; ".join([
        "default-src 'self'",
        f"script-src 'self' 'nonce-{csp_nonce()}' {_SCRIPT_HOSTS}",
        # Tailwind's CDN build injects a <style> tag at runtime, and templates use style="" for colours.
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
        "font-src 'self' https://fonts.gstatic.com data:",
        "img-src 'self' data: blob:",
        "connect-src 'self'",
        "object-src 'none'",
        "base-uri 'self'",
        "form-action 'self'",
        "frame-ancestors 'none'",
    ])


def is_safe_redirect(target) -> bool:
    if not target or not isinstance(target, str):
        return False
    parsed = urlparse(target)
    return (not parsed.scheme and not parsed.netloc
            and target.startswith("/") and not target.startswith("//") and "\\" not in target)


def init_security(app: Flask) -> None:
    app.jinja_env.globals["csrf_token"] = get_csrf_token
    app.jinja_env.globals["csp_nonce"] = csp_nonce

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
        response.headers.setdefault("Permissions-Policy",
                                    "camera=(), microphone=(), geolocation=(), payment=(), usb=()")
        response.headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
        if response.mimetype == "text/html":
            response.headers.setdefault("Content-Security-Policy", content_security_policy())
        if current_app.config.get("SESSION_COOKIE_SECURE"):
            # Only sent when the site runs on HTTPS (SECURE_COOKIES=true); browsers then refuse plain HTTP.
            response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        if request.endpoint and request.endpoint != "static":
            response.headers.setdefault("Cache-Control", "no-store")
        return response
