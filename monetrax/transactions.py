import csv
import io
import math
from decimal import Decimal

from flask import (Blueprint, Response, current_app, flash, redirect, render_template,
                   request, url_for)
from flask_login import current_user, login_required
from sqlalchemy import func, or_, select

from extensions import db
from models import FREQUENCIES, Category, Transaction, Wallet
from security import is_safe_redirect
import alerts, finance, schedule
from utils import format_money, get_owned_or_404, parse_date, today
from validators import validate_recurring, validate_transaction

transactions_bp = Blueprint("transactions", __name__, url_prefix="/transactions")

SORTS = {
    "date_desc": (Transaction.date.desc(), Transaction.id.desc()),
    "date_asc": (Transaction.date.asc(), Transaction.id.asc()),
    "amount_desc": (Transaction.amount.desc(), Transaction.date.desc()),
    "amount_asc": (Transaction.amount.asc(), Transaction.date.desc()),
}


def _user_categories():
    cats = db.session.scalars(
        select(Category).where(Category.user_id == current_user.id).order_by(Category.type, Category.name)
    ).all()
    return cats, {c.id: c for c in cats}


def _user_wallets(include_id=None):
    wallets = finance.wallets_for(current_user.id, include_archived=True)
    shown = [w for w in wallets if not w.archived or w.id == include_id]
    return shown, {w.id: w for w in shown}


def _last_used_wallet_id():
    return db.session.scalar(
        select(Transaction.wallet_id).join(Wallet, Wallet.id == Transaction.wallet_id)
        .where(Transaction.user_id == current_user.id, Wallet.archived.is_(False))
        .order_by(Transaction.created_at.desc(), Transaction.id.desc()).limit(1))


def _filters_from_request():
    args = request.args
    f = {
        "q": (args.get("q") or "").strip()[:100],
        "type": args.get("type") if args.get("type") in ("income", "expense") else "",
        "category": args.get("category", type=int),
        "wallet": args.get("wallet", type=int),
        "start": parse_date(args.get("start")),
        "end": parse_date(args.get("end")),
        "sort": args.get("sort") if args.get("sort") in SORTS else "date_desc",
    }
    return f


def _filtered_query(f):
    stmt = select(Transaction).where(Transaction.user_id == current_user.id)
    if f["q"]:
        like = f"%{f['q'].lower()}%"
        stmt = stmt.where(or_(func.lower(Transaction.name).like(like),
                              func.lower(func.coalesce(Transaction.description, "")).like(like)))
    if f["type"]:
        stmt = stmt.where(Transaction.type == f["type"])
    if f["category"]:
        stmt = stmt.where(Transaction.category_id == f["category"])
    if f["wallet"]:
        stmt = stmt.where(Transaction.wallet_id == f["wallet"])
    if f["start"]:
        stmt = stmt.where(Transaction.date >= f["start"])
    if f["end"]:
        stmt = stmt.where(Transaction.date <= f["end"])
    return stmt


@transactions_bp.route("/")
@login_required
def index():
    f = _filters_from_request()
    cats, _ = _user_categories()
    base = _filtered_query(f)

    total_count = db.session.scalar(select(func.count()).select_from(base.subquery()))
    per_page = current_app.config["TRANSACTIONS_PER_PAGE"]
    pages = max(1, math.ceil(total_count / per_page))
    page = min(max(request.args.get("page", 1, type=int), 1), pages)
    rows = db.session.scalars(base.order_by(*SORTS[f["sort"]]).limit(per_page).offset((page - 1) * per_page)).all()

    sub = base.subquery()
    income = db.session.scalar(select(func.sum(sub.c.amount)).where(sub.c.type == "income")) or 0
    expense = db.session.scalar(select(func.sum(sub.c.amount)).where(sub.c.type == "expense")) or 0

    args = {k: v for k, v in request.args.items() if k != "page" and v}
    filtered = any(f[k] for k in ("q", "type", "category", "wallet", "start", "end"))
    rule_count = len(schedule.active_rules(current_user.id))
    return render_template(
        "transactions/index.html", rows=rows, f=f, categories=cats, page=page, pages=pages,
        wallets=finance.wallets_for(current_user.id, include_archived=True), rule_count=rule_count,
        total_count=total_count, args=args, filtered=filtered,
        sums={"income": income, "expense": expense, "net": income - expense},
        overall=finance.totals(current_user.id),
    )


def _save(tx, clean):
    tx.name = clean["name"]
    tx.type = clean["type"]
    tx.category_id = clean["category"].id
    tx.date = clean["date"]
    tx.amount = clean["amount"]
    tx.description = clean["description"]
    tx.wallet_id = clean["wallet"].id


def _back(default_endpoint="transactions.index"):
    nxt = request.form.get("next") or request.args.get("next")
    return redirect(nxt if is_safe_redirect(nxt) else url_for(default_endpoint))


@transactions_bp.route("/new", methods=["GET", "POST"])
@login_required
def create():
    cats, by_id = _user_categories()
    wallets, wallets_by_id = _user_wallets()
    tx_type = request.args.get("type") if request.args.get("type") in ("income", "expense") else "expense"
    default_wallet = _last_used_wallet_id() or (wallets[0].id if wallets else "")
    values = {"type": tx_type, "date": today().isoformat(), "name": "", "amount": "", "category_id": "",
              "description": "", "wallet_id": str(default_wallet), "repeat": request.args.get("repeat", "")}
    source = None
    dup_id = request.args.get("duplicate", type=int)
    if dup_id:
        source = get_owned_or_404(Transaction, dup_id)
        # Copy everything except the date (defaults to today) and the schedule link (a copy is a one-off).
        wallet_ok = source.wallet_id in wallets_by_id
        values.update({"type": source.type, "name": source.name, "amount": f"{source.amount:.2f}",
                       "category_id": str(source.category_id), "description": source.description or "",
                       "wallet_id": str(source.wallet_id if wallet_ok else default_wallet)})
    errors = {}
    if request.method == "POST":
        data, errors = validate_transaction(request.form, by_id, today(), wallets_by_id)
        values = data["raw"]
        repeat = (request.form.get("repeat") or "").strip()
        values["repeat"] = repeat
        if repeat and repeat not in FREQUENCIES:
            errors["repeat"] = "Choose how often it repeats."
        if not errors and repeat:
            clean = dict(data["clean"], frequency=repeat, end_date=None)
            rule = schedule.create_rule(current_user, clean, clean["date"])
            posted = schedule.post_due(current_user, today())
            db.session.commit()
            alerts.refresh_budget_alerts(current_user, today())
            db.session.commit()
            nxt = schedule.next_date(rule)
            label = rule.frequency_label.lower()
            if posted:
                extra = f" {len(posted)} entries added so far." if len(posted) > 1 else ""
                flash(f"“{rule.name}” added and set to repeat {label}.{extra} Next: {nxt.strftime('%b %d')}.", "success")
            else:
                flash(f"“{rule.name}” scheduled {label}, starting {rule.start_date.strftime('%b %d')}.", "success")
            if request.form.get("add_another"):
                return redirect(url_for("transactions.create", type=rule.type))
            return _back()
        if not errors:
            tx = Transaction(user_id=current_user.id)
            _save(tx, data["clean"])
            db.session.add(tx)
            db.session.commit()
            alerts.refresh_budget_alerts(current_user, today())
            db.session.commit()
            kind = "Income" if tx.is_income else "Expense"
            flash(f"{kind} “{tx.name}” added.", "success")
            if request.form.get("add_another"):
                return redirect(url_for("transactions.create", type=tx.type))
            return _back()
    return render_template("transactions/form.html", values=values, errors=errors, categories=cats,
                           wallets=wallets, frequencies=FREQUENCIES, mode="create", source=source,
                           next=request.args.get("next", "")), (400 if errors else 200)


@transactions_bp.route("/<int:tx_id>")
@login_required
def detail(tx_id):
    tx = get_owned_or_404(Transaction, tx_id)
    rule_next = schedule.next_date(tx.rule) if tx.rule else None
    return render_template("transactions/detail.html", tx=tx, rule_next=rule_next)


@transactions_bp.route("/<int:tx_id>/duplicate")
@login_required
def duplicate(tx_id):
    get_owned_or_404(Transaction, tx_id)
    return redirect(url_for("transactions.create", duplicate=tx_id, next=request.args.get("next") or None))


@transactions_bp.route("/<int:tx_id>/edit", methods=["GET", "POST"])
@login_required
def edit(tx_id):
    tx = get_owned_or_404(Transaction, tx_id)
    cats, by_id = _user_categories()
    wallets, wallets_by_id = _user_wallets(include_id=tx.wallet_id)
    values = {"type": tx.type, "date": tx.date.isoformat(), "name": tx.name, "amount": f"{tx.amount:.2f}",
              "category_id": str(tx.category_id), "description": tx.description or "",
              "wallet_id": str(tx.wallet_id or "")}
    errors = {}
    if request.method == "POST":
        data, errors = validate_transaction(request.form, by_id, today(), wallets_by_id)
        values = data["raw"]
        if not errors and tx.recurring_id and data["clean"]["date"] != tx.date:
            clash = db.session.scalar(select(Transaction.id).where(
                Transaction.recurring_id == tx.recurring_id, Transaction.date == data["clean"]["date"],
                Transaction.id != tx.id))
            if clash:
                errors["date"] = "This schedule already has an entry on that date. Pick another date."
        if not errors:
            _save(tx, data["clean"])
            db.session.commit()
            alerts.refresh_budget_alerts(current_user, today())
            db.session.commit()
            flash(f"“{tx.name}” updated.", "success")
            return _back()
    return render_template("transactions/form.html", values=values, errors=errors, categories=cats,
                           wallets=wallets, frequencies=FREQUENCIES, mode="edit", tx=tx,
                           next=request.args.get("next", "")), (400 if errors else 200)


@transactions_bp.route("/<int:tx_id>/delete", methods=["POST"])
@login_required
def delete(tx_id):
    tx = get_owned_or_404(Transaction, tx_id)
    name = tx.name
    db.session.delete(tx)
    db.session.commit()
    flash(f"“{name}” deleted.", "success")
    return _back()


@transactions_bp.route("/export.csv")
@login_required
def export_csv():
    f = _filters_from_request()
    rows = db.session.scalars(_filtered_query(f).order_by(*SORTS[f["sort"]])).all()
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["Date", "Name", "Type", "Category", "Wallet", "Amount (PHP)", "Description"])
    income = expense = Decimal("0")
    for t in rows:
        if t.is_income:
            income += t.amount
        else:
            expense += t.amount
        writer.writerow([t.date.isoformat(), csv_safe(t.name), t.type.title(), csv_safe(t.category.name),
                         csv_safe(t.wallet.name) if t.wallet else "", php(t.signed_amount, signed=True),
                         csv_safe(t.description or "")])
    writer.writerow([])
    writer.writerow(["", "Total income", "", "", "", php(income), ""])
    writer.writerow(["", "Total expenses", "", "", "", php(-expense), ""])
    writer.writerow(["", "Net", "", "", "", php(income - expense, signed=True), ""])
    filename = f"monetrax-transactions-{today().isoformat()}.csv"
    return csv_response(buf.getvalue(), filename)


def php(value, signed=False) -> str:
    """Peso amount for exports. Uses an ASCII minus so spreadsheets read the sign."""
    return format_money(value, "PHP", signed=signed).replace("−", "-")


def csv_safe(text: str) -> str:
    """Stop user text from being run as a spreadsheet formula when the CSV is opened."""
    return "'" + text if text and text[0] in "=+-@\t\r" else text


def csv_response(body: str, filename: str) -> Response:
    # The BOM lets Excel read the file as UTF-8 so ₱ shows correctly.
    return Response("﻿" + body, mimetype="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})
