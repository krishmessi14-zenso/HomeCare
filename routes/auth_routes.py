from flask import Blueprint, current_app, flash, redirect, render_template, request, session, url_for
from flask_login import current_user, login_required, login_user, logout_user
from werkzeug.security import check_password_hash, generate_password_hash

from models import user as user_model
from utils.helpers import dashboard_url
from utils.security import is_safe_redirect
from utils.validators import (clean_text, normalize_email, password_errors, valid_email, valid_phone)

bp = Blueprint("auth", __name__)
_DUMMY_HASH = generate_password_hash("not-a-real-password")  # equalises timing for unknown emails


@bp.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(dashboard_url(current_user.role))
    form = request.form
    if request.method == "POST":
        name, phone = clean_text(form.get("name")), clean_text(form.get("phone"))
        email = normalize_email(form.get("email"))
        password, confirm = form.get("password", ""), form.get("confirm_password", "")
        errors = []
        if not 2 <= len(name) <= 80:
            errors.append("Name must be 2-80 characters.")
        if not valid_email(email):
            errors.append("Please enter a valid email address.")
        if not valid_phone(phone):
            errors.append("Please enter a valid phone number (7-20 digits, optional leading +).")
        errors += password_errors(password)
        if password != confirm:
            errors.append("Passwords do not match.")
        if not errors:
            try:  # role is ALWAYS customer here; any posted 'role' field is ignored
                user_model.create_user(name, email, phone, password, role="customer")
                flash("Registration successful. Please log in.", "success")
                return redirect(url_for("auth.login"))
            except user_model.DuplicateEmailError:
                errors.append("An account with this email already exists.")
        for e in errors:
            flash(e, "danger")
        return render_template("register.html", form=form), 400
    return render_template("register.html", form=form)


@bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(dashboard_url(current_user.role))
    nxt = request.args.get("next", "")
    if request.method == "POST":
        email = normalize_email(request.form.get("email"))
        password = request.form.get("password", "")
        limiter = current_app.extensions["login_limiter"]
        keys = [f"{request.remote_addr}|{email}", f"ip|{request.remote_addr}"]
        if limiter.is_blocked(keys[0]) or limiter.is_blocked(keys[1]) :
            flash("Too many failed login attempts. Please wait several minutes and try again.", "danger")
            return render_template("login.html", next=nxt), 429
        doc = user_model.find_by_email(email) if valid_email(email) else None
        if doc is None:
            check_password_hash(_DUMMY_HASH, password)
        if doc is None or not user_model.verify_password(doc, password):
            for k in keys:
                limiter.record_failure(k)
            flash("Invalid email or password.", "danger")
            return render_template("login.html", next=nxt), 401
        if not doc.get("active"):
            flash("This account is disabled. Please contact the administrator.", "danger")
            return render_template("login.html", next=nxt), 403
        limiter.reset(keys[0])
        session.clear()  # avoid session fixation
        login_user(user_model.User(doc))
        session.permanent = True
        target = request.form.get("next") or nxt
        if is_safe_redirect(target):
            return redirect(target)
        return redirect(dashboard_url(doc["role"]))
    return render_template("login.html", next=nxt)


@bp.route("/logout", methods=["POST"])
@login_required
def logout():
    logout_user()
    session.clear()
    flash("You have been logged out.", "info")
    return redirect(url_for("main.index"))
