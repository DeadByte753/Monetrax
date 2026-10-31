from flask import Blueprint, current_app, flash, redirect, render_template, request, session, url_for
from flask_login import current_user, login_required, login_user, logout_user

from models import EmailAlreadyRegistered, User, burn_password_check
import throttle
from security import is_safe_redirect
from validators import (email_error, normalize_email, normalize_name,
                          validate_login, validate_registration)

auth_bp = Blueprint("auth", __name__)


def _after_login_target() -> str:
    nxt = request.form.get("next") or request.args.get("next")
    return nxt if is_safe_redirect(nxt) else url_for("dashboard.index")


def _start_session(user, remember: bool) -> None:
    """Sign in on a fresh session so nothing from before login (a planted session) carries over."""
    session.clear()
    login_user(user, remember=remember)
    user.record_login()


@auth_bp.route("/")
def root():
    return redirect(url_for("dashboard.index" if current_user.is_authenticated else "auth.login"))


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard.index"))

    form = {"email": normalize_email(request.args.get("email")), "remember": True}
    errors = {}

    if request.method == "POST":
        email = normalize_email(request.form.get("email"))
        password = request.form.get("password", "")
        remember = request.form.get("remember") == "on"
        form = {"email": email, "remember": remember}

        errors = validate_login(email, password)
        status = 400
        if not errors:
            keys = (throttle.key("email", email), throttle.key("ip", throttle.client_ip()))
            wait = throttle.retry_after(*keys)
            if wait:
                # Locked: don't even check the password, so a lockout can't be used to keep guessing.
                errors["form"] = throttle.wait_message(wait)
                status = 429
            else:
                user = User.get_by_email(email)
                if user is None:
                    burn_password_check(password)
                elif user.check_password(password):
                    throttle.clear(keys[0])
                    throttle.prune()
                    _start_session(user, remember)
                    return redirect(_after_login_target())
                throttle.record_failure(*keys)
                errors["form"] = "Incorrect email or password. Please try again."

        resp = render_template("auth/login.html", form=form, errors=errors, next=request.form.get("next", ""))
        return (resp, status, {"Retry-After": "900"}) if status == 429 else (resp, status)

    return render_template("auth/login.html", form=form, errors=errors, next=request.args.get("next", ""))


@auth_bp.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard.index"))

    require_school = current_app.config["REQUIRE_SCHOOL_EMAIL"]
    form = {"full_name": "", "email": "", "terms": False}
    errors = {}

    if request.method == "POST":
        full_name = normalize_name(request.form.get("full_name"))
        email = normalize_email(request.form.get("email"))
        password = request.form.get("password", "")
        confirm = request.form.get("confirm_password", "")
        terms = request.form.get("terms") == "on"
        form = {"full_name": full_name, "email": email, "terms": terms}

        errors = validate_registration(full_name, email, password, confirm, terms, require_school)
        reg_key = throttle.key("register", throttle.client_ip())
        if not errors and (wait := throttle.retry_after(reg_key)):
            errors["form"] = throttle.wait_message(wait)
        if not errors and User.email_exists(email):
            errors["email"] = "An account with this email already exists. Try signing in instead."

        if not errors:
            try:
                user = User.create(full_name, email, password)
            except EmailAlreadyRegistered:
                errors["email"] = "An account with this email already exists. Try signing in instead."
            else:
                throttle.record_failure(reg_key)
                _start_session(user, False)
                flash(f"Welcome to Monetrax, {user.first_name}! Start by adding your allowance.", "success")
                return redirect(url_for("dashboard.index"))

        return render_template("auth/register.html", form=form, errors=errors, require_school=require_school), 400

    return render_template("auth/register.html", form=form, errors=errors, require_school=require_school)


@auth_bp.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard.index"))

    form = {"email": normalize_email(request.args.get("email"))}
    errors = {}
    if request.method == "POST":
        email = normalize_email(request.form.get("email"))
        form = {"email": email}
        if msg := email_error(email):
            errors["email"] = msg
            return render_template("auth/forgot.html", form=form, errors=errors), 400
        flash("Password reset by email isn't switched on for this server yet. "
              "Please contact your Monetrax administrator to recover your account.", "info")
        return redirect(url_for("auth.forgot_password", email=email))

    return render_template("auth/forgot.html", form=form, errors=errors)


@auth_bp.route("/logout", methods=["POST"])
@login_required
def logout():
    session.clear()  # before logout_user(), which leaves the flag that deletes the "remember me" cookie
    logout_user()
    flash("You've been signed out. See you soon!", "success")
    return redirect(url_for("auth.login"))
