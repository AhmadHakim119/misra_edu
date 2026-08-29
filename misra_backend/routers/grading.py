from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from database import get_db
from schemas.grading_input import GradeRequest
from services.grading_service import process_grading, process_grading_with_policy
from services.extraction_review_service import build_extraction_review
from services.auth_dependencies import require_instructor
from services.job_queue_service import create_processing_job, job_to_dict
from services.audit_service import record_audit_event
from models import Answer, GradingRun, Question, Submission, User

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
    user: User = Depends(require_instructor),
):
    answer = db.query(Answer).filter(
        Answer.id == answer_id,
        Answer.institution_id == user.institution_id,
    ).first()
    if not answer:
        raise HTTPException(status_code=404, detail="Answer not found")
    _require_verified_mapping(answer.submission_id, db)
    try:
        if payload.mode == "auto":
            result = process_grading_with_policy(answer_id, db)
        else:
            result = process_grading(answer_id, db, mode=payload.mode)
        record_audit_event(
            db,
            institution_id=user.institution_id,
            actor_id=user.id,
            action="answer_graded",
            entity_type="answer",
            entity_id=answer.id,
            details={"mode": payload.mode, "submission_id": answer.submission_id},
        )
        db.commit()
        return result
    except ValueError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error


@router.post("/submissions/{submission_id}/grade", status_code=202)
def grade_submission(
    submission_id: str,
    payload: GradeRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_instructor),
):
    submission = (
        db.query(Submission).filter(
            Submission.id == submission_id,
            Submission.institution_id == user.institution_id,
        ).first()
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
    job, created = create_processing_job(
        db,
        institution_id=submission.institution_id,
        requested_by=user.id,
        job_type="grade_submission",
        submission_id=submission.id,
        progress_total=len(answers),
        payload={"mode": payload.mode, "completed_answer_ids": []},
    )
    if created:
        record_audit_event(
            db,
            institution_id=submission.institution_id,
            actor_id=user.id,
            action="grading_job_queued",
            entity_type="submission",
            entity_id=submission.id,
            details={"job_id": job.id, "mode": payload.mode, "answer_count": len(answers)},
        )
        db.commit()
    return {"submission_id": submission.id, "job": job_to_dict(job)}

@router.get("/answers/{answer_id}/grading-runs")
async def get_grading_runs(
    answer_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_instructor),
):
    answer = db.query(Answer).filter(
        Answer.id == answer_id,
        Answer.institution_id == user.institution_id,
    ).first()
    if not answer:
        raise HTTPException(status_code=404, detail="Answer not found")
    return (
        db.query(GradingRun)
        .filter(GradingRun.answer_id == answer_id)
        .order_by(GradingRun.created_at.asc())
        .all()
    )
