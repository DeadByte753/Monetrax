import re
from datetime import timedelta
from decimal import Decimal

from sqlalchemy import select

from extensions import db
from models import Notification, RecurringRule, Transaction, User, Wallet
import finance
import schedule
from test_modules import add_tx, date


def wallet_ids(app, user_id=1):
    with app.app_context():
        return {w.name: w.id for w in db.session.scalars(select(Wallet).where(Wallet.user_id == user_id))}


def balances(app, user_id=1):
    with app.app_context():
        return {b.wallet.name: b.balance for b in finance.wallet_balances(user_id, date.today())}


def test_new_accounts_get_cash_and_gcash(app, user_client):
    assert set(wallet_ids(app)) == {"Cash", "GCash"}
    page = user_client.get("/dashboard").data
    assert b"Safe to spend today" in page and b"Wallets" in page


def test_wallet_balances_follow_transactions_and_transfers(app, user_client, cat_id):
    w = wallet_ids(app)
    add_tx(user_client, cat_id("Allowance"), 3000, "income", "Allowance", wallet=w["GCash"])
    add_tx(user_client, cat_id("Food"), 120, wallet=w["Cash"])
    r = user_client.post("/wallets/transfer", data={"from_wallet_id": w["GCash"], "to_wallet_id": w["Cash"],
                                                    "amount": "1000", "date": date.today().isoformat()})
    assert r.status_code == 302
    assert balances(app) == {"Cash": Decimal("880"), "GCash": Decimal("2000")}
    with app.app_context():
        t = finance.totals(1)
        assert (t["income"], t["expense"]) == (Decimal("3000"), Decimal("120"))
    bad = user_client.post("/wallets/transfer", data={"from_wallet_id": w["Cash"], "to_wallet_id": w["Cash"],
                                                      "amount": "5"})
    assert bad.status_code == 400 and b"Pick a different wallet" in bad.data
    user_client.post("/wallets/transfers/1/delete")
    assert balances(app) == {"Cash": Decimal("-120"), "GCash": Decimal("3000")}
    assert b"Below zero" in user_client.get("/wallets/").data


def test_add_edit_hide_restore_wallet(app, user_client, cat_id):
    r = user_client.post("/wallets/new", data={"name": "BPI Savings", "type": "bank", "opening_balance": "5,000",
                                              "color": "#0B1B3F"})
    assert r.status_code == 302
    w = wallet_ids(app)
    assert balances(app)["BPI Savings"] == Decimal("5000")
    with app.app_context():
        assert db.session.get(Wallet, w["BPI Savings"]).spendable is False
    dup = user_client.post("/wallets/new", data={"name": "bpi savings", "type": "bank"})
    assert dup.status_code == 400 and b"already have a wallet" in dup.data
    user_client.post(f"/wallets/{w['BPI Savings']}/edit", data={"name": "BPI", "type": "bank",
                                                               "opening_balance": "6000", "spendable": "on"})
    assert balances(app)["BPI"] == Decimal("6000")
    user_client.post(f"/wallets/{w['BPI Savings']}/hide")
    assert "BPI" not in wallet_ids(app)
    add_tx(user_client, cat_id("Food"), 50, wallet=w["GCash"])
    user_client.post(f"/wallets/{w['GCash']}/hide")
    with app.app_context():
        assert db.session.get(Wallet, w["GCash"]).archived is True
    assert "GCash" not in balances(app)
    r = user_client.post(f"/wallets/{w['Cash']}/hide", follow_redirects=True)
    assert b"Keep at least one wallet" in r.data
    user_client.post(f"/wallets/{w['GCash']}/restore")
    assert "GCash" in balances(app)


def test_transaction_requires_owned_wallet(app, client, register, cat_id):
    register()
    juan_wallet = wallet_ids(app)["Cash"]
    client.post("/logout")
    register(name="Maria Santos", email="maria@school.edu.ph")
    r = add_tx(client, cat_id("Food", user_id=2), 10, wallet=juan_wallet)
    assert r.status_code == 400 and b"Choose where the money came from" in r.data
    assert client.get(f"/wallets/{juan_wallet}/edit").status_code == 404


def test_filter_and_export_by_wallet(app, user_client, cat_id):
    w = wallet_ids(app)
    add_tx(user_client, cat_id("Food"), 50, name="Siomai", wallet=w["Cash"])
    add_tx(user_client, cat_id("Transportation"), 13, name="Jeep", wallet=w["GCash"])
    page = user_client.get(f"/transactions/?wallet={w['GCash']}").data
    assert b"Jeep" in page and b"Siomai" not in page
    csv = user_client.get("/transactions/export.csv").data.decode("utf-8-sig")
    assert csv.splitlines()[0] == "Date,Name,Type,Category,Wallet,Amount (PHP),Description"
    assert ",Cash,-₱50.00," in csv


def test_monthly_schedule_handles_short_months(app):
    with app.app_context():
        rule = RecurringRule(frequency="monthly", start_date=date(2026, 1, 31), posted_count=0, active=True)
        got = [schedule.occurrence_date(rule, n) for n in range(4)]
        assert got == [date(2026, 1, 31), date(2026, 2, 28), date(2026, 3, 31), date(2026, 4, 30)]


def test_repeat_from_transaction_form_catches_up(app, user_client, cat_id):
    start = date.today() - timedelta(days=14)
    r = add_tx(user_client, cat_id("Allowance"), 2500, "income", "Weekly allowance", when=start, repeat="weekly",
               wallet=wallet_ids(app)["GCash"])
    assert r.status_code == 200 and b"set to repeat every week" in r.data
    with app.app_context():
        txs = db.session.scalars(select(Transaction).order_by(Transaction.date)).all()
        assert [t.date for t in txs] == [start, start + timedelta(days=7), start + timedelta(days=14)]
        assert all(t.recurring_id == 1 for t in txs)
        rule = db.session.get(RecurringRule, 1)
        assert schedule.next_date(rule) == start + timedelta(days=21)
        assert db.session.query(Notification).filter(Notification.title == "Weekly allowance received").count() == 1
    user_client.get("/dashboard")
    user_client.get("/transactions/")
    with app.app_context():
        assert db.session.query(Transaction).count() == 3


def test_due_entries_post_on_next_visit(app, user_client, cat_id):
    tomorrow = date.today() + timedelta(days=1)
    user_client.post("/transactions/recurring/new", data={
        "type": "expense", "name": "Netflix", "amount": "149", "frequency": "monthly", "date": tomorrow.isoformat(),
        "category_id": cat_id("Entertainment"), "wallet_id": wallet_ids(app)["GCash"]})
    with app.app_context():
        assert db.session.query(Transaction).count() == 0
        rule = db.session.get(RecurringRule, 1)
        rule.start_date = date.today()
        db.session.commit()
    user_client.get("/wallets/")
    with app.app_context():
        tx = db.session.scalars(select(Transaction)).one()
        assert (tx.name, tx.amount, tx.date) == ("Netflix", Decimal("149.00"), date.today())


def test_pause_skip_edit_delete_recurring(app, user_client, cat_id):
    start = date.today() + timedelta(days=3)
    user_client.post("/transactions/recurring/new", data={
        "type": "income", "name": "Allowance", "amount": "2000", "frequency": "weekly", "date": start.isoformat(),
        "category_id": cat_id("Allowance"), "wallet_id": wallet_ids(app)["Cash"]})
    page = user_client.get("/transactions/recurring").data
    assert b"Allowance" in page and start.strftime("%b %d").encode() in page
    user_client.post("/transactions/recurring/1/skip")
    with app.app_context():
        assert schedule.next_date(db.session.get(RecurringRule, 1)) == start + timedelta(days=7)
    user_client.post("/transactions/recurring/1/toggle")
    assert b"Paused" in user_client.get("/transactions/recurring").data
    user_client.post("/transactions/recurring/1/toggle")
    nxt = date.today() + timedelta(days=2)
    user_client.post("/transactions/recurring/1/edit", data={
        "type": "income", "name": "Allowance", "amount": "2500", "frequency": "biweekly", "date": nxt.isoformat(),
        "category_id": cat_id("Allowance"), "wallet_id": wallet_ids(app)["Cash"]})
    with app.app_context():
        rule = db.session.get(RecurringRule, 1)
        assert (rule.amount, rule.frequency, schedule.next_date(rule)) == (Decimal("2500"), "biweekly", nxt)
    user_client.post("/transactions/recurring/1/delete")
    with app.app_context():
        assert db.session.get(RecurringRule, 1) is None


def test_recurring_validation(user_client, cat_id):
    r = user_client.post("/transactions/recurring/new", data={
        "type": "income", "name": "", "amount": "0", "frequency": "hourly",
        "date": "2026-05-01", "end_date": "2026-04-01", "category_id": cat_id("Food")})
    assert r.status_code == 400
    for msg in (b"Give this transaction a name", b"greater than zero", b"Choose how often", b"on or after",
                b"Pick an income category", b"Choose where the money went"):
        assert msg in r.data


def test_deleting_rule_keeps_posted_entries(app, user_client, cat_id):
    add_tx(user_client, cat_id("Allowance"), 1000, "income", "Allowance", repeat="weekly")
    user_client.post("/transactions/recurring/1/delete")
    with app.app_context():
        tx = db.session.scalars(select(Transaction)).one()
        assert tx.recurring_id is None


def test_safe_to_spend_uses_next_allowance_and_bills(app, user_client, cat_id):
    w = wallet_ids(app)
    ref = date.today()
    add_tx(user_client, cat_id("Allowance"), 1000, "income", "Leftover", wallet=w["GCash"])
    user_client.post("/transactions/recurring/new", data={
        "type": "income", "name": "Allowance", "amount": "2500", "frequency": "weekly",
        "date": (ref + timedelta(days=5)).isoformat(), "category_id": cat_id("Allowance"), "wallet_id": w["GCash"]})
    user_client.post("/transactions/recurring/new", data={
        "type": "expense", "name": "Load", "amount": "100", "frequency": "monthly",
        "date": (ref + timedelta(days=2)).isoformat(), "category_id": cat_id("Personal Needs"), "wallet_id": w["GCash"]})
    add_tx(user_client, cat_id("Food"), 60, wallet=w["GCash"])
    with app.app_context():
        s = finance.safe_to_spend(1, ref)
        assert s.basis == "income" and s.days == 5 and s.until == ref + timedelta(days=5)
        assert s.spendable_balance == Decimal("940") and s.set_aside == Decimal("100")
        assert s.daily == Decimal("180.00")
        assert s.left_today == Decimal("120.00") and s.status == "ok"
    page = user_client.get("/dashboard").data.decode()
    assert "₱120.00" in page and "until your" in page and "Allowance" in page and "Load" in page


def test_safe_to_spend_ignores_savings_wallet_and_falls_back_to_month_end(app, user_client, cat_id):
    user_client.post("/wallets/new", data={"name": "Savings", "type": "bank", "opening_balance": "10000"})
    w = wallet_ids(app)
    add_tx(user_client, cat_id("Allowance"), 600, "income", wallet=w["Cash"])
    with app.app_context():
        s = finance.safe_to_spend(1, date.today())
        assert s.basis == "month" and s.spendable_balance == Decimal("600")
    add_tx(user_client, cat_id("Food"), 5000, wallet=w["Cash"])
    with app.app_context():
        s = finance.safe_to_spend(1, date.today())
        assert s.status == "over" and s.left_today < 0
    user_client.post("/transactions/recurring/new", data={
        "type": "expense", "name": "Dorm rent", "amount": "9000", "frequency": "monthly",
        "date": (date.today() + timedelta(days=1)).isoformat(), "category_id": cat_id("Others"), "wallet_id": w["Cash"]})
    with app.app_context():
        s = finance.safe_to_spend(1, date.today())
        if s.until > date.today() + timedelta(days=1):
            assert s.status == "empty" and s.daily == 0


def test_existing_accounts_get_wallets_on_upgrade(tmp_path):
    import sqlite3
    from app import create_app
    from config import TestConfig

    path = tmp_path / "before-wallets.sqlite3"

    class Cfg(TestConfig):
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{path}"

    app = create_app(Cfg)
    client = app.test_client()
    client.post("/register", data={"full_name": "Old User", "email": "old@school.edu.ph", "password": "Budget2026",
                                   "confirm_password": "Budget2026", "terms": "on"})
    con = sqlite3.connect(path)
    food = con.execute("SELECT id FROM categories WHERE name='Food'").fetchone()[0]
    con.execute("DELETE FROM wallets")
    con.execute("INSERT INTO transactions (user_id, category_id, name, amount, type, date, created_at, updated_at) "
                "VALUES (1, ?, 'Old lunch', 80, 'expense', '2026-10-01', '2026-10-01', '2026-10-01')", (food,))
    con.commit()
    con.close()

    app2 = create_app(Cfg)
    with app2.app_context():
        names = set(db.session.scalars(select(Wallet.name).where(Wallet.user_id == 1)))
        tx = db.session.scalars(select(Transaction)).one()
        assert names == {"Cash", "GCash"} and tx.wallet.name == "Cash"
