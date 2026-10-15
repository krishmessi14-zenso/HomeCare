import calendar as calendar_module
from datetime import date, datetime, time, timedelta

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from models import review as review_model
from models import service as service_model
from models import user as user_model
from models import notification as notification_model
from models.db import get_db
from utils.validators import oid_or_404, parse_float_or_none, parse_int, clean_text

bp = Blueprint("main", __name__)


@bp.route("/notifications")
@login_required
def notifications():
    items = notification_model.for_user(current_user.doc["_id"])
    return render_template("notifications.html", notifications=items)


@bp.route("/notifications/<notification_id>/read", methods=["POST"])
@login_required
def notification_read(notification_id):
    oid = oid_or_404(notification_id)
    if not notification_model.mark_read(oid, current_user.doc["_id"]):
        abort(404)
    flash("Notification marked as read.", "success")
    return redirect(url_for("main.notifications"))


@bp.route("/notifications/read-all", methods=["POST"])
@login_required
def notifications_read_all():
    notification_model.mark_all_read(current_user.doc["_id"])
    flash("All notifications marked as read.", "success")
    return redirect(url_for("main.notifications"))


@bp.route("/calendar")
@login_required
def calendar():
    today = date.today()
    try:
        year = int(request.args.get("year", today.year))
        month = int(request.args.get("month", today.month))
        first_day = date(year, month, 1)
    except (TypeError, ValueError):
        abort(404)

    last_day_number = calendar_module.monthrange(year, month)[1]
    next_month = first_day + timedelta(days=last_day_number)
    query = {"start_dt": {"$gte": datetime.combine(first_day, time.min),
                           "$lt": datetime.combine(next_month, time.min)}}
    if current_user.role == "customer":
        query["customer_id"] = current_user.doc["_id"]
    elif current_user.role == "provider":
        query["provider_id"] = current_user.doc["_id"]
    bookings = list(get_db().bookings.find(query).sort("start_dt", 1).limit(500))
    events_by_day = {}
    for booking in bookings:
        events_by_day.setdefault(booking["booking_date"], []).append(booking)

    weeks = []
    for week in calendar_module.monthcalendar(year, month):
        cells = []
        for day in week:
            key = date(year, month, day).isoformat() if day else None
            cells.append({"day": day, "key": key, "events": events_by_day.get(key, [])})
        weeks.append(cells)

    previous = first_day - timedelta(days=1)
    following = next_month
    return render_template("booking_calendar.html", weeks=weeks, month_label=first_day.strftime("%B %Y"),
                           year=year, month=month, previous=previous, following=following,
                           today=today.isoformat())


def _decorate_reviews(reviews):
    from models.db import get_db
    users = user_model.names_by_ids([r["customer_id"] for r in reviews])
    sids = {r.get("service_id") for r in reviews if r.get("service_id")}
    services = {s["_id"]: s for s in get_db().services.find({"_id": {"$in": list(sids)}})} if sids else {}
    for r in reviews:  # show first name only (privacy)
        r["customer_first_name"] = users.get(r["customer_id"], {}).get("name", "Customer").split()[0]
        r["service_name"] = services.get(r.get("service_id"), {}).get("name", "")
    return reviews


@bp.route("/")
def index():
    featured = service_model.search(limit=6, sort="name")
    return render_template("index.html", featured=featured, categories=service_model.category_counts())


@bp.route("/services")
def services():
    q = clean_text(request.args.get("q"))[:60]
    category = clean_text(request.args.get("category"))[:50]
    min_p, max_p = parse_float_or_none(request.args.get("min_price")), parse_float_or_none(request.args.get("max_price"))
    sort = request.args.get("sort", "name")
    per_page = 9
    total = service_model.count_search(q=q, category=category or None, min_price=min_p, max_price=max_p)
    total_pages = max(1, (total + per_page - 1) // per_page)
    page = min(parse_int(request.args.get("page"), 1, 100000) or 1, total_pages)
    items = service_model.search(q=q, category=category or None, min_price=min_p, max_price=max_p, sort=sort,
                                 limit=per_page, skip=(page - 1) * per_page)
    return render_template("services.html", services=items, categories=[c for c, _ in service_model.category_counts()],
                           q=q, category=category, min_price=request.args.get("min_price", ""),
                           max_price=request.args.get("max_price", ""), sort=sort, page=page,
                           total_pages=total_pages, total_services=total)


@bp.route("/services/<service_id>")
def service_detail(service_id):
    service = service_model.get_service(oid_or_404(service_id))
    if service is None or not service.get("is_active"):
        from flask import abort
        abort(404)
    reviews = _decorate_reviews(review_model.recent(10, service_id=service["_id"]))
    avg, n = review_model.rating_summary(service_id=service["_id"])
    return render_template("service_detail.html", service=service, reviews=reviews, avg=avg, n=n)


@bp.route("/reviews")
def reviews():
    items = _decorate_reviews(review_model.recent(50))
    avg, n = review_model.rating_summary()
    return render_template("reviews.html", reviews=items, avg=avg, n=n)
