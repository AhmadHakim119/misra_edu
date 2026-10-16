"""Add account controls. Back up and explicitly authorize before live execution."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from database import engine
from models import InstructorAccountSettings


def main():
    InstructorAccountSettings.__table__.create(engine, checkfirst=True)
    print("Account settings table is ready. Existing profiles, guides and grades were not changed.")


if __name__ == "__main__":
    main()
