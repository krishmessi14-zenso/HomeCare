"""Input validation / normalisation helpers."""
import math
import re

from bson import ObjectId
from bson.errors import InvalidId
from flask import abort

EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]+\.[^@\s]{2,}$")
PHONE_RE = re.compile(r"^\+?[0-9][0-9\s\-]{6,18}[0-9]$")
CTRL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def to_object_id(value):
    """Return an ObjectId or None. Never raises."""
    if isinstance(value, ObjectId):
        return value
    if not isinstance(value, str) or len(value) != 24:
        return None
    try:
        return ObjectId(value)
    except (InvalidId, TypeError):
        return None


def oid_or_404(value):
    oid = to_object_id(value)
    if oid is None:
        abort(404)
    return oid


def clean_text(value, multiline=False):
    value = CTRL_RE.sub("", value or "").strip()
    if not multiline:
        value = re.sub(r"\s+", " ", value)
    return value


def normalize_email(email):
    return (email or "").strip().lower()


def valid_email(email):
    return bool(email) and len(email) <= 120 and bool(EMAIL_RE.match(email))


def valid_phone(phone):
    return bool(PHONE_RE.match(phone or ""))


def password_errors(pw):
    errs = []
    if not pw or len(pw) < 8:
        errs.append("Password must be at least 8 characters.")
    elif len(pw) > 128:
        errs.append("Password must be at most 128 characters.")
    elif not (re.search(r"[A-Za-z]", pw) and re.search(r"\d", pw)):
        errs.append("Password must contain at least one letter and one digit.")
    return errs


def parse_price(value):
    try:
        p = float(str(value).strip())
    except (TypeError, ValueError):
        return None
    if not math.isfinite(p) or p <= 0 or p > 1_000_000:
        return None
    return round(p, 2)


def parse_int(value, lo, hi):
    try:
        n = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    return n if lo <= n <= hi else None


def parse_float_or_none(value):
    try:
        f = float(str(value).strip())
        return f if math.isfinite(f) else None
    except (TypeError, ValueError):
        return None
