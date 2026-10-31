from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from extensions import db
from models import SavingsContribution, SavingsGoal
from models import GOAL_ICONS
from models import utcnow
import alerts, finance
from utils import format_money, get_owned_or_404, today
from validators import validate_contribution, validate_goal

savings_bp = Blueprint("savings", __name__, url_prefix="/savings")


@savings_bp.route("/")
@login_required
def index():
    ref = today()
    goals = finance.goals_for(current_user.id)
    active = [g for g in goals if not g.is_complete]
    done = [g for g in goals if g.is_complete]
    total_saved = finance.total_savings(current_user.id)
    total_target = sum((g.target_amount for g in active), 0)
    paces = {g.id: finance.goal_pace(g, ref) for g in active}
    return render_template("savings/index.html", active=active, done=done, paces=paces,
                           total_saved=total_saved, total_target=total_target,
                           contrib_errors={}, open_goal=None)


def _sync_completion(goal):
    goal.completed_at = goal.completed_at or utcnow() if goal.is_complete else None


@savings_bp.route("/new", methods=["GET", "POST"])
@savings_bp.route("/<int:goal_id>/edit", methods=["GET", "POST"])
@login_required
def form(goal_id=None):
    goal = get_owned_or_404(SavingsGoal, goal_id) if goal_id else None
    if goal:
        values = {"name": goal.name, "target_amount": f"{goal.target_amount:.2f}",
                  "target_date": goal.target_date.isoformat() if goal.target_date else "", "icon": goal.icon,
                  "initial_amount": ""}
    else:
        values = {"name": "", "target_amount": "", "target_date": "", "icon": "target", "initial_amount": ""}
    errors = {}
    if request.method == "POST":
        data, errors = validate_goal(request.form, today())
        values = data["raw"]
        clean = data["clean"]
        if clean["icon"] not in GOAL_ICONS:
            clean["icon"] = "target"
        if not errors:
            created = goal is None
            if created:
                goal = SavingsGoal(user_id=current_user.id)
                db.session.add(goal)
            goal.name = clean["name"]
            goal.target_amount = clean["target_amount"]
            goal.target_date = clean["target_date"]
            goal.icon = clean["icon"]
            if created and clean["initial_amount"]:
                db.session.flush()
                goal.contributions.append(SavingsContribution(amount=clean["initial_amount"], date=today(),
                                                              note="Starting amount"))
            db.session.flush()
            _sync_completion(goal)
            alerts.check_goal(current_user, goal, today())
            db.session.commit()
            flash(f"Goal “{goal.name}” {'created' if created else 'updated'}.", "success")
            return redirect(url_for("savings.index"))
    return render_template("savings/form.html", values=values, errors=errors, goal=goal,
                           icons=GOAL_ICONS), (400 if errors else 200)


@savings_bp.route("/<int:goal_id>/contribute", methods=["POST"])
@login_required
def contribute(goal_id):
    goal = get_owned_or_404(SavingsGoal, goal_id)
    data, errors = validate_contribution(request.form, today())
    clean = data["clean"]
    if not errors and clean["amount"] < 0 and -clean["amount"] > goal.saved_amount:
        errors["amount"] = f"You can withdraw at most {format_money(goal.saved_amount)}."
    if errors:
        flash(next(iter(errors.values())), "error")
        return redirect(url_for("savings.index", goal=goal.id) + f"#goal-{goal.id}")
    goal.contributions.append(SavingsContribution(amount=clean["amount"], date=clean["date"], note=clean["note"]))
    db.session.flush()
    _sync_completion(goal)
    alerts.check_goal(current_user, goal, today())
    db.session.commit()
    verb = "Added" if clean["amount"] > 0 else "Withdrew"
    flash(f"{verb} {format_money(abs(clean['amount']))} {'to' if clean['amount'] > 0 else 'from'} {goal.name}.", "success")
    return redirect(url_for("savings.index") + f"#goal-{goal.id}")


@savings_bp.route("/contributions/<int:cid>/delete", methods=["POST"])
@login_required
def delete_contribution(cid):
    c = get_owned_or_404(SavingsContribution, cid)
    goal = c.goal
    db.session.delete(c)
    db.session.flush()
    db.session.refresh(goal)
    _sync_completion(goal)
    db.session.commit()
    flash("Entry removed.", "success")
    return redirect(url_for("savings.index") + f"#goal-{goal.id}")


@savings_bp.route("/<int:goal_id>/delete", methods=["POST"])
@login_required
def delete(goal_id):
    goal = get_owned_or_404(SavingsGoal, goal_id)
    name = goal.name
    db.session.delete(goal)
    db.session.commit()
    flash(f"Goal “{name}” deleted.", "success")
    return redirect(url_for("savings.index"))
