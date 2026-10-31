import os
from datetime import timedelta

BASE_DIR = os.path.abspath(os.path.dirname(__file__))


def _env_flag(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _database_url() -> str:
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        return "sqlite:///" + os.path.join(BASE_DIR, "instance", "monetrax.sqlite3")
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    if url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://"):]
    return url


class Config:
    # Without an env key, create_app() loads (or creates once) instance/secret_key, so sessions survive
    # restarts and every worker signs cookies with the same key.
    SECRET_KEY = os.environ.get("SECRET_KEY") or os.environ.get("MONETRAX_SECRET_KEY") or None

    # Reject oversized request bodies (no route accepts uploads; forms are a few KB).
    MAX_CONTENT_LENGTH = 1024 * 1024
    # Number of reverse proxies in front of the app (Render: 1). Used to read the real client IP for
    # sign-in lockouts and HTTPS detection. Leave 0 when the app is reached directly.
    TRUST_PROXY = int(os.environ.get("TRUST_PROXY", "0") or 0)

    SQLALCHEMY_DATABASE_URI = _database_url()
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True}

    APP_TIMEZONE = os.environ.get("APP_TIMEZONE", "Asia/Manila")

    REQUIRE_SCHOOL_EMAIL = _env_flag("MONETRAX_REQUIRE_SCHOOL_EMAIL", True)

    CSRF_ENABLED = True
    TRANSACTIONS_PER_PAGE = 20

    _secure = _env_flag("SECURE_COOKIES", False)
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = _secure
    REMEMBER_COOKIE_DURATION = timedelta(days=14)
    REMEMBER_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_SAMESITE = "Lax"
    REMEMBER_COOKIE_SECURE = _secure


class TestConfig(Config):
    TESTING = True
    SECRET_KEY = "test-secret"
    CSRF_ENABLED = False
    REQUIRE_SCHOOL_EMAIL = True
    SQLALCHEMY_DATABASE_URI = "sqlite://"
    APP_TIMEZONE = "UTC"
