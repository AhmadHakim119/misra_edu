"""Add source-default version storage. Back up MariaDB before running explicitly."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from database import engine
from models import AssessmentMaterialScopeVersion
from scripts.upgrade_course_materials import upgrade as upgrade_materials


def upgrade(target_engine):
    upgrade_materials(target_engine)
    AssessmentMaterialScopeVersion.__table__.create(target_engine, checkfirst=True)


if __name__ == "__main__":
    upgrade(engine)
    print("Assessment source defaults are ready. No existing scopes, rubrics or grading runs were rewritten.")
