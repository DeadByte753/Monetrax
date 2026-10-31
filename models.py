from __future__ import annotations

import hashlib
import hmac
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Optional

from flask import current_app
from flask_login import UserMixin
from sqlalchemy import (Boolean, Date, DateTime, ForeignKey, Index, Integer, Numeric, String, Text,
                        UniqueConstraint, func, select)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Mapped, mapped_column, relationship
from werkzeug.security import check_password_hash, generate_password_hash

from extensions import db, login_manager


_DUMMY_HASH = generate_password_hash("monetrax-timing-guard")


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class EmailAlreadyRegistered(Exception):
    pass


THEMES = ("system", "light", "dark")


class User(UserMixin, db.Model):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    full_name: Mapped[str] = mapped_column(String(80))
    email: Mapped[str] = mapped_column(String(254), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))

    school: Mapped[Optional[str]] = mapped_column(String(120))
    program: Mapped[Optional[str]] = mapped_column(String(120))
    year_level: Mapped[Optional[str]] = mapped_column(String(30))

    currency: Mapped[str] = mapped_column(String(3), default="PHP")
    budget_alerts: Mapped[bool] = mapped_column(Boolean, default=True)
    savings_alerts: Mapped[bool] = mapped_column(Boolean, default=True)
    theme: Mapped[str] = mapped_column(String(10), default="system", server_default="system")

    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    last_login_at: Mapped[Optional[datetime]] = mapped_column(DateTime)

    categories = relationship("Category", back_populates="user", cascade="all, delete-orphan", lazy="dynamic")
    transactions = relationship("Transaction", back_populates="user", cascade="all, delete-orphan", lazy="dynamic")
    budgets = relationship("Budget", back_populates="user", cascade="all, delete-orphan", lazy="dynamic")
    goals = relationship("SavingsGoal", back_populates="user", cascade="all, delete-orphan", lazy="dynamic")
    notifications = relationship("Notification", back_populates="user", cascade="all, delete-orphan", lazy="dynamic")
    wallets = relationship("Wallet", back_populates="user", cascade="all, delete-orphan", lazy="dynamic")
    recurring = relationship("RecurringRule", back_populates="user", cascade="all, delete-orphan", lazy="dynamic")

    @property
    def first_name(self) -> str:
        return self.full_name.split()[0] if self.full_name else ""

    @property
    def initials(self) -> str:
        parts = [p for p in (self.full_name or "").split() if p]
        if not parts:
            return "?"
        return (parts[0][0] + (parts[-1][0] if len(parts) > 1 else "")).upper()

    @classmethod
    def get_by_email(cls, email: str) -> Optional["User"]:
        return db.session.scalar(select(cls).where(func.lower(cls.email) == email.lower()))

    @classmethod
    def email_exists(cls, email: str) -> bool:
        return cls.get_by_email(email) is not None

    @classmethod
    def create(cls, full_name: str, email: str, password: str) -> "User":
        user = cls(full_name=full_name, email=email.lower())
        user.set_password(password)
        db.session.add(user)
        try:
            db.session.flush()
            Category.seed_defaults(user)
            Wallet.seed_defaults(user)
            db.session.commit()
        except IntegrityError as exc:
            db.session.rollback()
            raise EmailAlreadyRegistered(email) from exc
        return user

    def get_id(self) -> str:
        return f"{self.id}.{_session_stamp(self.password_hash)}"

    def set_password(self, password: str) -> None:
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)

    def record_login(self) -> None:
        self.last_login_at = utcnow()
        db.session.commit()


def burn_password_check(password: str) -> None:
    check_password_hash(_DUMMY_HASH, password)


def _session_stamp(password_hash: str) -> str:
    """Short keyed fingerprint of the password hash. It is part of the login session id, so changing the
    password (or resetting it) signs the account out everywhere else, including "remember me" cookies."""
    key = (current_app.config.get("SECRET_KEY") or "").encode()
    return hmac.new(key, (password_hash or "").encode(), hashlib.sha256).hexdigest()[:24]


@login_manager.user_loader
def load_user(user_id: str) -> Optional[User]:
    uid, sep, stamp = (user_id or "").partition(".")
    if not sep or not uid.isdigit():
        return None
    user = db.session.get(User, int(uid))
    if user is None or not hmac.compare_digest(stamp, _session_stamp(user.password_hash)):
        return None
    return user


class AuthThrottle(db.Model):
    """Failed sign-in / password attempts per key ("email:…", "ip:…", "user:…") for brute-force lockout."""
    __tablename__ = "auth_throttle"

    key: Mapped[str] = mapped_column(String(300), primary_key=True)
    failures: Mapped[int] = mapped_column(Integer, default=0)
    window_start: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    locked_until: Mapped[Optional[datetime]] = mapped_column(DateTime)


DEFAULT_CATEGORIES = [
    ("Food", "expense", "utensils", "#047857"),
    ("Transportation", "expense", "bus", "#2563EB"),
    ("Education", "expense", "graduation-cap", "#0B1B3F"),
    ("School Supplies", "expense", "pencil-ruler", "#7C3AED"),
    ("Personal Needs", "expense", "shopping-bag", "#DB2777"),
    ("Entertainment", "expense", "clapperboard", "#EA580C"),
    ("Others", "expense", "ellipsis", "#64748B"),
    ("Allowance", "income", "wallet", "#10B981"),
    ("Scholarship", "income", "award", "#0EA5E9"),
    ("Part-time Income", "income", "briefcase", "#6366F1"),
    ("Other Income", "income", "circle-plus", "#14B8A6"),
]

CUSTOM_COLORS = ["#0891B2", "#CA8A04", "#9333EA", "#E11D48", "#059669", "#4F46E5", "#D97706", "#0D9488"]


class Category(db.Model):
    __tablename__ = "categories"
    __table_args__ = (UniqueConstraint("user_id", "type", "name", name="uq_categories_user_type_name"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(40))
    type: Mapped[str] = mapped_column(String(10))
    icon: Mapped[str] = mapped_column(String(40), default="tag")
    color: Mapped[str] = mapped_column(String(7), default="#64748B")
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)

    user = relationship("User", back_populates="categories")
    transactions = relationship("Transaction", back_populates="category", lazy="dynamic")
    budgets = relationship("Budget", back_populates="category", cascade="all, delete-orphan", lazy="dynamic")

    @classmethod
    def seed_defaults(cls, user) -> None:
        for name, ctype, icon, color in DEFAULT_CATEGORIES:
            db.session.add(cls(user_id=user.id, name=name, type=ctype, icon=icon, color=color, is_default=True))

    def __repr__(self) -> str:
        return f"<Category {self.type}:{self.name}>"


INCOME = "income"
EXPENSE = "expense"
TRANSACTION_TYPES = (INCOME, EXPENSE)


class Transaction(db.Model):
    __tablename__ = "transactions"
    __table_args__ = (
        Index("ix_transactions_user_date", "user_id", "date"),
        # One entry per schedule per date. NULL recurring_id (manual entries) never collides.
        Index("uq_transactions_recurring_date", "recurring_id", "date", unique=True),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    category_id: Mapped[int] = mapped_column(ForeignKey("categories.id", ondelete="RESTRICT"), index=True)
    name: Mapped[str] = mapped_column(String(100))
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    type: Mapped[str] = mapped_column(String(10))
    date: Mapped[date] = mapped_column(Date)
    description: Mapped[Optional[str]] = mapped_column(Text)
    wallet_id: Mapped[Optional[int]] = mapped_column(ForeignKey("wallets.id", ondelete="SET NULL"), index=True)
    recurring_id: Mapped[Optional[int]] = mapped_column(ForeignKey("recurring_rules.id", ondelete="SET NULL"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    user = relationship("User", back_populates="transactions")
    category = relationship("Category", back_populates="transactions")
    wallet = relationship("Wallet", back_populates="transactions")
    rule = relationship("RecurringRule", back_populates="transactions")

    @property
    def signed_amount(self) -> Decimal:
        return self.amount if self.type == INCOME else -self.amount

    @property
    def is_income(self) -> bool:
        return self.type == INCOME


WEEKLY = "weekly"
MONTHLY = "monthly"
BUDGET_PERIODS = (WEEKLY, MONTHLY)


class Budget(db.Model):
    __tablename__ = "budgets"
    __table_args__ = (UniqueConstraint("user_id", "category_id", "period", name="uq_budgets_user_category_period"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    category_id: Mapped[int] = mapped_column(ForeignKey("categories.id", ondelete="CASCADE"), index=True)
    limit_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    period: Mapped[str] = mapped_column(String(10), default=MONTHLY)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    user = relationship("User", back_populates="budgets")
    category = relationship("Category", back_populates="budgets")


GOAL_ICONS = ["target", "laptop", "smartphone", "plane", "graduation-cap", "shield", "gift", "bike", "house", "piggy-bank"]


class SavingsGoal(db.Model):
    __tablename__ = "savings_goals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(80))
    target_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    target_date: Mapped[Optional[date]] = mapped_column(Date)
    icon: Mapped[str] = mapped_column(String(40), default="target")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime)

    user = relationship("User", back_populates="goals")
    contributions = relationship(
        "SavingsContribution", back_populates="goal", cascade="all, delete-orphan",
        order_by="SavingsContribution.date.desc(), SavingsContribution.id.desc()",
    )

    @property
    def saved_amount(self) -> Decimal:
        return sum((c.amount for c in self.contributions), Decimal("0"))

    @property
    def remaining_amount(self) -> Decimal:
        return max(self.target_amount - self.saved_amount, Decimal("0"))

    @property
    def percent(self) -> float:
        if not self.target_amount:
            return 0.0
        return float(min(self.saved_amount / self.target_amount * 100, Decimal("100")))

    @property
    def is_complete(self) -> bool:
        return self.saved_amount >= self.target_amount


class SavingsContribution(db.Model):
    __tablename__ = "savings_contributions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    goal_id: Mapped[int] = mapped_column(ForeignKey("savings_goals.id", ondelete="CASCADE"), index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    date: Mapped[date] = mapped_column(Date)
    note: Mapped[Optional[str]] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    goal = relationship("SavingsGoal", back_populates="contributions")


LEVEL_ICONS = {"info": "info", "success": "party-popper", "warning": "triangle-alert", "danger": "octagon-alert"}


class Notification(db.Model):
    __tablename__ = "notifications"
    __table_args__ = (UniqueConstraint("user_id", "key", name="uq_notifications_user_key"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    key: Mapped[str] = mapped_column(String(120))
    kind: Mapped[str] = mapped_column(String(20), default="system")
    level: Mapped[str] = mapped_column(String(10), default="info")
    title: Mapped[str] = mapped_column(String(120))
    message: Mapped[str] = mapped_column(String(300))
    link: Mapped[Optional[str]] = mapped_column(String(200))
    is_read: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    dismissed: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)

    user = relationship("User", back_populates="notifications")

    @property
    def icon(self) -> str:
        return LEVEL_ICONS.get(self.level, "bell")


WALLET_TYPES = {
    "cash": ("Cash", "banknote", "#047857"),
    "gcash": ("GCash", "smartphone", "#2563EB"),
    "maya": ("Maya", "smartphone", "#059669"),
    "bank": ("Bank account", "landmark", "#0B1B3F"),
    "card": ("Prepaid card", "credit-card", "#7C3AED"),
    "other": ("Other", "wallet", "#64748B"),
}
# Name filled in automatically when a type is picked on the "Add a wallet" form.
WALLET_DEFAULT_NAMES = {"cash": "Cash", "gcash": "GCash", "maya": "Maya", "bank": "Bank Account",
                        "card": "Prepaid Card", "other": "Other"}
DEFAULT_WALLETS = [("Cash", "cash"), ("GCash", "gcash")]


class Wallet(db.Model):
    __tablename__ = "wallets"
    __table_args__ = (UniqueConstraint("user_id", "name", name="uq_wallets_user_name"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(40))
    type: Mapped[str] = mapped_column(String(10), default="cash")
    color: Mapped[str] = mapped_column(String(7), default="#047857")
    opening_balance: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0"))
    spendable: Mapped[bool] = mapped_column(Boolean, default=True)
    archived: Mapped[bool] = mapped_column(Boolean, default=False)
    position: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    user = relationship("User", back_populates="wallets")
    transactions = relationship("Transaction", back_populates="wallet", lazy="dynamic")

    @property
    def icon(self) -> str:
        return WALLET_TYPES.get(self.type, WALLET_TYPES["other"])[1]

    @property
    def type_label(self) -> str:
        return WALLET_TYPES.get(self.type, WALLET_TYPES["other"])[0]

    @classmethod
    def seed_defaults(cls, user) -> None:
        for i, (name, wtype) in enumerate(DEFAULT_WALLETS):
            db.session.add(cls(user_id=user.id, name=name, type=wtype, color=WALLET_TYPES[wtype][2],
                               opening_balance=Decimal("0"), position=i))


class WalletTransfer(db.Model):
    __tablename__ = "wallet_transfers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    from_wallet_id: Mapped[int] = mapped_column(ForeignKey("wallets.id", ondelete="CASCADE"), index=True)
    to_wallet_id: Mapped[int] = mapped_column(ForeignKey("wallets.id", ondelete="CASCADE"), index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    date: Mapped[date] = mapped_column(Date)
    note: Mapped[Optional[str]] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    from_wallet = relationship("Wallet", foreign_keys=[from_wallet_id])
    to_wallet = relationship("Wallet", foreign_keys=[to_wallet_id])


FREQUENCIES = {
    "daily": "Every day",
    "weekly": "Every week",
    "biweekly": "Every 2 weeks",
    "monthly": "Every month",
    "yearly": "Every year",
}


class RecurringRule(db.Model):
    __tablename__ = "recurring_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(100))
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    type: Mapped[str] = mapped_column(String(10))
    category_id: Mapped[int] = mapped_column(ForeignKey("categories.id", ondelete="CASCADE"), index=True)
    wallet_id: Mapped[Optional[int]] = mapped_column(ForeignKey("wallets.id", ondelete="SET NULL"))
    description: Mapped[Optional[str]] = mapped_column(Text)
    frequency: Mapped[str] = mapped_column(String(10))
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[Optional[date]] = mapped_column(Date)
    posted_count: Mapped[int] = mapped_column(Integer, default=0)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    user = relationship("User", back_populates="recurring")
    category = relationship("Category")
    wallet = relationship("Wallet")
    transactions = relationship("Transaction", back_populates="rule", lazy="dynamic")

    @property
    def frequency_label(self) -> str:
        return FREQUENCIES.get(self.frequency, self.frequency)

    @property
    def is_income(self) -> bool:
        return self.type == INCOME
