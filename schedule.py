from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import Iterator, List, Optional, Tuple

from flask import url_for
from sqlalchemy import select

from extensions import db
from models import INCOME, RecurringRule, Transaction, User, Wallet
from utils import add_months, format_money

MAX_CATCH_UP = 400

PER_MONTH = {"daily": Decimal("30.44"), "weekly": Decimal("4.345"), "biweekly": Decimal("2.1725"),
             "monthly": Decimal("1"), "yearly": Decimal("1") / Decimal("12")}


def occurrence_date(rule: RecurringRule, n: int) -> date:
    start = rule.start_date
    if rule.frequency == "daily":
        return start + timedelta(days=n)
    if rule.frequency == "weekly":
        return start + timedelta(weeks=n)
    if rule.frequency == "biweekly":
        return start + timedelta(weeks=2 * n)
    if rule.frequency == "yearly":
        return add_months(start, 12 * n)
    return add_months(start, n)


def next_date(rule: RecurringRule) -> Optional[date]:
    if not rule.active:
        return None
    d = occurrence_date(rule, rule.posted_count)
    if rule.end_date and d > rule.end_date:
        return None
    return d


def has_ended(rule: RecurringRule) -> bool:
    return bool(rule.end_date) and occurrence_date(rule, rule.posted_count) > rule.end_date


def monthly_estimate(rule: RecurringRule) -> Decimal:
    return (rule.amount * PER_MONTH.get(rule.frequency, Decimal("1"))).quantize(Decimal("0.01"))


def active_rules(user_id: int) -> List[RecurringRule]:
    return list(db.session.scalars(
        select(RecurringRule).where(RecurringRule.user_id == user_id, RecurringRule.active.is_(True))
    ))


def upcoming(user_id: int, after: date, before: date, tx_type: Optional[str] = None,
             limit_per_rule: int = 60) -> List[Tuple[RecurringRule, date]]:
    out = []
    for rule in active_rules(user_id):
        if tx_type and rule.type != tx_type:
            continue
        n = rule.posted_count
        for _ in range(limit_per_rule):
            d = occurrence_date(rule, n)
            if d >= before or (rule.end_date and d > rule.end_date):
                break
            if d > after:
                out.append((rule, d))
            n += 1
    out.sort(key=lambda x: (x[1], x[0].type != INCOME, x[0].name))
    return out


def next_income(user_id: int, after: date) -> Optional[Tuple[RecurringRule, date]]:
    items = upcoming(user_id, after, after + timedelta(days=62), INCOME, limit_per_rule=70)
    return items[0] if items else None


def _default_wallet_id(user_id: int) -> Optional[int]:
    return db.session.scalar(
        select(Wallet.id).where(Wallet.user_id == user_id, Wallet.archived.is_(False))
        .order_by(Wallet.position, Wallet.id).limit(1)
    )


def post_due(user: User, ref: date) -> List[Transaction]:
    created: List[Transaction] = []
    fallback_wallet = None
    for rule in active_rules(user.id):
        posted_this_rule = []
        already = set(db.session.scalars(
            select(Transaction.date).where(Transaction.recurring_id == rule.id, Transaction.date <= ref)))
        for _ in range(MAX_CATCH_UP):
            d = occurrence_date(rule, rule.posted_count)
            if d > ref or (rule.end_date and d > rule.end_date):
                break
            if d in already:
                # Already posted for this date (e.g. the schedule was edited): count it, don't duplicate.
                rule.posted_count += 1
                continue
            wallet_id = rule.wallet_id
            if wallet_id is None:
                fallback_wallet = fallback_wallet or _default_wallet_id(user.id)
                wallet_id = fallback_wallet
            tx = Transaction(user_id=user.id, name=rule.name, amount=rule.amount, type=rule.type,
                             category_id=rule.category_id, wallet_id=wallet_id, date=d,
                             description=rule.description, recurring_id=rule.id)
            db.session.add(tx)
            rule.posted_count += 1
            posted_this_rule.append(tx)
        if posted_this_rule and rule.is_income:
            _notify_income(user, rule, posted_this_rule)
        created.extend(posted_this_rule)
    if created:
        db.session.flush()
    return created


def _notify_income(user: User, rule: RecurringRule, posted: List[Transaction]) -> None:
    import alerts

    last = posted[-1]
    wallet = db.session.get(Wallet, last.wallet_id) if last.wallet_id else None
    where = f" to {wallet.name}" if wallet else ""
    count = len(posted)
    message = (f"{format_money(rule.amount, user.currency)} was added{where} on {last.date.strftime('%b %d')}."
               if count == 1 else
               f"{count} entries were added{where}, the latest on {last.date.strftime('%b %d')}.")
    alerts.notify(user, f"recurring:{rule.id}:{last.date.isoformat()}", kind="system", level="success",
                  title=f"{rule.name} received", message=message, link=url_for("transactions.index"))


def create_rule(user: User, clean: dict, start: date) -> RecurringRule:
    rule = RecurringRule(user_id=user.id, name=clean["name"], amount=clean["amount"], type=clean["type"],
                         category_id=clean["category"].id, wallet_id=clean["wallet"].id if clean.get("wallet") else None,
                         description=clean.get("description"), frequency=clean["frequency"], start_date=start,
                         end_date=clean.get("end_date"), posted_count=0, active=True)
    db.session.add(rule)
    db.session.flush()
    return rule


def occurrences_until(rule: RecurringRule, ref: date) -> int:
    count = 0
    for _ in range(MAX_CATCH_UP):
        d = occurrence_date(rule, count)
        if d > ref or (rule.end_date and d > rule.end_date):
            break
        count += 1
    return count


def iter_schedule(rule: RecurringRule, count: int) -> Iterator[date]:
    n = rule.posted_count
    for _ in range(count):
        d = occurrence_date(rule, n)
        if rule.end_date and d > rule.end_date:
            return
        yield d
        n += 1
