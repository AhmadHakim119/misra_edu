from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from database import get_db
from schemas.grading_input import GradeRequest
from services.grading_service import process_grading, process_grading_with_policy
from services.extraction_review_service import build_extraction_review
from models import Answer, GradingRun, Question, Submission

router = APIRouter(prefix="/api", tags=["grading"])


def _require_verified_mapping(submission_id: str, db: Session):
    report = build_extraction_review(submission_id, db)
    if not report["readiness"]["bulk_grading_allowed"]:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "Verify the extraction mapping before grading.",
                "readiness": report["readiness"],
            },
        )
    return report


@router.post("/grade/{answer_id}")
async def grading_endpoint(
    answer_id: str,
    payload: GradeRequest,
    db: Session = Depends(get_db),
):
    answer = db.query(Answer).filter(Answer.id == answer_id).first()
    if not answer:
        raise HTTPException(status_code=404, detail="Answer not found")
    _require_verified_mapping(answer.submission_id, db)
    try:
        if payload.mode == "auto":
            return process_grading_with_policy(answer_id, db)
        return process_grading(answer_id, db, mode=payload.mode)
    except ValueError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error


@router.post("/submissions/{submission_id}/grade")
def grade_submission(
    submission_id: str,
    payload: GradeRequest,
    db: Session = Depends(get_db),
):
    submission = (
        db.query(Submission).filter(Submission.id == submission_id).first()
    )
    if not submission:
        raise HTTPException(status_code=404, detail="Submission not found")
    _require_verified_mapping(submission.id, db)

    answers = (
        db.query(Answer)
        .join(Question, Question.id == Answer.question_id)
        .filter(Answer.submission_id == submission.id)
        .order_by(Question.order_index.asc())
        .all()
    )
    submission.status = "grading"
    db.commit()
    graded_answers = []
    try:
        for answer in answers:
            if payload.mode == "auto":
                graded = process_grading_with_policy(answer.id, db)
            else:
                graded = process_grading(answer.id, db, mode=payload.mode)
            graded_answers.append(graded)

        submission.status = (
            "needs_review"
            if any(answer.needs_review for answer in graded_answers)
            else "graded"
        )
        db.commit()
        return {
            "submission_id": submission.id,
            "status": submission.status,
            "graded_count": len(graded_answers),
            "answers": graded_answers,
        }
    except ValueError as error:
        submission.status = "extracted"
        db.commit()
        raise HTTPException(status_code=502, detail=str(error)) from error

@router.get("/answers/{answer_id}/grading-runs")
async def get_grading_runs(
    answer_id: str,
    db: Session = Depends(get_db),
):
    return (
        db.query(GradingRun)
        .filter(GradingRun.answer_id == answer_id)
        .order_by(GradingRun.created_at.asc())
        .all()
    )
