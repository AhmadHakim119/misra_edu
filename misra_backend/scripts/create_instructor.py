"""Create or update a locally provisioned instructor account."""

from __future__ import annotations

import argparse
import getpass
import sys
from pathlib import Path

from dotenv import load_dotenv


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

load_dotenv(BACKEND_DIR / ".env")

from database import SessionLocal  # noqa: E402
from models import Institution, User  # noqa: E402
from services.auth_service import hash_password  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Provision a MISRA instructor login.")
    parser.add_argument("--institution-id", required=True)
    parser.add_argument("--email", required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument(
        "--role",
        choices=("teacher", "admin"),
        help="Role for a new account, or an explicit role change for an existing account.",
    )
    args = parser.parse_args()

    password = getpass.getpass("Password (10+ characters): ")
    confirmation = getpass.getpass("Confirm password: ")
    if password != confirmation:
        print("Passwords do not match.", file=sys.stderr)
        return 1

    try:
        encoded_password = hash_password(password)
    except ValueError as error:
        print(str(error), file=sys.stderr)
        return 1

    db = SessionLocal()
    try:
        institution = db.query(Institution).filter(Institution.id == args.institution_id).first()
        if not institution:
            print("Institution not found.", file=sys.stderr)
            return 1

        email = args.email.strip().lower()
        user = db.query(User).filter(User.institution_id == institution.id, User.email == email).first()
        if user:
            user.hashed_password = encoded_password
            user.full_name = args.name.strip()
            if args.role:
                user.role = args.role
            user.is_active = True
            user.must_change_password = False
            user.session_version = (user.session_version or 1) + 1
            action = "Updated"
        else:
            user = User(
                institution_id=institution.id,
                email=email,
                hashed_password=encoded_password,
                full_name=args.name.strip(),
                role=args.role or "teacher",
                is_active=True,
                must_change_password=False,
                session_version=1,
            )
            db.add(user)
            action = "Created"
        db.commit()
        db.refresh(user)
        print(f"{action} {user.role} {user.email} ({user.id}) for {institution.name}.")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
