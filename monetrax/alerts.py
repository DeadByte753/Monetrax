from __future__ import annotations

from datetime import date
from typing import Optional

from flask import url_for
from sqlalchemy import select

from extensions import db
from models import Notification, SavingsGoal, User
from utils import format_money
import finance

THRESHOLDS = [(100, "over"), (90, "warning"), (75, "caution")]


def notify(user: User, key: str, *, kind: str, level: str, title: str, message: str,
           link: Optional[str] = None) -> Optional[Notification]:
    exists = db.session.scalar(select(Notification.id).where(Notification.user_id == user.id, Notification.key == key))
    if exists:
        return None
    n = Notification(user_id=user.id, key=key, kind=kind, level=level, title=title, message=message, link=link)
    db.session.add(n)
    return n


def check_budget(user: User, status: finance.BudgetStatus) -> Optional[Notification]:
    if not user.budget_alerts:
        return None
    pct = status.percent
    reached = next((t for t, _ in THRESHOLDS if (pct > t if t == 100 else pct >= t)), None)
    if reached is None:
        return None
    b = status.budget
    cat = b.category.name
    period = b.period
    key = f"budget:{b.id}:{status.start.isoformat()}:{reached}"
    spent = format_money(status.spent, user.currency)
    limit = format_money(b.limit_amount, user.currency)
    link = url_for("budgets.index")
    if reached == 100:
        over = format_money(-status.remaining, user.currency)
        return notify(user, key, kind="budget", level="danger",
                      title=f"{cat} budget exceeded",
                      message=f"Alert: You have exceeded your {period} {cat} budget by {over} ({spent} of {limit}).",
                      link=link)
    left = format_money(status.remaining, user.currency)
    return notify(user, key, kind="budget", level="warning" if reached == 90 else "info",
                  title=f"{cat} budget at {pct:.0f}%",
                  message=f"Warning: You have used {pct:.0f}% of your {period} {cat} budget. "
                          f"Only {left} left ({spent} of {limit}).",
                  link=link)


def refresh_budget_alerts(user: User, ref: date) -> None:
    for status in finance.budgets_with_status(user.id, ref):
        check_budget(user, status)


def check_goal(user: User, goal: SavingsGoal, ref: date) -> None:
    if not user.savings_alerts:
        return
    link = url_for("savings.index")
    pct = goal.percent
    if goal.is_complete:
        notify(user, f"goal:{goal.id}:complete", kind="savings", level="success",
               title=f"Goal reached: {goal.name}",
               message=f"You saved {format_money(goal.target_amount, user.currency)} for {goal.name}. Well done!",
               link=link)
        return
    if pct >= 50:
        notify(user, f"goal:{goal.id}:half", kind="savings", level="success",
               title=f"Halfway to {goal.name}",
               message=f"You're {pct:.0f}% of the way there. {format_money(goal.remaining_amount, user.currency)} to go.",
               link=link)
    if goal.target_date:
        days_left = (goal.target_date - ref).days
        if 0 <= days_left <= 7:
            notify(user, f"goal:{goal.id}:due:{goal.target_date.isoformat()}", kind="savings", level="warning",
                   title=f"{goal.name} is due soon",
                   message=f"{days_left} day{'s' if days_left != 1 else ''} left and "
                           f"{format_money(goal.remaining_amount, user.currency)} still to save.",
                   link=link)
        elif days_left < 0:
            notify(user, f"goal:{goal.id}:overdue:{goal.target_date.isoformat()}", kind="savings", level="danger",
                   title=f"{goal.name} passed its target date",
                   message="Update the target date or keep saving — "
                           f"{format_money(goal.remaining_amount, user.currency)} left.",
                   link=link)


def refresh_goal_alerts(user: User, ref: date) -> None:
    for goal in finance.goals_for(user.id):
        check_goal(user, goal, ref)


def refresh_all(user: User, ref: date) -> None:
    refresh_budget_alerts(user, ref)
    refresh_goal_alerts(user, ref)
    db.session.commit()


def unread_count(user_id: int) -> int:
    from sqlalchemy import func
    return db.session.scalar(select(func.count(Notification.id)).where(
        Notification.user_id == user_id, Notification.is_read.is_(False),
        Notification.dismissed.is_(False))) or 0
