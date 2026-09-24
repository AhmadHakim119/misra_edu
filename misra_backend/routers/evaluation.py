from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from database import get_db
from models import Exam, User
from services.auth_dependencies import require_instructor
from services.evaluation_service import build_evaluation_report


router = APIRouter(prefix="/api", tags=["evaluation"])


@router.get("/evaluation")
def get_evaluation_report(
    exam_id: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(require_instructor),
):
    if exam_id:
        owned_exam = (
            db.query(Exam.id)
            .filter(
                Exam.id == exam_id,
                Exam.institution_id == user.institution_id,
            )
            .first()
        )
        if not owned_exam:
            # Use the same response for missing and cross-institution exams so
            # callers cannot use this endpoint to enumerate another tenant.
            raise HTTPException(status_code=404, detail="Exam not found")

    return build_evaluation_report(
        db,
        institution_id=user.institution_id,
        exam_id=exam_id,
    )
