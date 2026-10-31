from flask import Blueprint, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import select, update

from extensions import db
from models import Notification
from security import is_safe_redirect
import alerts
from utils import get_owned_or_404, today

notifications_bp = Blueprint("notifications", __name__, url_prefix="/notifications")


@notifications_bp.route("/")
@login_required
def index():
    alerts.refresh_all(current_user, today())
    show = request.args.get("show", "all")
    stmt = select(Notification).where(Notification.user_id == current_user.id, Notification.dismissed.is_(False))
    if show == "unread":
        stmt = stmt.where(Notification.is_read.is_(False))
    elif show in ("budget", "savings"):
        stmt = stmt.where(Notification.kind == show)
    items = db.session.scalars(stmt.order_by(Notification.created_at.desc(), Notification.id.desc()).limit(200)).all()
    return render_template("notifications/index.html", items=items, show=show)


@notifications_bp.route("/<int:nid>/open", methods=["POST"])
@login_required
def open_(nid):
    n = get_owned_or_404(Notification, nid)
    n.is_read = True
    db.session.commit()
    return redirect(n.link if is_safe_redirect(n.link) else url_for("notifications.index"))


@notifications_bp.route("/<int:nid>/toggle", methods=["POST"])
@login_required
def toggle(nid):
    n = get_owned_or_404(Notification, nid)
    n.is_read = not n.is_read
    db.session.commit()
    return redirect(url_for("notifications.index", show=request.form.get("show", "all")))


@notifications_bp.route("/read-all", methods=["POST"])
@login_required
def read_all():
    db.session.execute(update(Notification).where(Notification.user_id == current_user.id)
                       .values(is_read=True))
    db.session.commit()
    return redirect(url_for("notifications.index"))


@notifications_bp.route("/<int:nid>/delete", methods=["POST"])
@login_required
def delete_one(nid):
    n = get_owned_or_404(Notification, nid)
    n.dismissed = True
    n.is_read = True
    db.session.commit()
    return redirect(url_for("notifications.index", show=request.form.get("show", "all")))


@notifications_bp.route("/clear-read", methods=["POST"])
@login_required
def clear_read():
    db.session.execute(update(Notification).where(Notification.user_id == current_user.id,
                                                  Notification.is_read.is_(True)).values(dismissed=True))
    db.session.commit()
    return redirect(url_for("notifications.index"))
