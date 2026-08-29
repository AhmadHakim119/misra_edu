"""Create or verify the current MISRA database schema.

For a new empty database, run with --create. For an existing database, the
script performs a read-only schema check and reports missing structures. It
never changes an existing database unless an explicit upgrade script is run.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from sqlalchemy import inspect
from sqlalchemy.exc import SQLAlchemyError


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from database import Base, engine  # noqa: E402
import models  # noqa: E402,F401


def schema_differences() -> tuple[list[str], dict[str, list[str]]]:
    inspector = inspect(engine)
    actual_tables = set(inspector.get_table_names())
    expected_tables = set(Base.metadata.tables)
    missing_tables = sorted(expected_tables - actual_tables)
    missing_columns: dict[str, list[str]] = {}

    for table_name in sorted(expected_tables & actual_tables):
        actual_columns = {column["name"] for column in inspector.get_columns(table_name)}
        expected_columns = set(Base.metadata.tables[table_name].columns.keys())
        missing = sorted(expected_columns - actual_columns)
        if missing:
            missing_columns[table_name] = missing

    return missing_tables, missing_columns


def main() -> int:
    parser = argparse.ArgumentParser(description="Create or verify the MISRA schema.")
    parser.add_argument(
        "--create",
        action="store_true",
        help="Create missing tables in a new database before verification.",
    )
    args = parser.parse_args()

    try:
        if args.create:
            Base.metadata.create_all(bind=engine)

        missing_tables, missing_columns = schema_differences()
    except SQLAlchemyError as exc:
        print(f"Database connection/schema check failed: {exc}", file=sys.stderr)
        return 1

    if not missing_tables and not missing_columns:
        print("Database connection successful. The current model schema is present.")
        return 0

    if missing_tables:
        print("Missing tables:")
        for table_name in missing_tables:
            print(f"  - {table_name}")

    if missing_columns:
        print("Missing columns:")
        for table_name, columns in missing_columns.items():
            print(f"  - {table_name}: {', '.join(columns)}")

    print(
        "Existing databases must run the relevant explicit upgrade script. "
        "Back up the database first."
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
