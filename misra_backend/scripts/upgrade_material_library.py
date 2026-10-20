"""Add library metadata only; never changes approved content or scopes."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from sqlalchemy import inspect
from database import engine
from services.material_library_service import LIBRARY_TABLES


def upgrade(target_engine):
    inspector=inspect(target_engine)
    if not inspector.has_table('material_versions'):
        raise RuntimeError('Run the existing course-material upgrade first.')
    for model in LIBRARY_TABLES:model.__table__.create(target_engine,checkfirst=True)


if __name__=='__main__':
    upgrade(engine)
    print('Chapter metadata and assessment attachments are ready. Existing source text, scopes and grades were not changed.')
