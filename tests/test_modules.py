from datetime import date as _date, datetime, timedelta, timezone


class date(_date):
    @classmethod
    def today(cls):
        return datetime.now(timezone.utc).date()
from decimal import Decimal

from sqlalchemy import select

from extensions import db
from models import Notification, SavingsGoal, Transaction
import finance


def default_wallet(client):
    import re
    page = client.get("/transactions/new").data.decode()
    return re.search(r'name="wallet_id" value="(\d+)" checked', page).group(1)


def add_tx(client, cat, amount, tx_type="expense", name="Item", when=None, desc="", wallet=None, repeat=""):
    return client.post("/transactions/new", data={
        "name": name, "amount": str(amount), "type": tx_type, "category_id": cat,
        "date": (when or date.today()).isoformat(), "description": desc,
        "wallet_id": wallet or default_wallet(client), "repeat": repeat}, follow_redirects=True)


def test_all_pages_render(user_client):
    for path in ("/dashboard", "/transactions/", "/transactions/new", "/budgets/", "/budgets/new",
                 "/savings/", "/savings/new", "/analytics/", "/analytics/?range=6m", "/analytics/?range=year",
                 "/analytics/?range=last_month", "/notifications/", "/settings/",
                 "/settings/?section=preferences", "/settings/?section=categories",
                 "/settings/?section=security", "/settings/?section=danger", "/wallets/", "/wallets/new",
                 "/wallets/transfer", "/transactions/recurring", "/transactions/recurring/new",
                 "/transactions/recurring/new?type=expense"):
        resp = user_client.get(path)
        assert resp.status_code == 200, path


def test_protected_pages_redirect_when_signed_out(client):
    for path in ("/transactions/", "/budgets/", "/savings/", "/analytics/", "/notifications/", "/settings/"):
        assert client.get(path).status_code == 302, path


def test_balance_updates_on_add_edit_delete(app, user_client, cat_id):
    allowance, food = cat_id("Allowance"), cat_id("Food")
    assert add_tx(user_client, allowance, "5,000", "income", "Weekly allowance").status_code == 200
    add_tx(user_client, food, 120.50, name="Lunch")
    add_tx(user_client, food, 79.50, name="Snacks")
    with app.app_context():
        t = finance.totals(1)
        assert (t["income"], t["expense"], t["balance"]) == (Decimal("5000"), Decimal("200"), Decimal("4800"))
        lunch_id = db.session.scalar(select(Transaction.id).where(Transaction.name == "Lunch"))

    user_client.post(f"/transactions/{lunch_id}/edit", data={
        "name": "Lunch", "amount": "220.50", "type": "expense", "category_id": food, "date": date.today().isoformat(),
        "wallet_id": default_wallet(user_client)})
    with app.app_context():
        assert finance.totals(1)["balance"] == Decimal("4700")

    user_client.post(f"/transactions/{lunch_id}/delete")
    with app.app_context():
        assert finance.totals(1)["balance"] == Decimal("4920.50")

    page = user_client.get("/dashboard")
    assert "₱4,920.50".encode() in page.data


def test_transaction_validation(user_client, cat_id):
    resp = add_tx(user_client, cat_id("Allowance"), "-5", "expense", name="")
    assert resp.status_code == 400
    assert b"Give this transaction a name" in resp.data
    assert b"greater than zero" in resp.data
    assert b"Pick an expense category" in resp.data


def test_search_filter_sort(user_client, cat_id):
    food, transport = cat_id("Food"), cat_id("Transportation")
    add_tx(user_client, food, 50, name="Siomai", when=date.today() - timedelta(days=3))
    add_tx(user_client, transport, 26, name="Jeepney fare")
    add_tx(user_client, food, 300, name="Samgyup with friends", desc="birthday")
    r = user_client.get("/transactions/?q=birthday")
    assert b"Samgyup" in r.data and b"Siomai" not in r.data
    r = user_client.get(f"/transactions/?category={transport}")
    assert b"Jeepney" in r.data and b"Siomai" not in r.data
    r = user_client.get("/transactions/?sort=amount_desc")
    assert r.data.index(b"Samgyup") < r.data.index(b"Jeepney")
    start = date.today().isoformat()
    r = user_client.get(f"/transactions/?start={start}")
    assert b"Siomai" not in r.data and b"Jeepney" in r.data
    csv = user_client.get("/transactions/export.csv?type=expense")
    assert csv.mimetype == "text/csv" and b"Jeepney fare" in csv.data


def test_users_cannot_touch_each_others_data(app, client, register, cat_id):
    register()
    add_tx(client, cat_id("Food"), 99, name="Private lunch")
    client.post("/logout")
    register(name="Maria Santos", email="maria@school.edu.ph")
    with app.app_context():
        tid = db.session.scalar(select(Transaction.id).where(Transaction.name == "Private lunch"))
    assert client.get(f"/transactions/{tid}/edit").status_code == 404
    assert client.post(f"/transactions/{tid}/delete").status_code == 404
    assert b"Private lunch" not in client.get("/transactions/").data
    assert add_tx(client, cat_id("Food", user_id=1), 10).status_code == 400


def test_budget_progress_and_threshold_notifications(app, user_client, cat_id):
    food = cat_id("Food")
    assert user_client.post("/budgets/new", data={"category_id": food, "limit_amount": "1000",
                                                  "period": "monthly"}).status_code == 302
    add_tx(user_client, food, 760)
    with app.app_context():
        msgs = db.session.scalars(select(Notification.message)).all()
        assert any("You have used 76% of your monthly Food budget" in m for m in msgs)
    add_tx(user_client, food, 150)
    add_tx(user_client, food, 200)
    with app.app_context():
        msgs = db.session.scalars(select(Notification.message)).all()
        assert any("used 91%" in m for m in msgs)
        assert any("exceeded your monthly Food budget" in m for m in msgs)
        assert len(msgs) == 3
        s = finance.budgets_with_status(1, date.today())[0]
        assert s.spent == Decimal("1110") and s.remaining == Decimal("-110") and s.level == "over"
    page = user_client.get("/budgets/")
    assert b"Over budget" in page.data
    user_client.get("/notifications/")
    with app.app_context():
        assert db.session.query(Notification).count() == 3


def test_duplicate_budget_rejected(user_client, cat_id):
    food = cat_id("Food")
    user_client.post("/budgets/new", data={"category_id": food, "limit_amount": "500", "period": "weekly"})
    r = user_client.post("/budgets/new", data={"category_id": food, "limit_amount": "600", "period": "weekly"})
    assert r.status_code == 400 and b"already have a weekly budget" in r.data


def test_budget_edit_and_delete(app, user_client, cat_id):
    food = cat_id("Food")
    user_client.post("/budgets/new", data={"category_id": food, "limit_amount": "500", "period": "weekly"})
    user_client.post("/budgets/1/edit", data={"category_id": food, "limit_amount": "800", "period": "monthly"})
    with app.app_context():
        s = finance.budgets_with_status(1, date.today())[0]
        assert s.budget.limit_amount == Decimal("800") and s.budget.period == "monthly"
    user_client.post("/budgets/1/delete")
    with app.app_context():
        assert finance.budgets_with_status(1, date.today()) == []


def test_savings_goal_flow(app, user_client):
    r = user_client.post("/savings/new", data={"name": "New laptop", "target_amount": "30000",
                                              "initial_amount": "5000", "icon": "laptop"})
    assert r.status_code == 302
    user_client.post("/savings/1/contribute", data={"amount": "10000", "direction": "add"})
    with app.app_context():
        g = db.session.get(SavingsGoal, 1)
        assert g.saved_amount == Decimal("15000") and g.percent == 50.0
        assert finance.total_savings(1) == Decimal("15000")
        assert any("Halfway" in t for t in db.session.scalars(select(Notification.title)))
    r = user_client.post("/savings/1/contribute", data={"amount": "99999", "direction": "withdraw"})
    with app.app_context():
        assert db.session.get(SavingsGoal, 1).saved_amount == Decimal("15000")
    user_client.post("/savings/1/contribute", data={"amount": "15000", "direction": "add"})
    with app.app_context():
        g = db.session.get(SavingsGoal, 1)
        assert g.is_complete and g.completed_at is not None
    assert b"Goals reached" in user_client.get("/savings/").data


def test_analytics_and_insights(user_client, cat_id):
    add_tx(user_client, cat_id("Allowance"), 3000, "income")
    add_tx(user_client, cat_id("Food"), 900, name="Groceries")
    add_tx(user_client, cat_id("Transportation"), 100)
    r = user_client.get("/analytics/")
    assert r.status_code == 200 and b"Groceries" in r.data and b"Spending by category" in r.data
    custom = user_client.get(f"/analytics/?range=custom&start={date.today().isoformat()}&end={date.today().isoformat()}")
    assert custom.status_code == 200
    bad = user_client.get("/analytics/?range=custom&start=2026-05-01&end=2026-01-01")
    assert b"Pick a valid start and end date" in bad.data
    dash = user_client.get("/dashboard")
    assert b"Food is your top expense" in dash.data


def test_notifications_read_and_dismiss(app, user_client, cat_id):
    food = cat_id("Food")
    user_client.post("/budgets/new", data={"category_id": food, "limit_amount": "100", "period": "weekly"})
    add_tx(user_client, food, 200)
    user_client.post("/notifications/read-all")
    with app.app_context():
        assert db.session.query(Notification).filter_by(is_read=False).count() == 0
    user_client.post("/notifications/1/delete")
    assert b"all caught up" in user_client.get("/notifications/").data
    with app.app_context():
        assert db.session.query(Notification).count() == 1


def test_settings_profile_password_categories_delete(app, client, register):
    register()
    r = client.post("/settings/profile", data={"full_name": "Juan P. Dela Cruz", "email": "juan@school.edu.ph",
                                               "school": "Aklan State University", "year_level": "2nd year"})
    assert r.status_code == 302
    client.post("/settings/preferences", data={"currency": "USD"})
    assert b"$0.00" in client.get("/dashboard").data

    bad = client.post("/settings/password", data={"current_password": "nope", "new_password": "NewPass2026",
                                                  "confirm_password": "NewPass2026"})
    assert bad.status_code == 400 and b"current password is incorrect" in bad.data
    client.post("/settings/password", data={"current_password": "Budget2026", "new_password": "NewPass2026",
                                            "confirm_password": "NewPass2026"})
    client.post("/logout")
    assert client.post("/login", data={"email": "juan@school.edu.ph", "password": "NewPass2026"}).status_code == 302

    client.post("/settings/categories", data={"name": "Org fees", "type": "expense", "color": "#123456"})
    assert b"Org fees" in client.get("/settings/?section=categories").data
    dup = client.post("/settings/categories", data={"name": "org fees", "type": "expense"})
    assert dup.status_code == 400

    r = client.post("/settings/delete-account", data={"password": "NewPass2026", "confirm": "DELETE"})
    assert r.status_code == 302
    assert client.post("/login", data={"email": "juan@school.edu.ph", "password": "NewPass2026"}).status_code == 400


def test_theme_saved_to_account(app, user_client):
    assert b'var pref = "system"' in user_client.get("/dashboard").data
    r = user_client.post("/settings/theme", data={"theme": "dark"}, headers={"X-Requested-With": "fetch"})
    assert r.status_code == 204
    assert b'var pref = "dark"' in user_client.get("/transactions/").data
    assert user_client.post("/settings/theme", data={"theme": "neon"},
                            headers={"X-Requested-With": "fetch"}).status_code == 400
    user_client.post("/settings/preferences", data={"currency": "PHP", "theme": "light"})
    page = user_client.get("/settings/?section=preferences")
    assert b'var pref = "light"' in page.data and b'value="light" data-theme-live checked' in page.data


def test_theme_toggle_on_every_screen(user_client, client):
    for path in ("/dashboard", "/budgets/", "/settings/"):
        assert b"data-theme-toggle" in user_client.get(path).data
    user_client.post("/logout")
    assert b"data-theme-toggle" in client.get("/login").data


def test_existing_database_gets_theme_column(tmp_path):
    import sqlite3
    from app import create_app
    from config import TestConfig

    path = tmp_path / "old.sqlite3"
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, full_name VARCHAR(80), email VARCHAR(254), "
                "password_hash VARCHAR(255), school VARCHAR(120), program VARCHAR(120), year_level VARCHAR(30), "
                "currency VARCHAR(3), budget_alerts BOOLEAN, savings_alerts BOOLEAN, created_at DATETIME, "
                "last_login_at DATETIME)")
    con.commit()
    con.close()

    class Cfg(TestConfig):
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{path}"

    create_app(Cfg)
    cols = [r[1] for r in sqlite3.connect(path).execute("PRAGMA table_info(users)")]
    assert "theme" in cols
