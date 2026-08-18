from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from database import get_db
from services.evaluation_service import build_evaluation_report


router = APIRouter(prefix="/api", tags=["evaluation"])


@router.get("/evaluation")
def get_evaluation_report(exam_id: str | None = None, db: Session = Depends(get_db)):
    return build_evaluation_report(db, exam_id=exam_id)
