"""Create the initial administrator interactively. The password is never stored in source,
never passed on the command line, and never echoed.

    python create_admin.py
"""
import argparse
import getpass
import sys

from pymongo.errors import PyMongoError

from app import create_app
from config import ConfigError
from models import user as user_model
from utils.validators import clean_text, normalize_email, password_errors, valid_email, valid_phone


def main():
    parser = argparse.ArgumentParser(description="Create a HomeCare administrator account.")
    parser.add_argument("--name"), parser.add_argument("--email"), parser.add_argument("--phone")
    args = parser.parse_args()
    try:
        app = create_app()
    except ConfigError as exc:
        sys.exit(f"CONFIGURATION ERROR:\n{exc}")
    except PyMongoError:
        sys.exit("DATABASE ERROR: could not connect to MongoDB. Check MONGO_URI and that MongoDB is running.")

    name = clean_text(args.name or input("Admin name: "))
    email = normalize_email(args.email or input("Admin email: "))
    phone = clean_text(args.phone or input("Admin phone: "))
    if not 2 <= len(name) <= 80 or not valid_email(email) or not valid_phone(phone):
        sys.exit("Invalid name, email or phone number.")
    password = getpass.getpass("Password (min 10 chars, letters + digits): ")
    if getpass.getpass("Confirm password: ") != password:
        sys.exit("Passwords do not match.")
    errors = password_errors(password) + (["Admin password must be at least 10 characters."] if len(password) < 10 else [])
    if errors:
        sys.exit("\n".join(errors))
    with app.app_context():
        try:
            user_model.create_user(name, email, phone, password, role="admin")
        except user_model.DuplicateEmailError:
            sys.exit("An account with that email already exists.")
    print(f"Administrator created: {email}")


if __name__ == "__main__":
    main()
