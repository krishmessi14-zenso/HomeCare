from datetime import date, timedelta

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user

from models import booking as booking_model
from models import review as review_model
from models import service as service_model
from services import booking_service as bs
from utils.decorators import role_required
from utils.validators import clean_text, oid_or_404, parse_int

bp = Blueprint("customer", __name__, url_prefix="/customer")


def _cid():
    return current_user.doc["_id"]


@bp.route("/dashboard")
@role_required("customer")
def dashboard():
    bookings = booking_model.for_customer(_cid())
    reviewed = review_model.booking_ids_reviewed([b["_id"] for b in bookings])
    for b in bookings:
        b["can_cancel"] = bs.can_customer_cancel(b)
        b["can_review"] = b["status"] == "Completed" and b["_id"] not in reviewed
        b["reviewed"] = b["_id"] in reviewed
    active = [b for b in bookings if b["status"] in ("Pending", "Assigned", "Accepted", "In Progress")]
    return render_template("customer_dashboard.html", bookings=bookings, active_count=len(active))


@bp.route("/book/<service_id>", methods=["GET", "POST"])
@role_required("customer")
def book(service_id):
    service = service_model.get_service(oid_or_404(service_id))
    if service is None or not service.get("is_active"):
        abort(404)
    ctx = dict(service=service, slots=bs.TIME_SLOTS, today=date.today().isoformat(),
               max_date=(date.today() + timedelta(days=bs.MAX_DAYS_AHEAD)).isoformat(), form=request.form)
    if request.method == "POST":
        try:
            booking = bs.create_booking(_cid(), service, request.form.get("booking_date"), request.form.get("booking_time"),
                                        request.form.get("address"), request.form.get("notes"))
        except bs.BookingError as exc:
            flash(exc.message, "danger")
            return render_template("book_service.html", **ctx), exc.status_code
        flash("Booking request submitted. An administrator will assign a provider shortly.", "success")
        return redirect(url_for("customer.dashboard"))
    return render_template("book_service.html", **ctx)


@bp.route("/bookings/<booking_id>/cancel", methods=["POST"])
@role_required("customer")
def cancel(booking_id):
    try:
        bs.cancel_booking(oid_or_404(booking_id), "customer", customer_id=_cid())
        flash("Booking cancelled.", "info")
    except bs.BookingError as exc:
        if exc.status_code == 404:
            abort(404)
        flash(exc.message, "danger")
    return redirect(url_for("customer.dashboard"))


@bp.route("/bookings/<booking_id>/review", methods=["GET", "POST"])
@role_required("customer")
def review(booking_id):
    booking = booking_model.get_booking(oid_or_404(booking_id))
    if booking is None or booking["customer_id"] != _cid():
        abort(404)  # ownership check: never reveal other customers' bookings
    if request.method == "POST":
        rating = parse_int(request.form.get("rating"), 1, 5)
        try:
            review_model.create_review(booking, _cid(), rating, clean_text(request.form.get("comment"), multiline=True))
        except review_model.ReviewError as exc:
            flash(exc.message, "danger")
            return render_template("review_form.html", booking=booking), exc.status_code
        flash("Thank you! Your review has been submitted.", "success")
        return redirect(url_for("customer.dashboard"))
    if booking["status"] != "Completed":
        flash("Only completed bookings can be reviewed.", "warning")
        return redirect(url_for("customer.dashboard"))
    if booking["_id"] in review_model.booking_ids_reviewed([booking["_id"]]):
        flash("You have already reviewed this booking.", "info")
        return redirect(url_for("customer.dashboard"))
    return render_template("review_form.html", booking=booking)
