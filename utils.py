from __future__ import annotations

import calendar
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Optional, Tuple
from zoneinfo import ZoneInfo

from flask import abort, current_app
from flask_login import current_user

from extensions import db

CURRENCIES = {
    "PHP": ("₱", "Philippine Peso"),
    "USD": ("$", "US Dollar"),
    "EUR": ("€", "Euro"),
    "GBP": ("£", "British Pound"),
    "JPY": ("¥", "Japanese Yen"),
    "SGD": ("S$", "Singapore Dollar"),
    "INR": ("₹", "Indian Rupee"),
}

CENT = Decimal("0.01")
MAX_AMOUNT = Decimal("10000000")


def today() -> date:
    tz = ZoneInfo(current_app.config.get("APP_TIMEZONE", "UTC"))
    return datetime.now(tz).date()


def to_local(dt: datetime) -> datetime:
    tz = ZoneInfo(current_app.config.get("APP_TIMEZONE", "UTC"))
    return dt.replace(tzinfo=ZoneInfo("UTC")).astimezone(tz)


def month_range(d: date) -> Tuple[date, date]:
    last = calendar.monthrange(d.year, d.month)[1]
    return d.replace(day=1), d.replace(day=last)


def week_range(d: date) -> Tuple[date, date]:
    start = d - timedelta(days=d.weekday())
    return start, start + timedelta(days=6)


def add_months(d: date, months: int) -> date:
    m = d.month - 1 + months
    y = d.year + m // 12
    m = m % 12 + 1
    return date(y, m, min(d.day, calendar.monthrange(y, m)[1]))


def parse_date(value) -> Optional[date]:
    try:
        return date.fromisoformat((value or "").strip())
    except ValueError:
        return None


def parse_amount(value) -> Optional[Decimal]:
    raw = (value or "").replace(",", "").replace(" ", "").strip()
    if not raw:
        return None
    try:
        amount = Decimal(raw)
    except InvalidOperation:
        return None
    if not amount.is_finite():
        return None
    return amount.quantize(CENT, rounding=ROUND_HALF_UP)


def currency_symbol(code: Optional[str] = None) -> str:
    if code is None:
        code = getattr(current_user, "currency", "PHP") if current_user and current_user.is_authenticated else "PHP"
    return CURRENCIES.get(code, ("₱", ""))[0]


def format_money(value, code: Optional[str] = None, signed: bool = False, decimals: bool = True) -> str:
    amount = Decimal(value or 0)
    sign = ""
    if amount < 0:
        sign = "−"
    elif signed and amount > 0:
        sign = "+"
    fmt = "{:,.2f}" if decimals else "{:,.0f}"
    return f"{sign}{currency_symbol(code)}{fmt.format(abs(amount))}"


def compact_money(value, code: Optional[str] = None) -> str:
    amount = Decimal(value or 0)
    sym = currency_symbol(code)
    a = abs(amount)
    sign = "−" if amount < 0 else ""
    if a >= 1_000_000:
        return f"{sign}{sym}{a / 1_000_000:.1f}M"
    if a >= 10_000:
        return f"{sign}{sym}{a / 1000:.1f}k"
    return f"{sign}{sym}{a:,.0f}"


def get_owned_or_404(model, obj_id: int):
    obj = db.session.get(model, obj_id)
    if obj is None:
        abort(404)
    owner_id = getattr(obj, "user_id", None)
    if owner_id is None and hasattr(obj, "goal"):
        owner_id = obj.goal.user_id
    if owner_id != current_user.id:
        abort(404)
    return obj
