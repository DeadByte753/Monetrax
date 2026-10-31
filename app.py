import os

import click
from flask import Flask, render_template, request
from flask_login import current_user

from config import Config

NAV_ITEMS = [
    ("dashboard.index", "Dashboard", "layout-dashboard"),
    ("transactions.index", "Transactions", "arrow-left-right"),
    ("wallets.index", "Wallets", "wallet"),
    ("budgets.index", "Budget Management", "wallet-cards"),
    ("savings.index", "Savings Goals", "piggy-bank"),
    ("analytics.index", "Analytics & Reports", "chart-column"),
    ("notifications.index", "Notifications", "bell"),
    ("settings.index", "Settings", "settings"),
]


def create_app(config_object=Config) -> Flask:
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object(config_object)
    os.makedirs(app.instance_path, exist_ok=True)

    from extensions import db, login_manager
    import models
    from security import init_security

    db.init_app(app)
    login_manager.init_app(app)
    init_security(app)

    _register_blueprints(app)
    _register_recurring(app)
    _register_template_helpers(app)
    _register_errors(app)
    _register_cli(app)

    with app.app_context():
        try:
            db.create_all()
        except Exception:
            db.session.rollback()
        _add_missing_columns(db)
        _add_recurring_unique_index(app, db)
        _backfill_wallets(db)

    return app


def _add_missing_columns(db) -> None:
    from sqlalchemy import inspect, text

    additions = {
        "users": {"theme": "VARCHAR(10) NOT NULL DEFAULT 'system'"},
        "transactions": {"wallet_id": "INTEGER", "recurring_id": "INTEGER"},
    }
    inspector = inspect(db.engine)
    for table, columns in additions.items():
        if not inspector.has_table(table):
            continue
        existing = {c["name"] for c in inspector.get_columns(table)}
        for name, ddl in columns.items():
            if name not in existing:
                try:
                    with db.engine.begin() as conn:
                        conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"))
                except Exception:
                    pass


def _add_recurring_unique_index(app: Flask, db) -> None:
    """Guard against a schedule posting the same date twice. Existing databases were created before this
    index existed; add it only when the data allows, and never delete user rows to make it fit."""
    from sqlalchemy import func, inspect, select, text
    from models import Transaction

    try:
        inspector = inspect(db.engine)
        if not inspector.has_table("transactions"):
            return
        if any(ix["name"] == "uq_transactions_recurring_date" for ix in inspector.get_indexes("transactions")):
            return
        dupes = db.session.execute(
            select(Transaction.recurring_id, Transaction.date)
            .where(Transaction.recurring_id.is_not(None))
            .group_by(Transaction.recurring_id, Transaction.date)
            .having(func.count(Transaction.id) > 1).limit(1)
        ).first()
        db.session.rollback()
        if dupes:
            app.logger.warning("Skipped uq_transactions_recurring_date: duplicate recurring entries exist. "
                               "Remove the duplicates, then restart to add the index.")
            return
        with db.engine.begin() as conn:
            conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_transactions_recurring_date "
                              "ON transactions (recurring_id, date)"))
    except Exception:
        db.session.rollback()
        app.logger.exception("Could not add uq_transactions_recurring_date")


def _backfill_wallets(db) -> None:
    from sqlalchemy import select, update
    from models import Transaction, User, Wallet

    try:
        no_wallets = db.session.scalars(
            select(User).where(~select(Wallet.id).where(Wallet.user_id == User.id).exists())).all()
        for user in no_wallets:
            Wallet.seed_defaults(user)
        if no_wallets:
            db.session.flush()
        orphan_users = db.session.scalars(
            select(Transaction.user_id).where(Transaction.wallet_id.is_(None)).distinct()).all()
        for uid in orphan_users:
            first = db.session.scalar(select(Wallet.id).where(Wallet.user_id == uid)
                                      .order_by(Wallet.position, Wallet.id).limit(1))
            db.session.execute(update(Transaction).where(Transaction.user_id == uid, Transaction.wallet_id.is_(None))
                               .values(wallet_id=first))
        db.session.commit()
    except Exception:
        db.session.rollback()


def _register_recurring(app: Flask) -> None:
    from flask import g
    from extensions import db

    @app.before_request
    def post_recurring():
        if request.method != "GET" or not request.endpoint or request.endpoint == "static":
            return
        if request.endpoint.startswith("auth.") or not current_user.is_authenticated:
            return
        import alerts, schedule
        from sqlalchemy.exc import IntegrityError
        from utils import today
        ref = today()
        try:
            if schedule.post_due(current_user, ref):
                alerts.refresh_budget_alerts(current_user, ref)
            db.session.commit()
        except IntegrityError:
            # Another request posted the same entries first; the unique index kept them single.
            db.session.rollback()
        except Exception:
            db.session.rollback()
            app.logger.exception("Posting recurring transactions failed")


def _register_blueprints(app: Flask) -> None:
    from auth import auth_bp
    from dashboard import dashboard_bp
    from transactions import transactions_bp
    import recurring
    from wallets import wallets_bp
    from budgets import budgets_bp
    from savings import savings_bp
    from analytics import analytics_bp
    from notifications import notifications_bp
    from settings import settings_bp

    for bp in (auth_bp, dashboard_bp, transactions_bp, wallets_bp, budgets_bp, savings_bp,
               analytics_bp, notifications_bp, settings_bp):
        app.register_blueprint(bp)


def _register_template_helpers(app: Flask) -> None:
    from alerts import unread_count
    from utils import CURRENCIES, compact_money, currency_symbol, format_money, to_local, today

    app.jinja_env.filters["money"] = lambda v, signed=False: format_money(v, signed=signed)
    app.jinja_env.filters["money0"] = lambda v: format_money(v, decimals=False)
    app.jinja_env.filters["php"] = lambda v, signed=False: format_money(v, "PHP", signed=signed)
    app.jinja_env.filters["cmoney"] = lambda v: compact_money(v)
    app.jinja_env.filters["localtime"] = lambda dt: to_local(dt).strftime("%b %d, %Y · %I:%M %p") if dt else ""

    from security import is_safe_redirect
    app.jinja_env.globals["is_safe_redirect"] = is_safe_redirect

    @app.context_processor
    def inject_globals():
        ctx = {"nav_items": NAV_ITEMS, "currencies": CURRENCIES}
        if current_user.is_authenticated:
            ctx["theme_pref"] = current_user.theme or "system"
        if current_user.is_authenticated and request.endpoint and not request.endpoint.startswith("auth."):
            ctx["unread_notifications"] = unread_count(current_user.id)
            ctx["currency_symbol"] = currency_symbol()
            ctx["today"] = today()
        return ctx


def _register_errors(app: Flask) -> None:
    from extensions import db

    @app.errorhandler(404)
    def not_found(_e):
        return render_template("errors/error.html", code=404, title="Page not found",
                               message="The page you're looking for doesn't exist or was moved."), 404

    @app.errorhandler(500)
    def server_error(_e):
        db.session.rollback()
        return render_template("errors/error.html", code=500, title="Something went wrong",
                               message="We couldn't complete that request. Please try again."), 500


def _register_cli(app: Flask) -> None:
    from extensions import db

    @app.cli.command("init-db", help="Create all database tables.")
    def init_db():
        db.create_all()
        click.echo("Monetrax database is ready.")


if __name__ == "__main__":
    create_app().run(debug=os.environ.get("FLASK_DEBUG") == "1")
