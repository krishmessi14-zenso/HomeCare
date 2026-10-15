from flask import Blueprint, abort, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user

from models import booking as booking_model
from models import review as review_model
from models import service as service_model
from models import user as user_model
from models.db import BOOKING_STATUSES, get_db
from routes.main_routes import _decorate_reviews
from services import booking_service as bs
from services import report_service
from utils.decorators import role_required
from utils.uploads import delete_service_image, save_service_image
from utils.validators import (clean_text, normalize_email, oid_or_404, password_errors, valid_email, valid_phone)

bp = Blueprint("admin", __name__, url_prefix="/admin")
admin_only = role_required("admin")


@bp.route("/dashboard")
@admin_only
def dashboard():
    recent = booking_model.list_all(limit=8)
    return render_template("admin_dashboard.html", stats=report_service.dashboard_stats(), recent=recent)


# ------------------------------------------------------------ services
@bp.route("/services")
@admin_only
def services():
    return render_template("admin_services.html", services=service_model.search(active_only=False, limit=500))


@bp.route("/services/new", methods=["GET", "POST"])
@admin_only
def service_new():
    if request.method == "POST":
        data, errors = service_model.parse_service_form(request.form)
        upload = request.files.get("image_file")
        saved_image = None
        if upload and upload.filename and not errors:
            try:
                saved_image = save_service_image(upload, current_app.static_folder)
                data["image"] = saved_image
            except ValueError as exc:
                errors.append(str(exc))
        if not errors:
            try:
                service_model.create_service(data)
                flash("Service created.", "success")
                return redirect(url_for("admin.services"))
            except service_model.DuplicateServiceError:
                if saved_image:
                    delete_service_image(saved_image, current_app.static_folder)
                errors.append("A service with this name already exists.")
        for e in errors:
            flash(e, "danger")
        return render_template("admin_service_form.html", service=None, form=request.form,
                               categories=service_model.DEFAULT_CATEGORIES), 400
    return render_template("admin_service_form.html", service=None, form={"is_active": "on"},
                           categories=service_model.DEFAULT_CATEGORIES)


@bp.route("/services/<service_id>/edit", methods=["GET", "POST"])
@admin_only
def service_edit(service_id):
    oid = oid_or_404(service_id)
    service = service_model.get_service(oid)
    if service is None:
        abort(404)
    if request.method == "POST":
        data, errors = service_model.parse_service_form(request.form)
        upload = request.files.get("image_file")
        saved_image = None
        if upload and upload.filename and not errors:
            try:
                saved_image = save_service_image(upload, current_app.static_folder)
                data["image"] = saved_image
            except ValueError as exc:
                errors.append(str(exc))
        if not errors:
            try:
                service_model.update_service(oid, data)
                if saved_image and service.get("image") != saved_image:
                    delete_service_image(service.get("image"), current_app.static_folder)
                flash("Service updated.", "success")
                return redirect(url_for("admin.services"))
            except service_model.DuplicateServiceError:
                if saved_image:
                    delete_service_image(saved_image, current_app.static_folder)
                errors.append("A service with this name already exists.")
        for e in errors:
            flash(e, "danger")
        return render_template("admin_service_form.html", service=service, form=request.form,
                               categories=service_model.DEFAULT_CATEGORIES), 400
    form = {**service, "is_active": "on" if service["is_active"] else ""}
    return render_template("admin_service_form.html", service=service, form=form, categories=service_model.DEFAULT_CATEGORIES)


@bp.route("/services/<service_id>/toggle", methods=["POST"])
@admin_only
def service_toggle(service_id):
    oid = oid_or_404(service_id)
    service = service_model.get_service(oid)
    if service is None:
        abort(404)
    service_model.set_active(oid, not service["is_active"])
    flash(f"Service {'deactivated' if service['is_active'] else 'activated'}.", "success")
    return redirect(url_for("admin.services"))


# ------------------------------------------------------------ users
@bp.route("/users")
@admin_only
def users():
    providers = user_model.list_by_role("provider")
    busy = {r["_id"]: r["n"] for r in get_db().bookings.aggregate([
        {"$match": {"status": {"$in": ["Accepted", "In Progress"]}}}, {"$group": {"_id": "$provider_id", "n": {"$sum": 1}}}])}
    for p in providers:
        p["busy_jobs"] = busy.get(p["_id"], 0)
    return render_template("admin_users.html", customers=user_model.list_by_role("customer"), providers=providers)


def _parse_provider_form(form, require_password):
    name, phone = clean_text(form.get("name")), clean_text(form.get("phone"))
    email, password = normalize_email(form.get("email")), form.get("password", "")
    errors = []
    if not 2 <= len(name) <= 80:
        errors.append("Name must be 2-80 characters.")
    if not valid_email(email):
        errors.append("Please enter a valid email address.")
    if not valid_phone(phone):
        errors.append("Please enter a valid phone number.")
    if require_password or password:
        errors += password_errors(password)
    return {"name": name, "phone": phone, "email": email, "password": password}, errors


@bp.route("/providers/new", methods=["GET", "POST"])
@admin_only
def provider_new():
    if request.method == "POST":
        data, errors = _parse_provider_form(request.form, True)
        if not errors:
            try:
                approved = request.form.get("approved") == "on"
                user_model.create_user(data["name"], data["email"], data["phone"], data["password"], role="provider",
                                       approved=approved, approved_by=current_user.doc["_id"])
                flash("Provider account created" + (" and approved." if approved else " (awaiting approval)."), "success")
                return redirect(url_for("admin.users"))
            except user_model.DuplicateEmailError:
                errors.append("An account with this email already exists.")
        for e in errors:
            flash(e, "danger")
        return render_template("admin_provider_form.html", provider=None, form=request.form), 400
    return render_template("admin_provider_form.html", provider=None, form={"approved": "on"})


@bp.route("/providers/<user_id>/edit", methods=["GET", "POST"])
@admin_only
def provider_edit(user_id):
    oid = oid_or_404(user_id)
    provider = user_model.find_by_id(oid, role="provider")
    if provider is None:
        abort(404)
    if request.method == "POST":
        data, errors = _parse_provider_form(request.form, False)
        if not errors:
            fields = {"name": data["name"], "phone": data["phone"], "email": data["email"]}
            if data["password"]:
                from werkzeug.security import generate_password_hash
                fields["password_hash"] = generate_password_hash(data["password"])
            try:
                user_model.update_user(oid, "provider", fields)
                flash("Provider updated.", "success")
                return redirect(url_for("admin.users"))
            except user_model.DuplicateEmailError:
                errors.append("Another account already uses this email.")
        for e in errors:
            flash(e, "danger")
        return render_template("admin_provider_form.html", provider=provider, form=request.form), 400
    return render_template("admin_provider_form.html", provider=provider, form=provider)


@bp.route("/providers/<user_id>/approve", methods=["POST"])
@admin_only
def provider_approve(user_id):
    if not user_model.approve_provider(oid_or_404(user_id), current_user.doc["_id"]):
        abort(404)
    flash("Provider approved.", "success")
    return redirect(url_for("admin.users"))


@bp.route("/users/<user_id>/toggle", methods=["POST"])
@admin_only
def user_toggle(user_id):
    oid = oid_or_404(user_id)
    user = user_model.find_by_id(oid)
    if user is None or user["role"] not in ("customer", "provider"):  # admins cannot be toggled here
        abort(404)
    if user["active"] and user["role"] == "provider":
        if get_db().bookings.count_documents({"provider_id": oid, "status": {"$in": ["Accepted", "In Progress"]}}):
            flash("This provider has accepted/in-progress jobs. Finish or cancel them before deactivating.", "danger")
            return redirect(url_for("admin.users"))
    user_model.set_active(oid, user["role"], not user["active"])
    flash(f"{user['name']} {'deactivated' if user['active'] else 'activated'}.", "success")
    return redirect(url_for("admin.users"))


# ------------------------------------------------------------ bookings
@bp.route("/bookings")
@admin_only
def bookings():
    status = request.args.get("status", "")
    items = booking_model.list_all(status=status or None)
    users = user_model.names_by_ids([i for b in items for i in (b["customer_id"], b.get("provider_id"))])
    for b in items:
        b["customer_name"] = users.get(b["customer_id"], {}).get("name", "?")
        b["provider_name"] = users.get(b.get("provider_id"), {}).get("name") if b.get("provider_id") else None
        b["assignable"] = b["status"] in bs.ASSIGNABLE_FROM
        b["cancellable"] = b["status"] in bs.CANCELLABLE_FROM
        b["available_providers"] = ([p for p in bs.available_providers_for(b) if p["_id"] != b.get("provider_id")]
                                    if b["assignable"] else [])
    return render_template("admin_bookings.html", bookings=items, statuses=BOOKING_STATUSES, status=status)


@bp.route("/bookings/<booking_id>/assign", methods=["POST"])
@admin_only
def assign(booking_id):
    provider_id = oid_or_404(request.form.get("provider_id", ""))
    try:
        bs.assign_provider(oid_or_404(booking_id), provider_id)
        flash("Provider assigned.", "success")
    except bs.BookingError as exc:
        flash(exc.message, "danger")
    return redirect(url_for("admin.bookings"))


@bp.route("/bookings/<booking_id>/cancel", methods=["POST"])
@admin_only
def cancel(booking_id):
    try:
        bs.cancel_booking(oid_or_404(booking_id), "admin")
        flash("Booking cancelled.", "info")
    except bs.BookingError as exc:
        flash(exc.message, "danger")
    return redirect(url_for("admin.bookings"))


# ------------------------------------------------------------ reviews & reports
@bp.route("/reviews")
@admin_only
def reviews():
    items = _decorate_reviews(review_model.recent(200))
    providers = user_model.names_by_ids([r["provider_id"] for r in items])
    for r in items:
        r["provider_name"] = providers.get(r["provider_id"], {}).get("name", "?")
    avg, n = review_model.rating_summary()
    return render_template("admin_reviews.html", reviews=items, avg=avg, n=n)


@bp.route("/reports")
@admin_only
def reports():
    return render_template("admin_reports.html", r=report_service.reports(), statuses=BOOKING_STATUSES)
