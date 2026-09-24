"""Add structured instructor review reasons to an existing MISRA database.

Back up the database first, then run this script once from ``misra_backend``.
The upgrade is additive and idempotent; existing review labels remain valid.
"""

from __future__ import annotations

import sys
from pathlib import Path

from sqlalchemy import inspect, text


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from database import engine  # noqa: E402


def main() -> int:
    inspector = inspect(engine)
    columns = {column["name"] for column in inspector.get_columns("review_labels")}
    statements = []
    if "review_reason_codes" not in columns:
        statements.append(
            "ALTER TABLE review_labels ADD COLUMN review_reason_codes JSON NULL"
        )
    if "review_reason_note" not in columns:
        statements.append(
            "ALTER TABLE review_labels ADD COLUMN review_reason_note TEXT NULL"
        )
    if "supersedes_label_id" not in columns:
        statements.append(
            "ALTER TABLE review_labels ADD COLUMN supersedes_label_id CHAR(36) NULL"
        )

    indexes = {index["name"]: index for index in inspector.get_indexes("review_labels")}
    # MariaDB may use the existing unique grading-run index to support the
    # foreign key. Create its non-unique replacement before dropping the
    # uniqueness constraint, otherwise error 1553 is raised.
    if "ix_review_labels_grading_run_id" not in indexes:
        statements.append(
            "CREATE INDEX ix_review_labels_grading_run_id ON review_labels (grading_run_id)"
        )
    if "uq_review_labels_grading_run_id" in indexes:
        statements.append(
            "ALTER TABLE review_labels DROP INDEX uq_review_labels_grading_run_id"
        )
    if "ix_review_labels_supersedes_label_id" not in indexes:
        statements.append(
            "CREATE INDEX ix_review_labels_supersedes_label_id "
            "ON review_labels (supersedes_label_id)"
        )

    foreign_keys = {
        foreign_key.get("name")
        for foreign_key in inspector.get_foreign_keys("review_labels")
    }
    if "fk_review_labels_supersedes" not in foreign_keys:
        statements.append(
            "ALTER TABLE review_labels ADD CONSTRAINT fk_review_labels_supersedes "
            "FOREIGN KEY (supersedes_label_id) REFERENCES review_labels (id) "
            "ON DELETE SET NULL"
        )

    with engine.begin() as connection:
        for statement in statements:
            connection.execute(text(statement))

    upgraded = {column["name"] for column in inspect(engine).get_columns("review_labels")}
    required = {"review_reason_codes", "review_reason_note", "supersedes_label_id"}
    if not required.issubset(upgraded):
        print("Review-reason schema verification failed.", file=sys.stderr)
        return 1
    print(
        "Structured review reasons and immutable review revisions are ready. "
        "Existing labels were not changed."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
