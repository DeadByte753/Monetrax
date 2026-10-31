from flask import Blueprint, render_template
from flask_login import current_user, login_required
from sqlalchemy import select

from extensions import db
from models import EXPENSE, Transaction
import alerts, finance, insights
from utils import today

dashboard_bp = Blueprint("dashboard", __name__)


@dashboard_bp.route("/dashboard")
@login_required
def index():
    ref = today()
    uid = current_user.id
    alerts.refresh_all(current_user, ref)

    ov = finance.overview(uid, ref)
    recent = db.session.scalars(
        select(Transaction).where(Transaction.user_id == uid)
        .order_by(Transaction.date.desc(), Transaction.id.desc()).limit(6)
    ).all()
    budgets = finance.budgets_with_status(uid, ref)
    goals = finance.goals_for(uid)
    goals = sorted(goals, key=lambda g: (g.is_complete, -g.percent))[:4]
    cats = finance.category_totals(uid, EXPENSE, ov["month_start"], ov["month_end"])

    charts = {
        "incomeExpense": finance.monthly_series(uid, 6, ref),
        "trend": finance.daily_series(uid, ov["month_start"], ref),
        "categories": {
            "labels": [c["name"] for c in cats],
            "values": [float(c["total"]) for c in cats],
            "colors": [c["color"] for c in cats],
        },
    }

    safe = finance.safe_to_spend(uid, ref)
    wallets = finance.wallet_balances(uid, ref)
    hour_greeting = "Good day"
    return render_template(
        "dashboard/index.html",
        greeting=hour_greeting, ov=ov, recent=recent, budgets=budgets[:5], budget_count=len(budgets),
        goals=goals, categories=cats[:5], charts=charts,
        insights=insights.generate(current_user, ref), safe=safe, wallets=wallets,
    )
