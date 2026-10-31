from datetime import timedelta
from decimal import Decimal

from flask import flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import select

from extensions import db
from models import FREQUENCIES, INCOME, RecurringRule
import alerts, schedule
from transactions import _user_categories, _user_wallets, transactions_bp
from utils import get_owned_or_404, today
from validators import validate_recurring

UPCOMING_DAYS = 30
UPCOMING_LIMIT = 12


@transactions_bp.route("/recurring")
@login_required
def recurring_index():
    rules = db.session.scalars(
        select(RecurringRule).where(RecurringRule.user_id == current_user.id)
        .order_by(RecurringRule.active.desc(), RecurringRule.type.desc(), RecurringRule.name)
    ).all()
    rows = []
    for r in rules:
        ended = schedule.has_ended(r)
        rows.append({"rule": r, "next": schedule.next_date(r), "ended": ended,
                     "status": "ended" if ended else ("active" if r.active else "paused")})
    running = [x for x in rows if x["status"] == "active"]
    monthly_in = sum((schedule.monthly_estimate(x["rule"]) for x in running if x["rule"].is_income), Decimal("0"))
    monthly_out = sum((schedule.monthly_estimate(x["rule"]) for x in running if not x["rule"].is_income), Decimal("0"))
    ref = today()
    upcoming = schedule.upcoming(current_user.id, ref - timedelta(days=1), ref + timedelta(days=UPCOMING_DAYS + 1),
                                 limit_per_rule=40)
    return render_template("transactions/recurring.html", rows=rows, monthly_in=monthly_in, monthly_out=monthly_out,
                           upcoming=upcoming[:UPCOMING_LIMIT], upcoming_total=len(upcoming),
                           upcoming_days=UPCOMING_DAYS)


def _form(rule=None):
    ref = today()
    cats, cats_by_id = _user_categories()
    wallets, wallets_by_id = _user_wallets(include_id=rule.wallet_id if rule else None)
    if rule:
        nxt = schedule.next_date(rule) or ref
        values = {"type": rule.type, "name": rule.name, "amount": f"{rule.amount:.2f}", "category_id": str(rule.category_id),
                  "wallet_id": str(rule.wallet_id or ""), "description": rule.description or "",
                  "frequency": rule.frequency, "date": nxt.isoformat(),
                  "end_date": rule.end_date.isoformat() if rule.end_date else ""}
    else:
        tx_type = request.args.get("type") if request.args.get("type") in ("income", "expense") else "income"
        values = {"type": tx_type, "name": "Allowance" if tx_type == INCOME else "", "amount": "", "category_id": "",
                  "wallet_id": str(wallets[0].id) if wallets else "", "description": "",
                  "frequency": "weekly" if tx_type == INCOME else "monthly", "date": ref.isoformat(), "end_date": ""}
    errors = {}
    if request.method == "POST":
        data, errors = validate_recurring(request.form, cats_by_id, wallets_by_id, ref, FREQUENCIES)
        values = data["raw"]
        if rule is not None and "date" not in errors and data["clean"]["date"] < ref:
            # Editing restarts the schedule from this date; a past date would re-add entries already posted.
            errors["date"] = "The next date can't be in the past. Entries already added stay as they are."
        if not errors:
            c = data["clean"]
            if rule is None:
                rule = schedule.create_rule(current_user, c, c["date"])
                verb = "added"
            else:
                rule.name, rule.amount, rule.type = c["name"], c["amount"], c["type"]
                rule.category_id, rule.wallet_id = c["category"].id, c["wallet"].id
                rule.description, rule.frequency, rule.end_date = c["description"], c["frequency"], c["end_date"]
                rule.start_date, rule.posted_count = c["date"], 0
                verb = "updated"
            posted = schedule.post_due(current_user, ref)
            db.session.commit()
            if posted:
                alerts.refresh_budget_alerts(current_user, ref)
                db.session.commit()
            nxt = schedule.next_date(rule)
            msg = f"“{rule.name}” {verb}."
            if posted:
                msg += f" {len(posted)} entr{'y' if len(posted) == 1 else 'ies'} added up to today."
            if nxt:
                msg += f" Next on {nxt.strftime('%b %d')}."
            flash(msg, "success")
            return redirect(url_for("transactions.recurring_index"))
    return render_template("transactions/recurring_form.html", values=values, errors=errors, rule=rule,
                           categories=cats, wallets=wallets, frequencies=FREQUENCIES), (400 if errors else 200)


@transactions_bp.route("/recurring/new", methods=["GET", "POST"])
@login_required
def recurring_new():
    return _form()


@transactions_bp.route("/recurring/<int:rule_id>/edit", methods=["GET", "POST"])
@login_required
def recurring_edit(rule_id):
    return _form(get_owned_or_404(RecurringRule, rule_id))


@transactions_bp.route("/recurring/<int:rule_id>/toggle", methods=["POST"])
@login_required
def recurring_toggle(rule_id):
    rule = get_owned_or_404(RecurringRule, rule_id)
    ref = today()
    if rule.active:
        rule.active = False
        flash(f"“{rule.name}” paused. Nothing new will be added until you resume it.", "success")
    else:
        rule.active = True
        while True:
            d = schedule.occurrence_date(rule, rule.posted_count)
            if d > ref or (rule.end_date and d > rule.end_date):
                break
            rule.posted_count += 1
        nxt = schedule.next_date(rule)
        flash(f"“{rule.name}” resumed." + (f" Next on {nxt.strftime('%b %d')}." if nxt else ""), "success")
    db.session.commit()
    return redirect(url_for("transactions.recurring_index"))


@transactions_bp.route("/recurring/<int:rule_id>/skip", methods=["POST"])
@login_required
def recurring_skip(rule_id):
    rule = get_owned_or_404(RecurringRule, rule_id)
    nxt = schedule.next_date(rule)
    if nxt:
        rule.posted_count += 1
        db.session.commit()
        after = schedule.next_date(rule)
        flash(f"Skipped {nxt.strftime('%b %d')}." + (f" Next on {after.strftime('%b %d')}." if after else ""), "success")
    return redirect(url_for("transactions.recurring_index"))


@transactions_bp.route("/recurring/<int:rule_id>/delete", methods=["POST"])
@login_required
def recurring_delete(rule_id):
    rule = get_owned_or_404(RecurringRule, rule_id)
    name = rule.name
    db.session.delete(rule)
    db.session.commit()
    flash(f"“{name}” won't repeat anymore. Entries it already added are still in your transactions.", "success")
    return redirect(url_for("transactions.recurring_index"))
