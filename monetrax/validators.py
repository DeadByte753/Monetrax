from __future__ import annotations

import re
from datetime import date, timedelta
from decimal import Decimal
from typing import Dict, Optional, Tuple

from utils import MAX_AMOUNT, parse_amount, parse_date

EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(\.[A-Za-z0-9\-]+)*\.[A-Za-z]{2,}$")
SCHOOL_DOMAIN_RE = re.compile(r"(^|\.)edu(\.[a-z]{2})?$", re.IGNORECASE)
HEX_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")

PASSWORD_MIN = 8
PASSWORD_MAX = 128
NAME_MAX = 80

Errors = Dict[str, str]


def normalize_email(value) -> str:
    return (value or "").strip().lower()


def normalize_name(value) -> str:
    return " ".join((value or "").split())


def clean_text(value, max_len: int) -> str:
    return " ".join((value or "").split())[:max_len + 1]


def email_error(email: str) -> str:
    if not email:
        return "Enter your email address."
    if len(email) > 254 or not EMAIL_RE.match(email):
        return "Enter a valid email address, like name@school.edu.ph."
    return ""


def is_school_email(email: str) -> bool:
    return bool(SCHOOL_DOMAIN_RE.search(email.rsplit("@", 1)[-1]))


def password_error(password: str) -> str:
    if not password:
        return "Create a password."
    if len(password) < PASSWORD_MIN:
        return f"Use at least {PASSWORD_MIN} characters."
    if len(password) > PASSWORD_MAX:
        return f"Use at most {PASSWORD_MAX} characters."
    if not re.search(r"[A-Za-z]", password) or not re.search(r"\d", password):
        return "Include at least one letter and one number."
    return ""


def full_name_error(full_name: str) -> str:
    if not full_name:
        return "Enter your full name."
    if len(full_name) < 2 or not re.search(r"[A-Za-z]", full_name):
        return "Enter your full name as it appears on your school ID."
    if len(full_name) > NAME_MAX:
        return f"Keep your name under {NAME_MAX} characters."
    return ""


def validate_login(email: str, password: str) -> Errors:
    errors: Errors = {}
    if msg := email_error(email):
        errors["email"] = msg
    if not password:
        errors["password"] = "Enter your password."
    return errors


def validate_registration(full_name, email, password, confirm, accepted_terms, require_school_email) -> Errors:
    errors: Errors = {}
    if msg := full_name_error(full_name):
        errors["full_name"] = msg
    if msg := email_error(email):
        errors["email"] = msg
    elif require_school_email and not is_school_email(email):
        errors["email"] = "Use your school email (it usually ends in .edu or .edu.ph)."
    if msg := password_error(password):
        errors["password"] = msg
    if not confirm:
        errors["confirm_password"] = "Re-enter your password."
    elif confirm != password:
        errors["confirm_password"] = "Passwords don't match."
    if not accepted_terms:
        errors["terms"] = "Please accept the Terms and Conditions to continue."
    return errors


def amount_field(raw, errors: Errors, key: str = "amount", label: str = "an amount",
                 allow_negative: bool = False) -> Optional[Decimal]:
    amount = parse_amount(raw)
    if amount is None:
        errors[key] = f"Enter {label}, like 250 or 1,250.50."
        return None
    if amount == 0 or (amount < 0 and not allow_negative):
        errors[key] = "Enter an amount greater than zero." if not allow_negative else "The amount can't be zero."
        return None
    if abs(amount) > MAX_AMOUNT:
        errors[key] = "That amount is too large."
        return None
    return amount


def validate_transaction(form, categories_by_id, today: date, wallets_by_id=None) -> Tuple[dict, Errors]:
    errors: Errors = {}
    data = {
        "name": clean_text(form.get("name"), 100),
        "type": (form.get("type") or "").strip(),
        "category_id": (form.get("category_id") or "").strip(),
        "date": (form.get("date") or "").strip(),
        "amount": (form.get("amount") or "").strip(),
        "description": (form.get("description") or "").strip(),
        "wallet_id": (form.get("wallet_id") or "").strip(),
    }
    if not data["name"]:
        errors["name"] = "Give this transaction a name."
    elif len(data["name"]) > 100:
        errors["name"] = "Keep the name under 100 characters."

    amount = amount_field(data["amount"], errors)

    if data["type"] not in ("income", "expense"):
        errors["type"] = "Choose Income or Expense."

    category = None
    try:
        category = categories_by_id.get(int(data["category_id"]))
    except ValueError:
        pass
    if category is None:
        errors["category_id"] = "Choose a category."
    elif data["type"] in ("income", "expense") and category.type != data["type"]:
        errors["category_id"] = f"Pick an {data['type']} category."

    tx_date = parse_date(data["date"])
    if tx_date is None:
        errors["date"] = "Choose a valid date."
    elif tx_date > today + timedelta(days=366):
        errors["date"] = "That date is too far in the future."
    elif tx_date.year < 2000:
        errors["date"] = "That date is too far in the past."

    if len(data["description"]) > 500:
        errors["description"] = "Keep the description under 500 characters."

    wallet = None
    if wallets_by_id is not None:
        try:
            wallet = wallets_by_id.get(int(data["wallet_id"]))
        except ValueError:
            pass
        if wallet is None:
            errors["wallet_id"] = ("Choose where the money went." if data["type"] == "income"
                                   else "Choose where the money came from.")

    clean = {"name": data["name"], "type": data["type"], "category": category, "date": tx_date,
             "amount": amount, "description": data["description"] or None, "wallet": wallet}
    return {"raw": data, "clean": clean}, errors


def validate_budget(form, expense_categories_by_id) -> Tuple[dict, Errors]:
    errors: Errors = {}
    raw = {
        "category_id": (form.get("category_id") or "").strip(),
        "limit_amount": (form.get("limit_amount") or "").strip(),
        "period": (form.get("period") or "").strip(),
    }
    category = None
    try:
        category = expense_categories_by_id.get(int(raw["category_id"]))
    except ValueError:
        pass
    if category is None:
        errors["category_id"] = "Choose an expense category."
    limit = amount_field(raw["limit_amount"], errors, key="limit_amount", label="a spending limit")
    if raw["period"] not in ("weekly", "monthly"):
        errors["period"] = "Choose weekly or monthly."
    return {"raw": raw, "clean": {"category": category, "limit_amount": limit, "period": raw["period"]}}, errors


def validate_goal(form, today: date) -> Tuple[dict, Errors]:
    errors: Errors = {}
    raw = {
        "name": clean_text(form.get("name"), 80),
        "target_amount": (form.get("target_amount") or "").strip(),
        "target_date": (form.get("target_date") or "").strip(),
        "icon": (form.get("icon") or "target").strip(),
        "initial_amount": (form.get("initial_amount") or "").strip(),
    }
    if not raw["name"]:
        errors["name"] = "Name your goal, like “New laptop”."
    elif len(raw["name"]) > 80:
        errors["name"] = "Keep the name under 80 characters."
    target = amount_field(raw["target_amount"], errors, key="target_amount", label="a target amount")
    target_date = None
    if raw["target_date"]:
        target_date = parse_date(raw["target_date"])
        if target_date is None:
            errors["target_date"] = "Choose a valid date."
    initial = None
    if raw["initial_amount"]:
        initial = amount_field(raw["initial_amount"], errors, key="initial_amount", label="a starting amount")
    return {"raw": raw, "clean": {"name": raw["name"], "target_amount": target, "target_date": target_date,
                                  "icon": raw["icon"], "initial_amount": initial}}, errors


def validate_contribution(form, today: date) -> Tuple[dict, Errors]:
    errors: Errors = {}
    raw = {
        "amount": (form.get("amount") or "").strip(),
        "direction": (form.get("direction") or "add").strip(),
        "date": (form.get("date") or "").strip(),
        "note": clean_text(form.get("note"), 120),
    }
    amount = amount_field(raw["amount"], errors)
    d = parse_date(raw["date"]) if raw["date"] else today
    if d is None:
        errors["date"] = "Choose a valid date."
    if amount is not None and raw["direction"] == "withdraw":
        amount = -amount
    return {"raw": raw, "clean": {"amount": amount, "date": d, "note": raw["note"] or None}}, errors


def validate_category(form) -> Tuple[dict, Errors]:
    errors: Errors = {}
    raw = {
        "name": clean_text(form.get("name"), 40),
        "type": (form.get("type") or "").strip(),
        "color": (form.get("color") or "").strip(),
    }
    if not raw["name"]:
        errors["name"] = "Name the category."
    elif len(raw["name"]) > 40:
        errors["name"] = "Keep it under 40 characters."
    if raw["type"] not in ("income", "expense"):
        errors["type"] = "Choose income or expense."
    if raw["color"] and not HEX_RE.match(raw["color"]):
        raw["color"] = ""
    return raw, errors


def validate_wallet(form, wallet_types) -> Tuple[dict, Errors]:
    errors: Errors = {}
    raw = {
        "name": clean_text(form.get("name"), 40),
        "type": (form.get("type") or "").strip(),
        "opening_balance": (form.get("opening_balance") or "").strip(),
        "color": (form.get("color") or "").strip(),
        "spendable": form.get("spendable") == "on",
    }
    if not raw["name"]:
        errors["name"] = "Name the wallet, like “GCash” or “BPI Savings”."
    elif len(raw["name"]) > 40:
        errors["name"] = "Keep the name under 40 characters."
    if raw["type"] not in wallet_types:
        errors["type"] = "Choose a wallet type."
    opening = Decimal("0")
    if raw["opening_balance"]:
        parsed = parse_amount(raw["opening_balance"])
        if parsed is None:
            errors["opening_balance"] = "Enter an amount, like 500 or 1,250.50."
        elif parsed < 0:
            errors["opening_balance"] = "The starting balance can't be negative."
        elif parsed > MAX_AMOUNT:
            errors["opening_balance"] = "That amount is too large."
        else:
            opening = parsed
    color = raw["color"] if HEX_RE.match(raw["color"]) else None
    return {"raw": raw, "clean": {"name": raw["name"], "type": raw["type"], "opening_balance": opening,
                                  "color": color, "spendable": raw["spendable"]}}, errors


def validate_transfer(form, wallets_by_id, today: date) -> Tuple[dict, Errors]:
    errors: Errors = {}
    raw = {
        "from_wallet_id": (form.get("from_wallet_id") or "").strip(),
        "to_wallet_id": (form.get("to_wallet_id") or "").strip(),
        "amount": (form.get("amount") or "").strip(),
        "date": (form.get("date") or "").strip(),
        "note": clean_text(form.get("note"), 120),
    }

    def pick(key):
        try:
            return wallets_by_id.get(int(raw[key]))
        except ValueError:
            return None

    src, dst = pick("from_wallet_id"), pick("to_wallet_id")
    if src is None:
        errors["from_wallet_id"] = "Choose the wallet the money leaves."
    if dst is None:
        errors["to_wallet_id"] = "Choose the wallet the money goes to."
    elif src is not None and src.id == dst.id:
        errors["to_wallet_id"] = "Pick a different wallet from the one you're moving money out of."
    amount = amount_field(raw["amount"], errors)
    d = parse_date(raw["date"]) if raw["date"] else today
    if d is None:
        errors["date"] = "Choose a valid date."
    return {"raw": raw, "clean": {"from_wallet": src, "to_wallet": dst, "amount": amount, "date": d,
                                  "note": raw["note"] or None}}, errors


def validate_recurring(form, categories_by_id, wallets_by_id, today: date, frequencies) -> Tuple[dict, Errors]:
    data, errors = validate_transaction(form, categories_by_id, today, wallets_by_id)
    raw = data["raw"]
    raw["frequency"] = (form.get("frequency") or "").strip()
    raw["end_date"] = (form.get("end_date") or "").strip()
    if raw["frequency"] not in frequencies:
        errors["frequency"] = "Choose how often it repeats."
    end = None
    if raw["end_date"]:
        end = parse_date(raw["end_date"])
        if end is None:
            errors["end_date"] = "Choose a valid end date."
        elif data["clean"]["date"] and end < data["clean"]["date"]:
            errors["end_date"] = "The end date must be on or after the first date."
    data["clean"]["frequency"] = raw["frequency"]
    data["clean"]["end_date"] = end
    return data, errors
