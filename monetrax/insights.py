from __future__ import annotations

import calendar
from datetime import date
from decimal import Decimal
from typing import List

from models import EXPENSE, User
from utils import add_months, format_money, month_range
import finance


def _ins(level, icon, title, text):
    return {"level": level, "icon": icon, "title": title, "text": text}


def generate(user: User, ref: date, limit: int = 5) -> List[dict]:
    cur = user.currency
    m_start, m_end = month_range(ref)
    month = finance.totals(user.id, m_start, m_end)
    out: List[dict] = []

    if finance.totals(user.id)["count"] == 0:
        return [_ins("info", "sparkles", "Start with your allowance",
                     "Add your allowance as income, then log a few expenses. Insights appear as your data grows.")]

    for s in finance.budgets_with_status(user.id, ref):
        name = s.budget.category.name
        if s.level == "over":
            out.append(_ins("danger", "octagon-alert", f"Over your {name} budget",
                            f"You've spent {format_money(s.spent, cur)} against a {format_money(s.budget.limit_amount, cur)} "
                            f"{s.budget.period} limit — {format_money(-s.remaining, cur)} over."))
        elif s.level in ("warning", "caution"):
            out.append(_ins("warning", "triangle-alert", f"{name} budget at {s.percent:.0f}%",
                            f"{format_money(s.remaining, cur)} left until {s.end.strftime('%b %d')}. "
                            "Slow down spending here to stay on track."))

    cats = finance.category_totals(user.id, EXPENSE, m_start, m_end)
    if cats:
        top = cats[0]
        out.append(_ins("info", "chart-pie", f"{top['name']} is your top expense",
                        f"{format_money(top['total'], cur)} this month — {top['share']:.0f}% of everything you spent."))

    day = ref.day
    prev_start = add_months(m_start, -1)
    prev_end = prev_start.replace(day=min(day, calendar.monthrange(prev_start.year, prev_start.month)[1]))
    prev = finance.totals(user.id, prev_start, prev_end)["expense"]
    now = finance.totals(user.id, m_start, ref)["expense"]
    if prev > 0 and now > 0:
        change = float((now - prev) / prev * 100)
        if change >= 10:
            out.append(_ins("warning", "trending-up", f"Spending up {change:.0f}%",
                            f"You've spent {format_money(now, cur)} so far this month, vs {format_money(prev, cur)} "
                            f"by this day last month."))
        elif change <= -10:
            out.append(_ins("success", "trending-down", f"Spending down {abs(change):.0f}%",
                            f"{format_money(now, cur)} so far vs {format_money(prev, cur)} by this day last month. Nice work."))

    days_in_month = calendar.monthrange(ref.year, ref.month)[1]
    if now > 0 and day >= 5:
        projected = (now / Decimal(day) * Decimal(days_in_month)).quantize(Decimal("1"))
        if month["income"] > 0 and projected > month["income"]:
            out.append(_ins("warning", "gauge", "On pace to overspend",
                            f"At about {format_money(now / Decimal(day), cur)} a day you'd spend {format_money(projected, cur)} "
                            f"this month — more than the {format_money(month['income'], cur)} you've received."))

    if month["income"] > 0:
        rate = float((month["income"] - month["expense"]) / month["income"] * 100)
        if rate >= 20:
            out.append(_ins("success", "piggy-bank", f"You're keeping {rate:.0f}% of your income",
                            "A 20% savings rate or better is a strong habit. Consider moving some into a savings goal."))
        elif rate < 0:
            out.append(_ins("danger", "wallet", "Spending more than you received",
                            f"Expenses are {format_money(month['expense'] - month['income'], cur)} above this month's income."))
    elif month["expense"] > 0:
        out.append(_ins("info", "wallet", "No income logged this month",
                        "Record your allowance or other income so your balance and savings rate stay accurate."))

    for goal in finance.goals_for(user.id, include_complete=False):
        pace = finance.goal_pace(goal, ref)
        if pace and not pace["overdue"] and pace["days_left"] <= 60:
            out.append(_ins("info", "target", f"Keep {goal.name} on schedule",
                            f"Save about {format_money(pace['per_week'], cur)} a week to reach it by "
                            f"{goal.target_date.strftime('%b %d')}."))
            break

    return out[:limit]
