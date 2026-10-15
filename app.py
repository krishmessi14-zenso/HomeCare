"""HomeCare - House Service Management Portal (Flask + MongoDB).

Run:      python app.py
Gunicorn: gunicorn "app:create_app()"
"""
import os
import sys

from flask import Flask, render_template, request
from flask_login import LoginManager, current_user
from flask_wtf.csrf import CSRFError, CSRFProtect
from pymongo.errors import PyMongoError

from config import ConfigError, load_config
from models import user as user_model
from models.db import init_db
from utils.helpers import pretty_date, pretty_dt
from utils.security import RateLimiter
from utils.validators import to_object_id

csrf = CSRFProtect()
login_manager = LoginManager()
login_manager.login_view = "auth.login"
login_manager.login_message = "Please log in to continue."
login_manager.login_message_category = "warning"
login_manager.session_protection = "strong"

ERRORS = {
    400: ("Bad request", "The request could not be understood. Please go back and try again."),
    403: ("Access denied", "You do not have permission to view this page."),
    404: ("Page not found", "The page or record you are looking for does not exist."),
    405: ("Method not allowed", "That action is not allowed on this page."),
    500: ("Something went wrong", "An unexpected error occurred. Please try again later."),
}


def create_app(test_config=None):
    app = Flask(__name__)
    if test_config is None:
        app.config.update(load_config())
        init_db(app)
    else:  # tests inject a mongomock database via MONGO_DB
        app.config.update({"CURRENCY_SYMBOL": "₹", "LOGIN_MAX_ATTEMPTS": 5, "LOGIN_WINDOW_SECONDS": 900,
                           "SESSION_COOKIE_HTTPONLY": True, "SESSION_COOKIE_SAMESITE": "Lax"})
        app.config.update(test_config)
        init_db(app, db=test_config["MONGO_DB"])

    app.extensions["login_limiter"] = RateLimiter(app.config["LOGIN_MAX_ATTEMPTS"], app.config["LOGIN_WINDOW_SECONDS"])
    csrf.init_app(app)
    login_manager.init_app(app)

    @login_manager.user_loader
    def load_user(user_id):
        oid = to_object_id(user_id)
        doc = user_model.find_by_id(oid) if oid else None
        return user_model.User(doc) if doc and doc.get("active") else None

    from routes.admin_routes import bp as admin_bp
    from routes.auth_routes import bp as auth_bp
    from routes.customer_routes import bp as customer_bp
    from routes.main_routes import bp as main_bp
    from routes.provider_routes import bp as provider_bp
    for bp in (main_bp, auth_bp, customer_bp, provider_bp, admin_bp):
        app.register_blueprint(bp)

    @app.context_processor
    def inject_globals():
        from datetime import datetime
        from models import notification as notification_model
        unread_count = notification_model.unread_count(current_user.doc["_id"]) if current_user.is_authenticated else 0
        return {"now_year": datetime.now().year, "unread_notification_count": unread_count}

    app.jinja_env.filters["pretty_date"] = pretty_date
    app.jinja_env.filters["pretty_dt"] = pretty_dt
    app.jinja_env.filters["money"] = lambda v: f"{app.config['CURRENCY_SYMBOL']}{v:,.2f}"

    @app.after_request
    def security_headers(resp):
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("X-Frame-Options", "DENY")
        resp.headers.setdefault("Referrer-Policy", "same-origin")
        resp.headers.setdefault("Content-Security-Policy",
                                "default-src 'self'; img-src 'self' data:; frame-ancestors 'none'; form-action 'self'")
        if request.endpoint != "static" and request.method == "GET":
            resp.headers.setdefault("Cache-Control", "no-store")
        return resp

    def render_error(code, status=None):
        title, message = ERRORS[code]
        return render_template("error.html", code=code, title=title, message=message), status or code

    for code in ERRORS:
        app.register_error_handler(code, lambda e, c=code: render_error(c))

    @app.errorhandler(CSRFError)
    def csrf_error(e):
        title, _ = ERRORS[400]
        return render_template("error.html", code=400, title=title,
                               message="Your session expired or the form was invalid. Please reload the page and try again."), 400

    @app.errorhandler(PyMongoError)
    def db_error(e):
        app.logger.exception("Database error")  # details go to the log only, never to the user
        return render_error(500)

    @app.errorhandler(Exception)
    def unhandled(e):
        from werkzeug.exceptions import HTTPException
        if isinstance(e, HTTPException):
            return render_error(e.code) if e.code in ERRORS else (e.get_response())
        app.logger.exception("Unhandled error")
        return render_error(500)

    return app


if __name__ == "__main__":
    try:
        application = create_app()
    except ConfigError as exc:
        print(f"\nCONFIGURATION ERROR:\n{exc}\n", file=sys.stderr)
        sys.exit(1)
    except PyMongoError:
        print("\nDATABASE ERROR: could not connect to MongoDB. Check MONGO_URI, that MongoDB is running "
              "(or your Atlas IP allow-list / credentials) and try again.\n", file=sys.stderr)
        sys.exit(1)
    # Debug mode is intentionally never enabled.
    application.run(host=os.getenv("HOST", "127.0.0.1"), port=int(os.getenv("PORT", "5000")), debug=False)
