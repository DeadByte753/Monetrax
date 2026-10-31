import csv
import io
from datetime import date, timedelta
from decimal import Decimal

from flask import Blueprint, flash, render_template, request
from flask_login import current_user, login_required
from sqlalchemy import select

from extensions import db
from models import EXPENSE, INCOME, Transaction
import finance
from transactions import csv_response, csv_safe, php
from utils import add_months, month_range, parse_date, today

analytics_bp = Blueprint("analytics", __name__, url_prefix="/analytics")

TOP_CATEGORIES = 5

RANGES = [
    ("month", "This month"),
    ("last_month", "Last month"),
    ("3m", "Last 3 months"),
    ("6m", "Last 6 months"),
    ("year", "This year"),
    ("custom", "Custom"),
]


def _resolve_range(key, ref):
    if key == "last_month":
        return month_range(add_months(ref.replace(day=1), -1))
    if key == "3m":
        return add_months(ref.replace(day=1), -2), ref
    if key == "6m":
        return add_months(ref.replace(day=1), -5), ref
    if key == "year":
        return ref.replace(month=1, day=1), ref
    if key == "custom":
        start, end = parse_date(request.args.get("start")), parse_date(request.args.get("end"))
        if start and end and start <= end and (end - start).days <= 3660:
            return start, end
        return None
    return month_range(ref)


@analytics_bp.route("/")
@login_required
def index():
    ref = today()
    uid = current_user.id
    key = request.args.get("range", "month")
    if key not in dict(RANGES):
        key = "month"
    resolved = _resolve_range(key, ref)
    range_error = None
    if resolved is None:
        range_error = "Pick a valid start and end date (start before end)."
        key = "month"
        resolved = _resolve_range("month", ref)
    start, end = resolved
    days = (end - start).days + 1

    t = finance.totals(uid, start, end)
    exp_cats = finance.category_totals(uid, EXPENSE, start, end)
    inc_cats = finance.category_totals(uid, INCOME, start, end)
    savings_rate = float(t["balance"] / t["income"] * 100) if t["income"] else None
    avg_daily = (t["expense"] / Decimal(days)).quantize(Decimal("0.01")) if days else Decimal("0")

    p_end = start - timedelta(days=1)
    p_start = p_end - timedelta(days=days - 1)
    prev = finance.totals(uid, p_start, p_end)

    def change(cur, old):
        return float((cur - old) / old * 100) if old else None

    months_span = (end.year - start.year) * 12 + end.month - start.month + 1
    if months_span >= 2:
        flow = finance.monthly_series(uid, months_span, end)
        flow_label = "Monthly"
    else:
        inc = finance.weekly_series(uid, start, end, INCOME)
        exp = finance.weekly_series(uid, start, end, EXPENSE)
        flow = {"labels": inc["labels"], "income": inc["values"], "expense": exp["values"]}
        flow_label = "Weekly"
    trend = finance.daily_series(uid, start, end) if days <= 92 else finance.weekly_series(uid, start, end)

    biggest = db.session.scalars(
        select(Transaction).where(Transaction.user_id == uid, Transaction.type == EXPENSE,
                                  Transaction.date >= start, Transaction.date <= end)
        .order_by(Transaction.amount.desc()).limit(5)
    ).all()

    wallets = finance.wallet_balances(uid, ref)
    top = exp_cats[:TOP_CATEGORIES]
    savings_months = max(months_span, 6)
    savings = finance.savings_progress(uid, savings_months, end)

    charts = {
        "flow": flow,
        "trend": trend,
        "categories": {"labels": [c["name"] for c in exp_cats], "values": [float(c["total"]) for c in exp_cats],
                       "colors": [c["color"] for c in exp_cats]},
        "topCategories": {"labels": [c["name"] for c in top], "values": [float(c["total"]) for c in top],
                          "colors": [c["color"] for c in top]},
        "wallets": {"labels": [b.wallet.name for b in wallets], "values": [float(b.balance) for b in wallets],
                    "colors": [b.wallet.color for b in wallets]},
        "savings": savings,
    }
    return render_template(
        "analytics/index.html", ranges=RANGES, key=key, start=start, end=end, days=days, t=t, prev=prev,
        income_change=change(t["income"], prev["income"]), expense_change=change(t["expense"], prev["expense"]),
        savings_rate=savings_rate, avg_daily=avg_daily, exp_cats=exp_cats, inc_cats=inc_cats,
        biggest=biggest, charts=charts, flow_label=flow_label, range_error=range_error,
        trend_label="Daily" if days <= 92 else "Weekly", wallets=wallets, top=top,
        wallet_total=sum((b.balance for b in wallets), Decimal("0")),
        wallet_positive=sum((b.balance for b in wallets if b.balance > 0), Decimal("0")),
        savings_months=savings_months,
        savings_net_total=sum((Decimal(str(v)) for v in savings["net"]), Decimal("0")),
        savings_goal_now=Decimal(str(savings["goal_total"][-1])) if savings["goal_total"] else Decimal("0"),
    )


def _month_from_request(ref):
    raw = (request.args.get("month") or "").strip()
    try:
        year, month = (int(p) for p in raw.split("-"))
        picked = date(year, month, 1)
    except (ValueError, TypeError):
        return ref.replace(day=1), bool(raw)
    if picked.year < 2000 or picked > ref.replace(day=1):
        return ref.replace(day=1), True
    return picked, False


@analytics_bp.route("/monthly")
@login_required
def monthly():
    ref = today()
    month_start, bad = _month_from_request(ref)
    if bad:
        flash("Pick a month between January 2000 and this month. Showing this month instead.", "error")
    s = finance.monthly_summary(current_user.id, month_start)
    return render_template("analytics/monthly.html", s=s, month=month_start,
                           prev_month=add_months(month_start, -1),
                           next_month=add_months(month_start, 1) if month_start < ref.replace(day=1) else None,
                           max_month=ref.strftime("%Y-%m"))


@analytics_bp.route("/monthly.csv")
@login_required
def monthly_csv():
    month_start, _ = _month_from_request(today())
    s = finance.monthly_summary(current_user.id, month_start)
    t = s["totals"]
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow([f"Monetrax monthly summary — {month_start.strftime('%B %Y')}"])
    w.writerow(["Period", f"{s['start'].isoformat()} to {s['end'].isoformat()}"])
    w.writerow([])
    w.writerow(["Summary", "Amount (PHP)"])
    w.writerow(["Total income", php(t["income"])])
    w.writerow(["Total expenses", php(t["expense"])])
    w.writerow(["Net savings (income − expenses)", php(s["net"], signed=True)])
    w.writerow(["Savings rate", f"{s['savings_rate']:.1f}%" if s["savings_rate"] is not None else "—"])
    w.writerow(["Added to savings goals this month", php(s["goal_contributions"])])
    w.writerow(["Total in savings goals (today)", php(s["goal_total"])])
    w.writerow(["Transactions", t["count"]])
    for title, rows in (("Expenses by category", s["expense_categories"]),
                        ("Income by category", s["income_categories"])):
        w.writerow([])
        w.writerow([title, "Amount (PHP)", "Share", "Transactions"])
        for row in rows:
            w.writerow([csv_safe(row["name"]), php(row["total"]), f"{row['share']:.1f}%", row["count"]])
        if not rows:
            w.writerow(["None recorded", php(0), "0.0%", 0])
    return csv_response(buf.getvalue(), f"monetrax-summary-{month_start.strftime('%Y-%m')}.csv")
