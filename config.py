"""Environment-based configuration. Fails loudly if required settings are missing."""
import os

from dotenv import load_dotenv

load_dotenv()

INSECURE_SECRETS = {"", "replace_with_a_secure_random_secret", "changeme", "secret", "dev"}


class ConfigError(RuntimeError):
    """Raised at startup when required configuration is missing or insecure."""


def _bool(name, default=False):
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


def load_config():
    missing = [k for k in ("MONGO_URI", "SECRET_KEY") if not os.getenv(k, "").strip()]
    if missing:
        raise ConfigError(
            "Missing required environment variable(s): " + ", ".join(missing) + ".\n"
            "Copy .env.example to .env and fill in real values (see README.md)."
        )
    secret = os.environ["SECRET_KEY"].strip()
    if secret in INSECURE_SECRETS or len(secret) < 16:
        raise ConfigError(
            "SECRET_KEY is a placeholder or too short (min 16 chars). Generate one with:\n"
            '  python -c "import secrets; print(secrets.token_hex(32))"'
        )
    return {
        "SECRET_KEY": secret,
        "MONGO_URI": os.environ["MONGO_URI"].strip(),
        "MONGO_DB_NAME": os.getenv("MONGO_DB_NAME", "homecare").strip() or "homecare",
        "SESSION_COOKIE_HTTPONLY": True,
        "SESSION_COOKIE_SAMESITE": "Lax",
        # Set COOKIE_SECURE=true when serving over HTTPS (production).
        "SESSION_COOKIE_SECURE": _bool("COOKIE_SECURE", False),
        "PERMANENT_SESSION_LIFETIME": 8 * 60 * 60,
        "MAX_CONTENT_LENGTH": 1024 * 1024,
        "WTF_CSRF_TIME_LIMIT": 3600,
        "LOGIN_MAX_ATTEMPTS": int(os.getenv("LOGIN_MAX_ATTEMPTS", "5")),
        "LOGIN_WINDOW_SECONDS": int(os.getenv("LOGIN_WINDOW_SECONDS", "900")),
        "CURRENCY_SYMBOL": os.getenv("CURRENCY_SYMBOL", "₹"),
    }
