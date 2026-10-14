"""Explicit additive upgrade; back up MariaDB before running."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from database import engine
from models import ExtractionInventory


def upgrade(target_engine):
    ExtractionInventory.__table__.create(target_engine,checkfirst=True)


if __name__ == "__main__":
    upgrade(engine)
    print("Extraction inventory table ready. Existing submissions and grades were not rewritten.")
