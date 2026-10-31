import csv
import io
import json
import re
from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy import func, inspect, select, text
from sqlalchemy.exc import IntegrityError

from extensions import db
from models import (Budget, Category, RecurringRule, SavingsContribution, SavingsGoal, Transaction, Wallet,
                    WalletTransfer)
import finance
import schedule
from test_modules import add_tx, date
from test_wallets_recurring import balances, wallet_ids


def tx_count(app, **where):
    with app.app_context():
        stmt = select(func.count(Transaction.id))
        for k, v in where.items():
            stmt = stmt.where(getattr(Transaction, k) == v)
        return db.session.scalar(stmt)


def chart_data(page: bytes, source: str) -> dict:
    m = re.search(rf'<script type="application/json" id="{source}">(.*?)</script>', page.decode(), re.S)
    return json.loads(m.group(1))


def read_csv(resp) -> list:
    return list(csv.reader(io.StringIO(resp.data.decode("utf-8-sig"))))


def new_rule(client, app, cat, freq="daily", start=None, end=None, tx_type="expense", amount="10", name="Load"):
    return client.post("/transactions/recurring/new", data={
        "type": tx_type, "name": name, "amount": amount, "frequency": freq,
        "date": (start or date.today()).isoformat(), "end_date": end.isoformat() if end else "",
        "category_id": cat, "wallet_id": wallet_ids(app)["Cash"]})


# ---------- Recurring ----------

def test_yearly_schedule(app):
    with app.app_context():
        rule = RecurringRule(frequency="yearly", start_date=date(2024, 2, 29), posted_count=0, active=True)
        assert [schedule.occurrence_date(rule, n) for n in range(3)] == [date(2024, 2, 29), date(2025, 2, 28),
                                                                          date(2026, 2, 28)]
        rule.amount = Decimal("1200")
        assert schedule.monthly_estimate(rule) == Decimal("100.00")


def test_yearly_rule_posts_catch_up_and_shows_next(app, user_client, cat_id):
    start = date.today().replace(year=date.today().year - 2)
    r = new_rule(user_client, app, cat_id("Education"), "yearly", start, amount="5000", name="Tuition")
    assert r.status_code == 302
    assert tx_count(app, name="Tuition") == 3
    page = user_client.get("/transactions/recurring").data.decode()
    assert "Every year" in page and "Tuition" in page


def test_catch_up_and_no_duplicates_on_repeat_requests(app, user_client, cat_id):
    new_rule(user_client, app, cat_id("Food"), "daily", date.today() - timedelta(days=9))
    assert tx_count(app, name="Load") == 10
    for path in ("/dashboard", "/transactions/", "/transactions/recurring", "/analytics/"):
        user_client.get(path)
    assert tx_count(app, name="Load") == 10
    with app.app_context():
        # Simulate a restarted schedule (old edit bug): posting again must skip dates already present.
        rule = db.session.scalar(select(RecurringRule))
        rule.posted_count = 0
        db.session.commit()
        user = rule.user
        assert schedule.post_due(user, date.today()) == []
        db.session.commit()
        assert rule.posted_count == 10
    assert tx_count(app, name="Load") == 10


def test_database_rejects_duplicate_schedule_entry(app, user_client, cat_id):
    new_rule(user_client, app, cat_id("Food"), "daily")
    with app.app_context():
        t = db.session.scalar(select(Transaction))
        db.session.add(Transaction(user_id=t.user_id, name="dup", amount=1, type="expense", date=t.date,
                                   category_id=t.category_id, wallet_id=t.wallet_id, recurring_id=t.recurring_id))
        with pytest.raises(IntegrityError):
            db.session.commit()
        db.session.rollback()


def test_edit_rule_rejects_past_next_date(app, user_client, cat_id):
    new_rule(user_client, app, cat_id("Food"), "weekly", date.today() - timedelta(days=14))
    before = tx_count(app)
    r = user_client.post("/transactions/recurring/1/edit", data={
        "type": "expense", "name": "Load", "amount": "10", "frequency": "weekly",
        "date": (date.today() - timedelta(days=3)).isoformat(), "category_id": cat_id("Food"),
        "wallet_id": wallet_ids(app)["Cash"]})
    assert r.status_code == 400 and b"can&#39;t be in the past" in r.data
    assert tx_count(app) == before


def test_end_date_pause_resume(app, user_client, cat_id):
    start = date.today() - timedelta(days=2)
    new_rule(user_client, app, cat_id("Food"), "daily", start, end=start + timedelta(days=4))
    assert tx_count(app) == 3
    user_client.post("/transactions/recurring/1/toggle")
    with app.app_context():
        rule = db.session.get(RecurringRule, 1)
        assert rule.active is False and schedule.next_date(rule) is None
        rule.posted_count = 2  # pretend a day was missed while paused
        db.session.commit()
    user_client.post("/transactions/recurring/1/toggle")
    with app.app_context():
        rule = db.session.get(RecurringRule, 1)
        assert rule.active and schedule.next_date(rule) == date.today() + timedelta(days=1)
    assert tx_count(app) == 3  # resuming skips the paused gap instead of back-filling


def test_upcoming_list(app, user_client, cat_id):
    new_rule(user_client, app, cat_id("Food"), "weekly", date.today() + timedelta(days=3), name="Dorm rent")
    page = user_client.get("/transactions/recurring").data.decode()
    assert "Upcoming · next 30 days" in page
    first = (date.today() + timedelta(days=3)).strftime("%b %d")
    assert first in page and page.count("Dorm rent") >= 3


# ---------- Transactions ----------

def test_detail_duplicate_edit_delete(app, user_client, cat_id):
    w = wallet_ids(app)
    add_tx(user_client, cat_id("Food"), 85.5, name="Siomai", desc="With rice", wallet=w["GCash"],
           when=date.today() - timedelta(days=1))
    page = user_client.get("/transactions/1").data.decode()
    for text_ in ("Siomai", "₱85.50", "Food", "GCash", "Expense", "With rice",
                  (date.today() - timedelta(days=1)).strftime("%B %d, %Y")):
        assert text_ in page

    form = user_client.get("/transactions/1/duplicate", follow_redirects=True).data.decode()
    assert "Duplicate transaction" in form and 'value="85.50"' in form and 'value="Siomai"' in form
    assert f'value="{date.today().isoformat()}"' in form
    add_tx(user_client, cat_id("Food"), 85.5, name="Siomai", wallet=w["GCash"])
    assert tx_count(app, name="Siomai") == 2

    user_client.post("/transactions/2/edit", data={
        "name": "Siomai x2", "amount": "171", "type": "expense", "category_id": cat_id("Food"),
        "date": date.today().isoformat(), "wallet_id": w["Cash"]})
    with app.app_context():
        assert finance.totals(1)["expense"] == Decimal("256.50")
    assert "₱256.50" in user_client.get("/dashboard").data.decode()

    user_client.post("/transactions/2/delete")
    assert tx_count(app) == 1
    assert user_client.get("/transactions/2").status_code == 404
    with app.app_context():
        assert finance.totals(1)["expense"] == Decimal("85.50")


def test_detail_is_private(app, client, register, cat_id):
    register()
    add_tx(client, cat_id("Food"), 10, name="Mine")
    client.post("/logout")
    register(name="Maria Santos", email="maria@school.edu.ph")
    assert client.get("/transactions/1").status_code == 404
    assert client.get("/transactions/1/duplicate").status_code == 404
    assert client.get("/transactions/new?duplicate=1").status_code == 404


def test_editing_schedule_entry_onto_sibling_date_is_rejected(app, user_client, cat_id):
    new_rule(user_client, app, cat_id("Food"), "daily", date.today() - timedelta(days=1))
    r = user_client.post("/transactions/2/edit", data={
        "name": "Load", "amount": "10", "type": "expense", "category_id": cat_id("Food"),
        "date": (date.today() - timedelta(days=1)).isoformat(), "wallet_id": wallet_ids(app)["Cash"]})
    assert r.status_code == 400 and b"already has an entry on that date" in r.data


# ---------- Exports ----------

def test_csv_export_respects_filters_and_uses_peso(app, user_client, cat_id):
    add_tx(user_client, cat_id("Food"), 1234.5, name="Groceries")
    add_tx(user_client, cat_id("Food"), 20, name="=HYPERLINK(1)")
    add_tx(user_client, cat_id("Allowance"), 3000, "income", "Allowance")
    resp = user_client.get("/transactions/export.csv?type=expense&q=groc")
    assert resp.data.startswith("﻿".encode())
    rows = read_csv(resp)
    assert rows[0][5] == "Amount (PHP)"
    body = [r for r in rows[1:] if r and r[0]]
    assert len(body) == 1 and body[0][1] == "Groceries" and body[0][5] == "-₱1,234.50"
    assert ["", "Total expenses", "", "", "", "-₱1,234.50", ""] in rows
    everything = read_csv(user_client.get("/transactions/export.csv"))
    assert any(r[1] == "'=HYPERLINK(1)" for r in everything if len(r) > 1)


def test_monthly_summary_page_and_csv(app, user_client, cat_id):
    first = date.today().replace(day=1)
    add_tx(user_client, cat_id("Allowance"), 5000, "income", "Allowance", when=first)
    add_tx(user_client, cat_id("Food"), 1500, name="Food", when=first)
    add_tx(user_client, cat_id("Transportation"), 500, name="Jeep", when=first)
    user_client.post("/savings/new", data={"name": "Laptop", "target_amount": "20000", "icon": "laptop"})
    with app.app_context():
        goal = db.session.scalar(select(SavingsGoal))
        db.session.add(SavingsContribution(goal_id=goal.id, amount=Decimal("700"), date=first))
        db.session.commit()
    month = first.strftime("%Y-%m")
    page = user_client.get(f"/analytics/monthly?month={month}").data.decode()
    for s in ("₱5,000.00", "₱2,000.00", "₱3,000.00", "60% of income kept", "₱700.00", "Transportation"):
        assert s in page
    rows = read_csv(user_client.get(f"/analytics/monthly.csv?month={month}"))
    flat = {r[0]: r[1] for r in rows if len(r) >= 2}
    assert flat["Total income"] == "₱5,000.00"
    assert flat["Total expenses"] == "₱2,000.00"
    assert flat["Net savings (income − expenses)"] == "+₱3,000.00"
    assert flat["Added to savings goals this month"] == "₱700.00"
    assert flat["Food"] == "₱1,500.00" and flat["Transportation"] == "₱500.00"
    bad = user_client.get("/analytics/monthly?month=2999-01", follow_redirects=True)
    assert bad.status_code == 200 and b"Pick a month" in bad.data


# ---------- Analytics ----------

def test_analytics_charts_match_database(app, user_client, cat_id):
    w = wallet_ids(app)
    add_tx(user_client, cat_id("Allowance"), 4000, "income", "Allowance", wallet=w["GCash"])
    add_tx(user_client, cat_id("Food"), 900, name="Food", wallet=w["Cash"])
    add_tx(user_client, cat_id("Entertainment"), 300, name="Movie", wallet=w["GCash"])
    add_tx(user_client, cat_id("Transportation"), 150, name="Jeep", wallet=w["GCash"])
    data = chart_data(user_client.get("/analytics/").data, "an-data")

    bal = balances(app)
    assert dict(zip(data["wallets"]["labels"], data["wallets"]["values"])) == {k: float(v) for k, v in bal.items()}
    assert data["topCategories"]["labels"] == ["Food", "Entertainment", "Transportation"]
    assert data["topCategories"]["values"] == [900.0, 300.0, 150.0]
    assert data["savings"]["net"][-1] == 4000 - 1350
    assert len(data["savings"]["labels"]) == 6
    with app.app_context():
        t = finance.totals(1)
    assert sum(data["flow"]["income"]) == float(t["income"])
    assert sum(data["flow"]["expense"]) == float(t["expense"])


# ---------- Reset ----------

def test_reset_financial_data(app, user_client, cat_id):
    w = wallet_ids(app)
    add_tx(user_client, cat_id("Allowance"), 1000, "income", "Allowance", repeat="weekly")
    add_tx(user_client, cat_id("Food"), 50)
    user_client.post("/budgets/new", data={"category_id": cat_id("Food"), "limit_amount": "500", "period": "monthly"})
    user_client.post("/wallets/transfer", data={"from_wallet_id": w["Cash"], "to_wallet_id": w["GCash"],
                                                "amount": "10", "date": date.today().isoformat()})
    with app.app_context():
        db.session.get(Wallet, w["Cash"]).opening_balance = Decimal("99")
        db.session.commit()

    bad = user_client.post("/settings/reset-data", data={"reset_password": "wrong", "reset_confirm": "RESET"})
    assert bad.status_code == 400 and tx_count(app) == 2
    bad = user_client.post("/settings/reset-data", data={"reset_password": "Budget2026", "reset_confirm": "nope"})
    assert bad.status_code == 400 and tx_count(app) == 2

    ok = user_client.post("/settings/reset-data", data={"reset_password": "Budget2026", "reset_confirm": "reset"})
    assert ok.status_code == 302
    with app.app_context():
        for model in (Transaction, RecurringRule, Budget, WalletTransfer, SavingsGoal):
            assert db.session.scalar(select(func.count(model.id))) == 0
        assert {w_.name: w_.opening_balance for w_ in db.session.scalars(select(Wallet))} == \
            {"Cash": Decimal("0"), "GCash": Decimal("0")}
        assert db.session.scalar(select(func.count(Category.id))) > 0
    assert user_client.get("/dashboard").status_code == 200
    assert tx_count(app) == 0  # the deleted schedule must not re-post on the next page load


# ---------- Migration ----------

def test_unique_index_migration_is_safe(app):
    from app import _add_recurring_unique_index

    def has_index():
        return any(i["name"] == "uq_transactions_recurring_date" for i in inspect(db.engine).get_indexes("transactions"))

    with app.app_context():
        assert has_index()
        db.session.execute(text("DROP INDEX uq_transactions_recurring_date"))
        for _ in range(2):
            db.session.execute(text("INSERT INTO transactions (user_id, category_id, name, amount, type, date, "
                                    "recurring_id, created_at, updated_at) VALUES (9, 99, 'd', 1, 'expense', "
                                    "'2026-01-01', 5, '2026-01-01 00:00:00', '2026-01-01 00:00:00')"))
        db.session.commit()
        _add_recurring_unique_index(app, db)
        assert not has_index()  # duplicates present: skipped, nothing deleted
        assert db.session.scalar(text("SELECT COUNT(*) FROM transactions WHERE recurring_id = 5")) == 2
        db.session.execute(text("DELETE FROM transactions WHERE recurring_id = 5"))
        db.session.commit()
        _add_recurring_unique_index(app, db)
        assert has_index()
