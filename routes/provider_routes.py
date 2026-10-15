from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user

from models import booking as booking_model
from models import review as review_model
from models import user as user_model
from routes.main_routes import _decorate_reviews
from services import booking_service as bs
from utils.decorators import role_required
from utils.validators import oid_or_404

bp = Blueprint("provider", __name__, url_prefix="/provider")
WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")


def _pid():
    return current_user.doc["_id"]


@bp.route("/dashboard")
@role_required("provider")
def dashboard():
    availability = user_model.provider_availability(current_user.doc)
    if not current_user.is_approved_provider:
        return render_template("provider_dashboard.html", approved=False, jobs=[], tab="active",
                               availability=availability, weekdays=WEEKDAYS)
    tab = "history" if request.args.get("tab") == "history" else "active"
    statuses = booking_model.HISTORY_STATUSES if tab == "history" else booking_model.ACTIVE_JOB_STATUSES
    jobs = booking_model.for_provider(_pid(), statuses, ascending=(tab == "active"))
    customers = user_model.names_by_ids([j["customer_id"] for j in jobs])
    for j in jobs:
        c = customers.get(j["customer_id"], {})
        j["customer_name"] = c.get("name", "Customer")
        # phone is only shared once the provider has accepted the job
        j["customer_phone"] = c.get("phone") if j["status"] in ("Accepted", "In Progress", "Completed") else None
    avg, n = review_model.rating_summary(provider_id=_pid())
    return render_template("provider_dashboard.html", approved=True, jobs=jobs, tab=tab, avg=avg, n=n,
                           availability=availability, weekdays=WEEKDAYS)


@bp.route("/availability", methods=["POST"])
@role_required("provider")
def update_availability():
    try:
        updated = user_model.save_provider_availability(_pid(), request.form.getlist("days"),
                                                        request.form.get("start_time", ""),
                                                        request.form.get("end_time", ""))
    except ValueError as exc:
        flash(str(exc), "danger")
    else:
        flash("Availability updated." if updated else
              "Availability cannot be changed because it conflicts with an assigned job.",
              "success" if updated else "danger")
    return redirect(url_for("provider.dashboard"))


@bp.route("/jobs/<booking_id>/<action>", methods=["POST"])
@role_required("provider")
def job_action(booking_id, action):
    try:
        bs.provider_action(oid_or_404(booking_id), current_user, action)
        flash({"accept": "Job accepted.", "reject": "Job rejected.", "start": "Job marked In Progress.",
               "complete": "Job marked Completed."}[action], "success")
    except bs.BookingError as exc:
        if exc.status_code == 404:
            abort(404)
        flash(exc.message, "danger")
    return redirect(url_for("provider.dashboard"))


@bp.route("/reviews")
@role_required("provider")
def reviews():
    items = _decorate_reviews(review_model.recent(100, provider_id=_pid()))
    avg, n = review_model.rating_summary(provider_id=_pid())
    return render_template("provider_reviews.html", reviews=items, avg=avg, n=n)
