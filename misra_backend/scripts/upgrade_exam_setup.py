"""Add the exam_setup job type without changing existing jobs. Back up first."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sqlalchemy import inspect, text
from database import engine


def main():
    if engine.dialect.name not in ('mysql', 'mariadb'):
        print('No enum migration needed for this database dialect.')
        return
    column = next(c for c in inspect(engine).get_columns('processing_jobs') if c['name'] == 'job_type')
    values = list(column['type'].enums)
    if 'exam_setup' not in values:
        if values != ['ocr_submission', 'ocr_batch', 'grade_submission']:
            raise RuntimeError('Unexpected job types. Inspect schema before modifying it.')
        with engine.begin() as connection:
            connection.execute(text("ALTER TABLE processing_jobs MODIFY job_type ENUM('ocr_submission','ocr_batch','grade_submission','exam_setup') NOT NULL"))
    print('Exam setup job type is ready.')


if __name__ == '__main__':
    main()
