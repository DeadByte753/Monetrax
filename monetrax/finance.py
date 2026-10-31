from __future__ import annotations

import calendar
from collections import OrderedDict, defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import ROUND_FLOOR, Decimal
from typing import Dict, List, Optional

from sqlalchemy import case, func, select

from extensions import db
from models import (EXPENSE, INCOME, MONTHLY, Budget, Category, SavingsContribution,
                      SavingsGoal, Transaction, Wallet, WalletTransfer)
from utils import add_months, month_range, week_range

ZERO = Decimal("0")


def _d(value) -> Decimal:
    return Decimal(value) if value is not None else ZERO


def totals(user_id: int, start: Optional[date] = None, end: Optional[date] = None) -> Dict[str, Decimal]:
    stmt = select(
        func.sum(case((Transaction.type == INCOME, Transaction.amount), else_=0)),
        func.sum(case((Transaction.type == EXPENSE, Transaction.amount), else_=0)),
        func.count(Transaction.id),
    ).where(Transaction.user_id == user_id)
    if start:
        stmt = stmt.where(Transaction.date >= start)
    if end:
        stmt = stmt.where(Transaction.date <= end)
    income, expense, count = db.session.execute(stmt).one()
    income, expense = _d(income), _d(expense)
    return {"income": income, "expense": expense, "balance": income - expense, "count": count or 0}


def total_savings(user_id: int) -> Decimal:
    stmt = (select(func.sum(SavingsContribution.amount))
            .join(SavingsGoal, SavingsContribution.goal_id == SavingsGoal.id)
            .where(SavingsGoal.user_id == user_id))
    return _d(db.session.scalar(stmt))


def category_totals(user_id: int, tx_type: str, start: Optional[date] = None,
                    end: Optional[date] = None) -> List[dict]:
    stmt = (select(Category, func.sum(Transaction.amount), func.count(Transaction.id))
            .join(Transaction, Transaction.category_id == Category.id)
            .where(Transaction.user_id == user_id, Transaction.type == tx_type)
            .group_by(Category.id)
            .order_by(func.sum(Transaction.amount).desc()))
    if start:
        stmt = stmt.where(Transaction.date >= start)
    if end:
        stmt = stmt.where(Transaction.date <= end)
    rows = db.session.execute(stmt).all()
    grand = sum((_d(r[1]) for r in rows), ZERO)
    return [{
        "category": cat, "name": cat.name, "color": cat.color, "icon": cat.icon,
        "total": _d(total), "count": count,
        "share": float(_d(total) / grand * 100) if grand else 0.0,
    } for cat, total, count in rows]


def spent_in_category(user_id: int, category_id: int, start: date, end: date) -> Decimal:
    stmt = select(func.sum(Transaction.amount)).where(
        Transaction.user_id == user_id, Transaction.type == EXPENSE,
        Transaction.category_id == category_id, Transaction.date >= start, Transaction.date <= end)
    return _d(db.session.scalar(stmt))


def _rows_between(user_id: int, start: date, end: date):
    stmt = select(Transaction.date, Transaction.type, Transaction.amount).where(
        Transaction.user_id == user_id, Transaction.date >= start, Transaction.date <= end)
    return db.session.execute(stmt).all()


def monthly_series(user_id: int, months: int, ref: date) -> dict:
    first = add_months(ref.replace(day=1), -(months - 1))
    _, last = month_range(ref)
    buckets: "OrderedDict[tuple, Dict[str, Decimal]]" = OrderedDict()
    cursor = first
    for _ in range(months):
        buckets[(cursor.year, cursor.month)] = {"income": ZERO, "expense": ZERO}
        cursor = add_months(cursor, 1)
    for d, t, amount in _rows_between(user_id, first, last):
        key = (d.year, d.month)
        if key in buckets:
            buckets[key][t] += _d(amount)
    labels = [f"{calendar.month_abbr[m]} {str(y)[2:]}" if months > 12 or y != ref.year else calendar.month_abbr[m]
              for (y, m) in buckets]
    return {
        "labels": labels,
        "income": [float(v["income"]) for v in buckets.values()],
        "expense": [float(v["expense"]) for v in buckets.values()],
        "net": [float(v["income"] - v["expense"]) for v in buckets.values()],
    }


def daily_series(user_id: int, start: date, end: date, tx_type: str = EXPENSE) -> dict:
    span = (end - start).days + 1
    values: Dict[date, Decimal] = defaultdict(lambda: ZERO)
    for d, t, amount in _rows_between(user_id, start, end):
        if t == tx_type:
            values[d] += _d(amount)
    days = [start + timedelta(days=i) for i in range(span)]
    fmt = "%b %d" if span > 7 else "%a"
    return {"labels": [d.strftime(fmt) for d in days], "values": [float(values[d]) for d in days]}


def weekly_series(user_id: int, start: date, end: date, tx_type: str = EXPENSE) -> dict:
    ws, _ = week_range(start)
    weeks = []
    cursor = ws
    while cursor <= end:
        weeks.append(cursor)
        cursor += timedelta(days=7)
    values = defaultdict(lambda: ZERO)
    for d, t, amount in _rows_between(user_id, start, end):
        if t == tx_type:
            values[week_range(d)[0]] += _d(amount)
    return {"labels": [w.strftime("%b %d") for w in weeks], "values": [float(values[w]) for w in weeks]}


@dataclass
class BudgetStatus:
    budget: Budget
    start: date
    end: date
    spent: Decimal
    remaining: Decimal
    percent: float
    level: str

    @property
    def bar_percent(self) -> float:
        return min(self.percent, 100.0)

    @property
    def period_label(self) -> str:
        if self.budget.period == MONTHLY:
            return self.start.strftime("%B %Y")
        return f"{self.start.strftime('%b %d')} – {self.end.strftime('%b %d')}"


def budget_range(budget: Budget, ref: date):
    return month_range(ref) if budget.period == MONTHLY else week_range(ref)


def level_for(percent: float) -> str:
    if percent > 100:
        return "over"
    if percent >= 90:
        return "warning"
    if percent >= 75:
        return "caution"
    return "ok"


def budget_status(budget: Budget, ref: date) -> BudgetStatus:
    start, end = budget_range(budget, ref)
    spent = spent_in_category(budget.user_id, budget.category_id, start, end)
    limit = _d(budget.limit_amount)
    percent = float(spent / limit * 100) if limit else 0.0
    return BudgetStatus(budget, start, end, spent, limit - spent, round(percent, 1), level_for(percent))


def budgets_with_status(user_id: int, ref: date) -> List[BudgetStatus]:
    budgets = db.session.scalars(
        select(Budget).join(Category).where(Budget.user_id == user_id).order_by(Category.name, Budget.period)
    ).all()
    statuses = [budget_status(b, ref) for b in budgets]
    order = {"over": 0, "warning": 1, "caution": 2, "ok": 3}
    return sorted(statuses, key=lambda s: (order[s.level], -s.percent))


def goals_for(user_id: int, include_complete: bool = True) -> List[SavingsGoal]:
    goals = db.session.scalars(
        select(SavingsGoal).where(SavingsGoal.user_id == user_id).order_by(SavingsGoal.created_at.desc())
    ).all()
    if not include_complete:
        goals = [g for g in goals if not g.is_complete]
    return goals


def goal_pace(goal: SavingsGoal, ref: date) -> Optional[dict]:
    if not goal.target_date or goal.is_complete:
        return None
    days_left = (goal.target_date - ref).days
    if days_left <= 0:
        return {"days_left": days_left, "per_week": goal.remaining_amount, "overdue": True}
    weeks = max(days_left / 7, 1)
    return {"days_left": days_left, "per_week": (goal.remaining_amount / Decimal(str(weeks))).quantize(Decimal("0.01")),
            "overdue": False}


def overview(user_id: int, ref: date) -> dict:
    m_start, m_end = month_range(ref)
    all_time = totals(user_id)
    month = totals(user_id, m_start, m_end)
    prev_start, prev_end = month_range(add_months(m_start, -1))
    prev = totals(user_id, prev_start, prev_end)
    return {
        "all_time": all_time,
        "month": month,
        "prev_month": prev,
        "savings": total_savings(user_id),
        "month_start": m_start,
        "month_end": m_end,
    }


@dataclass
class WalletBalance:
    wallet: Wallet
    balance: Decimal
    month_in: Decimal
    month_out: Decimal

    @property
    def is_negative(self) -> bool:
        return self.balance < 0


def wallets_for(user_id: int, include_archived: bool = False) -> List[Wallet]:
    stmt = select(Wallet).where(Wallet.user_id == user_id)
    if not include_archived:
        stmt = stmt.where(Wallet.archived.is_(False))
    return list(db.session.scalars(stmt.order_by(Wallet.position, Wallet.id)))


def wallet_balances(user_id: int, ref: date, include_archived: bool = False) -> List[WalletBalance]:
    wallets = wallets_for(user_id, include_archived)
    if not wallets:
        return []
    m_start, m_end = month_range(ref)
    tx_rows = db.session.execute(
        select(Transaction.wallet_id, Transaction.type, func.sum(Transaction.amount),
               func.sum(case(((Transaction.date >= m_start) & (Transaction.date <= m_end), Transaction.amount), else_=0)))
        .where(Transaction.user_id == user_id, Transaction.wallet_id.is_not(None))
        .group_by(Transaction.wallet_id, Transaction.type)
    ).all()
    net = defaultdict(lambda: ZERO)
    month_in = defaultdict(lambda: ZERO)
    month_out = defaultdict(lambda: ZERO)
    for wid, ttype, total, this_month in tx_rows:
        if ttype == INCOME:
            net[wid] += _d(total)
            month_in[wid] += _d(this_month)
        else:
            net[wid] -= _d(total)
            month_out[wid] += _d(this_month)
    in_month = case(((WalletTransfer.date >= m_start) & (WalletTransfer.date <= m_end), WalletTransfer.amount), else_=0)
    for wid, total, this_month in db.session.execute(
        select(WalletTransfer.to_wallet_id, func.sum(WalletTransfer.amount), func.sum(in_month))
        .where(WalletTransfer.user_id == user_id).group_by(WalletTransfer.to_wallet_id)
    ).all():
        net[wid] += _d(total)
        month_in[wid] += _d(this_month)
    for wid, total, this_month in db.session.execute(
        select(WalletTransfer.from_wallet_id, func.sum(WalletTransfer.amount), func.sum(in_month))
        .where(WalletTransfer.user_id == user_id).group_by(WalletTransfer.from_wallet_id)
    ).all():
        net[wid] -= _d(total)
        month_out[wid] += _d(this_month)
    return [WalletBalance(w, _d(w.opening_balance) + net[w.id], month_in[w.id], month_out[w.id]) for w in wallets]


def spent_today(user_id: int, ref: date, wallet_ids) -> Decimal:
    if not wallet_ids:
        return ZERO
    return _d(db.session.scalar(select(func.sum(Transaction.amount)).where(
        Transaction.user_id == user_id, Transaction.type == EXPENSE, Transaction.date == ref,
        Transaction.wallet_id.in_(wallet_ids))))


@dataclass
class SafeToSpend:
    daily: Decimal
    left_today: Decimal
    spent_today: Decimal
    days: int
    until: date
    basis: str
    next_income_name: Optional[str]
    next_income_amount: Optional[Decimal]
    spendable_balance: Decimal
    set_aside: Decimal
    bills: list
    has_data: bool

    @property
    def status(self) -> str:
        if self.daily <= 0:
            return "empty"
        if self.left_today < 0:
            return "over"
        if self.spent_today >= self.daily * Decimal("0.8"):
            return "close"
        return "ok"

    @property
    def percent_used(self) -> float:
        if self.daily <= 0:
            return 100.0
        return float(min(self.spent_today / self.daily * 100, Decimal("100")))


def safe_to_spend(user_id: int, ref: date) -> SafeToSpend:
    import schedule

    balances = wallet_balances(user_id, ref)
    spendable = [b for b in balances if b.wallet.spendable]
    spendable_ids = [b.wallet.id for b in spendable]
    balance_now = sum((b.balance for b in spendable), ZERO)
    today_spent = spent_today(user_id, ref, spendable_ids)

    nxt = schedule.next_income(user_id, ref)
    if nxt:
        rule, until = nxt
        basis, inc_name, inc_amount = "income", rule.name, rule.amount
    else:
        until = month_range(ref)[1] + timedelta(days=1)
        basis, inc_name, inc_amount = "month", None, None
    days = max((until - ref).days, 1)

    bills = [(r, d) for r, d in schedule.upcoming(user_id, ref, until, EXPENSE)
             if r.wallet_id is None or r.wallet_id in spendable_ids]
    set_aside = sum((r.amount for r, _ in bills), ZERO)

    pool = balance_now + today_spent - set_aside
    daily = (pool / days).quantize(Decimal("0.01"), rounding=ROUND_FLOOR) if pool > 0 else ZERO
    has_data = bool(balances) and (totals(user_id)["count"] > 0 or any(b.balance for b in balances))
    return SafeToSpend(daily=daily, left_today=daily - today_spent, spent_today=today_spent, days=days,
                       until=until, basis=basis, next_income_name=inc_name, next_income_amount=inc_amount,
                       spendable_balance=balance_now, set_aside=set_aside, bills=bills, has_data=has_data)


def savings_progress(user_id: int, months: int, ref: date) -> dict:
    """Per month: net saved (income − expenses), money put into savings goals that month, and the
    running total held in goals at each month end. All from stored transactions and contributions."""
    flow = monthly_series(user_id, months, ref)
    first = add_months(ref.replace(day=1), -(months - 1))
    _, last = month_range(ref)
    before = _d(db.session.scalar(
        select(func.sum(SavingsContribution.amount)).join(SavingsGoal, SavingsContribution.goal_id == SavingsGoal.id)
        .where(SavingsGoal.user_id == user_id, SavingsContribution.date < first)))
    per_month: Dict[tuple, Decimal] = defaultdict(lambda: ZERO)
    for d, amount in db.session.execute(
        select(SavingsContribution.date, SavingsContribution.amount)
        .join(SavingsGoal, SavingsContribution.goal_id == SavingsGoal.id)
        .where(SavingsGoal.user_id == user_id, SavingsContribution.date >= first, SavingsContribution.date <= last)
    ).all():
        per_month[(d.year, d.month)] += _d(amount)
    contributed, cumulative = [], []
    running = before
    cursor = first
    for _ in range(months):
        added = per_month[(cursor.year, cursor.month)]
        running += added
        contributed.append(float(added))
        cumulative.append(float(running))
        cursor = add_months(cursor, 1)
    return {"labels": flow["labels"], "net": flow["net"], "contributed": contributed, "goal_total": cumulative}


def monthly_summary(user_id: int, month_start: date) -> dict:
    start, end = month_range(month_start)
    t = totals(user_id, start, end)
    contributed = _d(db.session.scalar(
        select(func.sum(SavingsContribution.amount)).join(SavingsGoal, SavingsContribution.goal_id == SavingsGoal.id)
        .where(SavingsGoal.user_id == user_id, SavingsContribution.date >= start, SavingsContribution.date <= end)))
    prev_start, prev_end = month_range(add_months(start, -1))
    return {
        "start": start, "end": end, "totals": t, "prev": totals(user_id, prev_start, prev_end),
        "net": t["balance"],
        "savings_rate": float(t["balance"] / t["income"] * 100) if t["income"] else None,
        "goal_contributions": contributed,
        "goal_total": total_savings(user_id),
        "expense_categories": category_totals(user_id, EXPENSE, start, end),
        "income_categories": category_totals(user_id, INCOME, start, end),
    }
