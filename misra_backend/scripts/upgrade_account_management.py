"""Add account-management fields and password reset storage to an existing database."""

from __future__ import annotations

import sys
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import inspect


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

load_dotenv(BACKEND_DIR / ".env")

from database import engine  # noqa: E402
from models import PasswordResetToken  # noqa: E402


USER_COLUMNS = {
    "is_active": "TINYINT(1) NOT NULL DEFAULT 1",
    "must_change_password": "TINYINT(1) NOT NULL DEFAULT 0",
    "session_version": "INT NOT NULL DEFAULT 1",
    "password_changed_at": "DATETIME NULL",
}


def main() -> int:
    if engine.dialect.name not in {"mysql", "mariadb"}:
        print("This upgrade script is intended for the MISRA MariaDB/MySQL database.", file=sys.stderr)
        return 1

    inspector = inspect(engine)
    if "users" not in inspector.get_table_names():
        print("The users table does not exist. Bootstrap the database first.", file=sys.stderr)
        return 1

    existing = {column["name"] for column in inspector.get_columns("users")}
    with engine.begin() as connection:
        for name, definition in USER_COLUMNS.items():
            if name not in existing:
                connection.exec_driver_sql(f"ALTER TABLE users ADD COLUMN {name} {definition}")
                print(f"Added users.{name}")

    PasswordResetToken.__table__.create(bind=engine, checkfirst=True)
    print("Account-management schema is ready.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
