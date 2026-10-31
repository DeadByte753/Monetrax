"""Brute-force protection for sign-in and password checks.

Counters live in the database (table ``auth_throttle``) so every gunicorn worker sees the same numbers and
restarts don't reset an attack. A key that reaches its limit inside the window is locked for ``LOCK``.
"""
from __future__ import annotations

import math
from datetime import timedelta

from flask import request
from sqlalchemy import delete

from extensions import db
from models import AuthThrottle, utcnow

WINDOW = timedelta(minutes=15)
LOCK = timedelta(minutes=15)

# (limit, window) per key kind.
LIMITS = {
    "email": (5, WINDOW),       # wrong passwords for one account email, from anywhere
    "ip": (30, WINDOW),         # wrong passwords from one address, across all emails
    "user": (5, WINDOW),        # wrong "current password" on settings forms while signed in
    "register": (10, timedelta(hours=1)),  # new accounts from one address
}


def client_ip() -> str:
    return request.remote_addr or "unknown"


def key(kind: str, value) -> str:
    return f"{kind}:{str(value).strip().lower()[:280]}"


def retry_after(*keys: str) -> int:
    """Seconds until every given key is unlocked (0 when none is locked)."""
    now = utcnow()
    wait = 0.0
    for k in keys:
        row = db.session.get(AuthThrottle, k)
        if row and row.locked_until and row.locked_until > now:
            wait = max(wait, (row.locked_until - now).total_seconds())
    return math.ceil(wait)


def record_failure(*keys: str) -> None:
    now = utcnow()
    for k in keys:
        limit, window = LIMITS[k.split(":", 1)[0]]
        row = db.session.get(AuthThrottle, k)
        if row is None:
            row = AuthThrottle(key=k, failures=0, window_start=now)
            db.session.add(row)
        if row.window_start is None or now - row.window_start > window:
            row.failures, row.window_start = 0, now
        row.failures += 1
        if row.failures >= limit:
            row.locked_until = now + LOCK
            row.failures, row.window_start = 0, now
    db.session.commit()


def clear(*keys: str) -> None:
    db.session.execute(delete(AuthThrottle).where(AuthThrottle.key.in_(keys)))
    db.session.commit()


def prune() -> None:
    """Drop rows that can no longer lock anyone, so the table stays small."""
    cutoff = utcnow() - max(w for _, w in LIMITS.values()) - LOCK
    db.session.execute(delete(AuthThrottle).where(
        AuthThrottle.window_start < cutoff,
        (AuthThrottle.locked_until.is_(None)) | (AuthThrottle.locked_until < utcnow())))
    db.session.commit()


def wait_message(seconds: int) -> str:
    minutes = max(1, math.ceil(seconds / 60))
    return f"Too many attempts. Please wait {minutes} minute{'s' if minutes != 1 else ''} and try again."
