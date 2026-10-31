from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import select

from extensions import db
from models import Budget, Category
import alerts, finance
from utils import get_owned_or_404, today
from validators import validate_budget

budgets_bp = Blueprint("budgets", __name__, url_prefix="/budgets")


def _expense_categories():
    cats = db.session.scalars(select(Category).where(
        Category.user_id == current_user.id, Category.type == "expense").order_by(Category.name)).all()
    return cats, {c.id: c for c in cats}


def _duplicate(category_id, period, exclude_id=None):
    stmt = select(Budget.id).where(Budget.user_id == current_user.id, Budget.category_id == category_id,
                                   Budget.period == period)
    if exclude_id:
        stmt = stmt.where(Budget.id != exclude_id)
    return db.session.scalar(stmt) is not None


@budgets_bp.route("/")
@login_required
def index():
    ref = today()
    statuses = finance.budgets_with_status(current_user.id, ref)
    summary = {
        "count": len(statuses),
        "limit": sum((s.budget.limit_amount for s in statuses), 0),
        "spent": sum((s.spent for s in statuses), 0),
        "attention": sum(1 for s in statuses if s.level != "ok"),
    }
    return render_template("budgets/index.html", statuses=statuses, summary=summary)


def _form(budget=None):
    cats, by_id = _expense_categories()
    if budget:
        values = {"category_id": str(budget.category_id), "limit_amount": f"{budget.limit_amount:.2f}",
                  "period": budget.period}
    else:
        values = {"category_id": request.args.get("category", ""), "limit_amount": "", "period": "monthly"}
    errors = {}
    if request.method == "POST":
        data, errors = validate_budget(request.form, by_id)
        values = data["raw"]
        clean = data["clean"]
        if not errors and _duplicate(clean["category"].id, clean["period"], budget.id if budget else None):
            errors["category_id"] = f"You already have a {clean['period']} budget for {clean['category'].name}. Edit that one instead."
        if not errors:
            if budget is None:
                budget = Budget(user_id=current_user.id)
                db.session.add(budget)
            budget.category_id = clean["category"].id
            budget.limit_amount = clean["limit_amount"]
            budget.period = clean["period"]
            db.session.commit()
            alerts.refresh_budget_alerts(current_user, today())
            db.session.commit()
            flash(f"{clean['category'].name} budget saved.", "success")
            return redirect(url_for("budgets.index"))
    return render_template("budgets/form.html", values=values, errors=errors, categories=cats,
                           budget=budget), (400 if errors else 200)


@budgets_bp.route("/new", methods=["GET", "POST"])
@login_required
def create():
    return _form()


@budgets_bp.route("/<int:budget_id>/edit", methods=["GET", "POST"])
@login_required
def edit(budget_id):
    return _form(get_owned_or_404(Budget, budget_id))


@budgets_bp.route("/<int:budget_id>/delete", methods=["POST"])
@login_required
def delete(budget_id):
    budget = get_owned_or_404(Budget, budget_id)
    name = budget.category.name
    db.session.delete(budget)
    db.session.commit()
    flash(f"{name} budget deleted.", "success")
    return redirect(url_for("budgets.index"))
