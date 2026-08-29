"""Add durable RQ processing jobs to an existing MISRA database.

Back up the database first, then run this script once from ``misra_backend``.
It is idempotent and verifies the two new schema structures afterwards.
"""

from __future__ import annotations

import sys
from pathlib import Path

from sqlalchemy import inspect, text


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from database import engine  # noqa: E402
from models import ProcessingJob  # noqa: E402


def main() -> int:
    ProcessingJob.__table__.create(bind=engine, checkfirst=True)
    inspector = inspect(engine)
    grading_columns = {column["name"] for column in inspector.get_columns("grading_runs")}

    with engine.begin() as connection:
        if "processing_job_id" not in grading_columns:
            connection.execute(
                text(
                    "ALTER TABLE grading_runs "
                    "ADD COLUMN processing_job_id CHAR(36) NULL, "
                    "ADD INDEX ix_grading_runs_processing_job_id (processing_job_id), "
                    "ADD CONSTRAINT fk_grading_runs_processing_job "
                    "FOREIGN KEY (processing_job_id) REFERENCES processing_jobs(id) "
                    "ON DELETE SET NULL"
                )
            )

    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    columns = {column["name"] for column in inspector.get_columns("grading_runs")}
    if "processing_jobs" not in tables or "processing_job_id" not in columns:
        print("Processing-job schema verification failed.", file=sys.stderr)
        return 1
    print("Processing-job schema is ready.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
