from datetime import datetime

from flask import url_for


def dashboard_url(role):
    return url_for({"customer": "customer.dashboard",
                    "provider": "provider.dashboard",
                    "admin": "admin.dashboard"}.get(role, "main.index"))


def pretty_date(value):
    try:
        return datetime.strptime(value, "%Y-%m-%d").strftime("%a, %d %b %Y")
    except (TypeError, ValueError):
        return value or ""


def pretty_dt(value):
    return value.strftime("%d %b %Y %H:%M") if value else ""
