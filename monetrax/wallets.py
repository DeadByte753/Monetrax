from decimal import Decimal

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import func, or_, select

from extensions import db
from models import WALLET_TYPES, RecurringRule, Transaction, Wallet, WalletTransfer
import finance
from utils import format_money, get_owned_or_404, today
from validators import validate_transfer, validate_wallet

wallets_bp = Blueprint("wallets", __name__, url_prefix="/wallets")


def _usage(wallet_id: int) -> int:
    tx = db.session.scalar(select(func.count(Transaction.id)).where(Transaction.wallet_id == wallet_id)) or 0
    tr = db.session.scalar(select(func.count(WalletTransfer.id)).where(
        or_(WalletTransfer.from_wallet_id == wallet_id, WalletTransfer.to_wallet_id == wallet_id))) or 0
    rr = db.session.scalar(select(func.count(RecurringRule.id)).where(RecurringRule.wallet_id == wallet_id)) or 0
    return tx + tr + rr


def _name_taken(name: str, exclude_id=None) -> bool:
    stmt = select(Wallet.id).where(Wallet.user_id == current_user.id, func.lower(Wallet.name) == name.lower())
    if exclude_id:
        stmt = stmt.where(Wallet.id != exclude_id)
    return db.session.scalar(stmt) is not None


@wallets_bp.route("/")
@login_required
def index():
    ref = today()
    balances = finance.wallet_balances(current_user.id, ref, include_archived=True)
    active = [b for b in balances if not b.wallet.archived]
    hidden = [b for b in balances if b.wallet.archived]
    transfers = db.session.scalars(
        select(WalletTransfer).where(WalletTransfer.user_id == current_user.id)
        .order_by(WalletTransfer.date.desc(), WalletTransfer.id.desc()).limit(10)
    ).all()
    total = sum((b.balance for b in active), Decimal("0"))
    spendable = sum((b.balance for b in active if b.wallet.spendable), Decimal("0"))
    opening = sum((b.wallet.opening_balance for b in balances), Decimal("0"))
    return render_template("wallets/index.html", active=active, hidden=hidden, transfers=transfers,
                           total=total, spendable=spendable, opening=opening,
                           overall=finance.totals(current_user.id))


@wallets_bp.route("/new", methods=["GET", "POST"])
@wallets_bp.route("/<int:wallet_id>/edit", methods=["GET", "POST"])
@login_required
def form(wallet_id=None):
    wallet = get_owned_or_404(Wallet, wallet_id) if wallet_id else None
    if wallet:
        values = {"name": wallet.name, "type": wallet.type, "opening_balance": f"{wallet.opening_balance:.2f}",
                  "color": wallet.color, "spendable": wallet.spendable}
    else:
        wtype = request.args.get("type") if request.args.get("type") in WALLET_TYPES else "gcash"
        values = {"name": "", "type": wtype, "opening_balance": "", "color": WALLET_TYPES[wtype][2], "spendable": True}
    errors = {}
    if request.method == "POST":
        data, errors = validate_wallet(request.form, WALLET_TYPES)
        values = data["raw"]
        clean = data["clean"]
        if not errors and _name_taken(clean["name"], wallet.id if wallet else None):
            errors["name"] = f"You already have a wallet called {clean['name']}."
        if not errors:
            created = wallet is None
            if created:
                position = db.session.scalar(select(func.count(Wallet.id)).where(Wallet.user_id == current_user.id)) or 0
                wallet = Wallet(user_id=current_user.id, position=position)
                db.session.add(wallet)
            wallet.name = clean["name"]
            wallet.type = clean["type"]
            wallet.opening_balance = clean["opening_balance"]
            wallet.color = clean["color"] or WALLET_TYPES[clean["type"]][2]
            wallet.spendable = clean["spendable"]
            db.session.commit()
            flash(f"Wallet “{wallet.name}” {'added' if created else 'updated'}.", "success")
            return redirect(url_for("wallets.index"))
    return render_template("wallets/form.html", values=values, errors=errors, wallet=wallet,
                           wallet_types=WALLET_TYPES), (400 if errors else 200)


@wallets_bp.route("/<int:wallet_id>/hide", methods=["POST"])
@login_required
def hide(wallet_id):
    wallet = get_owned_or_404(Wallet, wallet_id)
    others = db.session.scalar(select(func.count(Wallet.id)).where(
        Wallet.user_id == current_user.id, Wallet.archived.is_(False), Wallet.id != wallet.id)) or 0
    if not wallet.archived and others == 0:
        flash("Keep at least one wallet. Add another before hiding this one.", "error")
        return redirect(url_for("wallets.index"))
    if _usage(wallet.id) == 0:
        db.session.delete(wallet)
        db.session.commit()
        flash(f"Wallet “{wallet.name}” deleted.", "success")
    else:
        wallet.archived = True
        db.session.commit()
        flash(f"“{wallet.name}” is hidden. Its past transactions stay in your history.", "success")
    return redirect(url_for("wallets.index"))


@wallets_bp.route("/<int:wallet_id>/restore", methods=["POST"])
@login_required
def restore(wallet_id):
    wallet = get_owned_or_404(Wallet, wallet_id)
    wallet.archived = False
    db.session.commit()
    flash(f"“{wallet.name}” is back in your wallets.", "success")
    return redirect(url_for("wallets.index"))


@wallets_bp.route("/transfer", methods=["GET", "POST"])
@login_required
def transfer():
    wallets = finance.wallets_for(current_user.id)
    by_id = {w.id: w for w in wallets}
    values = {"from_wallet_id": request.args.get("from", ""), "to_wallet_id": request.args.get("to", ""),
              "amount": "", "date": today().isoformat(), "note": ""}
    errors = {}
    if len(wallets) < 2:
        flash("Add a second wallet first, then you can move money between them.", "info")
        return redirect(url_for("wallets.form"))
    if request.method == "POST":
        data, errors = validate_transfer(request.form, by_id, today())
        values = data["raw"]
        if not errors:
            c = data["clean"]
            db.session.add(WalletTransfer(user_id=current_user.id, from_wallet_id=c["from_wallet"].id,
                                          to_wallet_id=c["to_wallet"].id, amount=c["amount"], date=c["date"],
                                          note=c["note"]))
            db.session.commit()
            flash(f"Moved {format_money(c['amount'])} from {c['from_wallet'].name} to {c['to_wallet'].name}.", "success")
            return redirect(url_for("wallets.index"))
    balances = {b.wallet.id: b.balance for b in finance.wallet_balances(current_user.id, today())}
    return render_template("wallets/transfer.html", values=values, errors=errors, wallets=wallets,
                           balances=balances), (400 if errors else 200)


@wallets_bp.route("/transfers/<int:transfer_id>/delete", methods=["POST"])
@login_required
def delete_transfer(transfer_id):
    t = get_owned_or_404(WalletTransfer, transfer_id)
    db.session.delete(t)
    db.session.commit()
    flash("Transfer removed. Both wallet balances were updated.", "success")
    return redirect(url_for("wallets.index"))
