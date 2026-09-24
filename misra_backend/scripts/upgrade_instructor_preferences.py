"""Add instructor preference version history.

Back up the database before explicit execution. This script is idempotent and
does not create, approve, or apply preference profiles.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from database import engine
from models import InstructorPreferenceVersion


def main():
    InstructorPreferenceVersion.__table__.create(engine, checkfirst=True)
    print(
        "Instructor preference version table is ready. "
        "No rubric, question, or grading run was changed."
    )


if __name__ == "__main__":
    main()
