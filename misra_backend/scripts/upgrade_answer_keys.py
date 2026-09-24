"""Add versioned answer keys. Back up the database before explicit execution."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from database import engine
from models import AnswerKeyVersion


def main():
    AnswerKeyVersion.__table__.create(engine, checkfirst=True)
    print('Answer-key version table is ready. Existing rubric references were not changed.')


if __name__ == '__main__':
    main()
