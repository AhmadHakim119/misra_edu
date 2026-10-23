"""Institution-scoped read-only pilot papers; editing reuses rubric versions."""
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from database import get_db
from models import User
from services.auth_dependencies import require_instructor
from services import pilot_archive_service as service

router = APIRouter(prefix='/api/pilot-studies', tags=['pilot-studies'])


def _call(fn, *args):
    try:
        return fn(*args)
    except FileNotFoundError:
        raise HTTPException(404, 'Saved pilot record not found.') from None
    except (ValueError, KeyError, TypeError):
        raise HTTPException(409, 'Saved pilot data is unavailable or changed. Check the local import.') from None


@router.get('')
def catalog(db: Session = Depends(get_db), user: User = Depends(require_instructor)):
    return _call(service.list_archives, db, user)


@router.get('/{study_id}')
def study(study_id: str, db: Session = Depends(get_db), user: User = Depends(require_instructor)):
    return _call(service.study_detail, db, user, study_id)


@router.get('/{study_id}/papers/{paper_id}')
def paper(study_id: str, paper_id: str, db: Session = Depends(get_db), user: User = Depends(require_instructor)):
    return _call(service.paper_detail, db, user, study_id, paper_id)


@router.get('/{study_id}/papers/{paper_id}/pages/{index}')
def page(study_id: str, paper_id: str, index: int,
         db: Session = Depends(get_db), user: User = Depends(require_instructor)):
    path = _call(service.page_file, db, user, study_id, paper_id, index)
    return FileResponse(path, headers={'Cache-Control': 'no-store, max-age=0'})
