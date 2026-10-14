"""Explicit additive upgrade. Back up the database before executing this script."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import inspect, text
from database import engine
from services.course_material_service import MATERIAL_TABLES


def upgrade(target_engine):
    inspector = inspect(target_engine)
    if not inspector.has_table("processing_jobs"):
        raise RuntimeError("Run the existing processing-job/foundation upgrades first.")
    if target_engine.dialect.name in {"mysql", "mariadb"}:
        job_type = next(c["type"] for c in inspector.get_columns("processing_jobs") if c["name"] == "job_type")
        if "material_ingestion" not in getattr(job_type, "enums", []):
            # Preserve other job types installed by a later/parallel upgrade.
            values = list(getattr(job_type, "enums", []) or ["ocr_submission","ocr_batch","grade_submission","exam_setup"])
            values.append("material_ingestion")
            literals = ",".join("'" + value.replace("'", "''") + "'" for value in values)
            with target_engine.begin() as connection:
                connection.execute(text(f"ALTER TABLE processing_jobs MODIFY COLUMN job_type ENUM({literals}) NOT NULL"))
    for model in MATERIAL_TABLES:
        model.__table__.create(target_engine, checkfirst=True)


if __name__ == "__main__":
    upgrade(engine)
    print("Course material and retrieval tables are ready. Existing assessments, grades and references were not rewritten.")
