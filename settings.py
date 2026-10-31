from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required, logout_user
from sqlalchemy import delete, func, select, update

from extensions import db
from models import (THEMES, Budget, Category, Notification, RecurringRule, SavingsContribution, SavingsGoal,
                      Transaction, User, Wallet, WalletTransfer)
from models import CUSTOM_COLORS
from security import is_safe_redirect
from utils import CURRENCIES, get_owned_or_404
from validators import (email_error, full_name_error, is_school_email, normalize_email,
                          normalize_name, password_error, validate_category)

settings_bp = Blueprint("settings", __name__, url_prefix="/settings")

YEAR_LEVELS = ["1st year", "2nd year", "3rd year", "4th year", "5th year", "Graduate"]


def _categories_with_usage():
    rows = db.session.execute(
        select(Category, func.count(Transaction.id))
        .outerjoin(Transaction, Transaction.category_id == Category.id)
        .where(Category.user_id == current_user.id)
        .group_by(Category.id).order_by(Category.type.desc(), Category.name)
    ).all()
    return rows


def _render(errors=None, values=None, section="profile", status=200):
    return render_template("settings/index.html", errors=errors or {}, values=values or {}, section=section,
                           categories=_categories_with_usage(), year_levels=YEAR_LEVELS,
                           colors=CUSTOM_COLORS), status


@settings_bp.route("/")
@login_required
def index():
    return _render(section=request.args.get("section", "profile"))


@settings_bp.route("/profile", methods=["POST"])
@login_required
def profile():
    f = request.form
    values = {
        "full_name": normalize_name(f.get("full_name")),
        "email": normalize_email(f.get("email")),
        "school": " ".join((f.get("school") or "").split())[:120],
        "program": " ".join((f.get("program") or "").split())[:120],
        "year_level": f.get("year_level") if f.get("year_level") in YEAR_LEVELS else "",
    }
    errors = {}
    if msg := full_name_error(values["full_name"]):
        errors["full_name"] = msg
    if msg := email_error(values["email"]):
        errors["email"] = msg
    elif current_app.config["REQUIRE_SCHOOL_EMAIL"] and not is_school_email(values["email"]):
        errors["email"] = "Use your school email (it usually ends in .edu or .edu.ph)."
    elif values["email"] != current_user.email.lower():
        other = User.get_by_email(values["email"])
        if other and other.id != current_user.id:
            errors["email"] = "Another account already uses this email."
    if errors:
        return _render(errors, values, "profile", 400)
    current_user.full_name = values["full_name"]
    current_user.email = values["email"]
    current_user.school = values["school"] or None
    current_user.program = values["program"] or None
    current_user.year_level = values["year_level"] or None
    db.session.commit()
    flash("Profile updated.", "success")
    return redirect(url_for("settings.index", section="profile"))


@settings_bp.route("/preferences", methods=["POST"])
@login_required
def preferences():
    currency = request.form.get("currency")
    if currency in CURRENCIES:
        current_user.currency = currency
    if request.form.get("theme") in THEMES:
        current_user.theme = request.form.get("theme")
    current_user.budget_alerts = request.form.get("budget_alerts") == "on"
    current_user.savings_alerts = request.form.get("savings_alerts") == "on"
    db.session.commit()
    flash("Preferences saved.", "success")
    return redirect(url_for("settings.index", section="preferences"))


@settings_bp.route("/theme", methods=["POST"])
@login_required
def theme():
    choice = request.form.get("theme")
    if choice in THEMES:
        current_user.theme = choice
        db.session.commit()
    if request.headers.get("X-Requested-With") == "fetch":
        return ("", 204) if choice in THEMES else ("Unknown theme", 400)
    return redirect(request.referrer if is_safe_redirect(request.referrer) else url_for("settings.index"))


@settings_bp.route("/password", methods=["POST"])
@login_required
def password():
    current = request.form.get("current_password", "")
    new = request.form.get("new_password", "")
    confirm = request.form.get("confirm_password", "")
    errors = {}
    if not current_user.check_password(current):
        errors["current_password"] = "Your current password is incorrect."
    if msg := password_error(new):
        errors["new_password"] = msg
    elif new == current:
        errors["new_password"] = "Choose a password different from your current one."
    if not confirm:
        errors["confirm_password"] = "Re-enter your new password."
    elif confirm != new:
        errors["confirm_password"] = "Passwords don't match."
    if errors:
        return _render(errors, {}, "security", 400)
    current_user.set_password(new)
    db.session.commit()
    flash("Password changed.", "success")
    return redirect(url_for("settings.index", section="security"))


@settings_bp.route("/categories", methods=["POST"])
@login_required
def add_category():
    raw, errors = validate_category(request.form)
    if not errors:
        exists = db.session.scalar(select(Category.id).where(
            Category.user_id == current_user.id, Category.type == raw["type"],
            func.lower(Category.name) == raw["name"].lower()))
        if exists:
            errors["name"] = f"You already have an {raw['type']} category called {raw['name']}."
    if errors:
        return _render(errors, {"cat_" + k: v for k, v in raw.items()}, "categories", 400)
    count = db.session.scalar(select(func.count(Category.id)).where(Category.user_id == current_user.id)) or 0
    color = raw["color"] or CUSTOM_COLORS[count % len(CUSTOM_COLORS)]
    db.session.add(Category(user_id=current_user.id, name=raw["name"], type=raw["type"],
                            icon="tag", color=color, is_default=False))
    db.session.commit()
    flash(f"Category “{raw['name']}” added.", "success")
    return redirect(url_for("settings.index", section="categories"))


@settings_bp.route("/categories/<int:cat_id>/delete", methods=["POST"])
@login_required
def delete_category(cat_id):
    cat = get_owned_or_404(Category, cat_id)
    used = db.session.scalar(select(func.count(Transaction.id)).where(Transaction.category_id == cat.id))
    rules = db.session.scalar(select(func.count(RecurringRule.id)).where(RecurringRule.category_id == cat.id))
    if cat.is_default:
        flash("Default categories can't be deleted.", "error")
    elif rules:
        flash(f"“{cat.name}” is used by a recurring transaction. Change or delete that first.", "error")
    elif used:
        flash(f"“{cat.name}” is used by {used} transaction{'s' if used != 1 else ''}. "
              "Move or delete those first.", "error")
    else:
        db.session.delete(cat)
        db.session.commit()
        flash(f"Category “{cat.name}” deleted.", "success")
    return redirect(url_for("settings.index", section="categories"))


@settings_bp.route("/reset-data", methods=["POST"])
@login_required
def reset_data():
    errors = {}
    if not current_user.check_password(request.form.get("reset_password", "")):
        errors["reset_password"] = "Your password is incorrect."
    if request.form.get("reset_confirm", "").strip().upper() != "RESET":
        errors["reset_confirm"] = "Type RESET to confirm."
    if errors:
        return _render(errors, {}, "danger", 400)

    uid = current_user.id
    try:
        goal_ids = select(SavingsGoal.id).where(SavingsGoal.user_id == uid)
        db.session.execute(delete(SavingsContribution).where(SavingsContribution.goal_id.in_(goal_ids)))
        # Transactions go before recurring rules because they reference them.
        for model in (Transaction, WalletTransfer, RecurringRule, Budget, SavingsGoal, Notification):
            db.session.execute(delete(model).where(model.user_id == uid))
        db.session.execute(update(Wallet).where(Wallet.user_id == uid).values(opening_balance=0))
        db.session.commit()
    except Exception:
        db.session.rollback()
        current_app.logger.exception("Resetting financial data failed for user %s", uid)
        flash("Couldn't reset your data. Nothing was changed. Please try again.", "error")
        return redirect(url_for("settings.index", section="danger"))
    flash("Your financial data was reset. Your account, wallets and categories are kept.", "success")
    return redirect(url_for("dashboard.index"))


@settings_bp.route("/delete-account", methods=["POST"])
@login_required
def delete_account():
    errors = {}
    if not current_user.check_password(request.form.get("password", "")):
        errors["delete_password"] = "Your password is incorrect."
    if request.form.get("confirm", "").strip().upper() != "DELETE":
        errors["delete_confirm"] = "Type DELETE to confirm."
    if errors:
        return _render(errors, {}, "danger", 400)

    uid = current_user.id
    goal_ids = select(SavingsGoal.id).where(SavingsGoal.user_id == uid)
    db.session.execute(delete(SavingsContribution).where(SavingsContribution.goal_id.in_(goal_ids)))
    for model in (SavingsGoal, Notification, Budget, Transaction, WalletTransfer, RecurringRule, Wallet, Category):
        db.session.execute(delete(model).where(model.user_id == uid))
    db.session.execute(delete(User).where(User.id == uid))
    db.session.commit()
    logout_user()
    flash("Your account and all its data were deleted.", "info")
    return redirect(url_for("auth.login"))
