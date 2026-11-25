from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from database import get_db
from schemas.grading_input import ContinueGradeRequest, GradeRequest
from services.grading_service import process_grading, process_grading_with_policy
from services.extraction_review_service import build_extraction_review
from services.auth_dependencies import require_instructor
from services.job_queue_service import create_processing_job, job_to_dict, lock_grading_paper
from services.inference_profiles import active_profile
from services.audit_service import record_audit_event
from services.grading_scope_service import is_external_question, is_removed_question
from models import Answer, GradingRun, ProcessingJob, Question, Submission, User
from schemas.public_results import GradingRunRecord, AnswerRecord

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


@router.post("/grade/{answer_id}", response_model=AnswerRecord)
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
    question = db.query(Question).filter(Question.id == answer.question_id).first()
    if question and is_removed_question(question):
        raise HTTPException(409, 'This question was removed from the exam. Restore it in Extraction before grading.')
    if question and is_external_question(question):
        raise HTTPException(status_code=409, detail="This question is assessed outside MISRA; it is not an AI zero.")
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
    report = _require_verified_mapping(submission.id, db)

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
        progress_total=report["readiness"]["expected_question_count"],
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


@router.post('/submissions/{submission_id}/grade/continue', status_code=202)
def continue_grading(submission_id: str, payload: ContinueGradeRequest,
                     db: Session = Depends(get_db), user: User = Depends(require_instructor)):
    if not lock_grading_paper(db, 'grade_submission', submission_id, user.institution_id):
        raise HTTPException(404, 'Submission not found.')
    scope = db.query(ProcessingJob).filter_by(institution_id=user.institution_id,
                                              submission_id=submission_id, job_type='grade_submission')
    source = scope.filter_by(id=payload.from_job_id).with_for_update().first()
    if not source:
        raise HTTPException(404, 'Grading job not found for this paper.')
    if source.status != 'failed' or (source.payload or {}).get('operation') == 'regrade_corrected_answer':
        raise HTTPException(409, 'Stop whole-paper grading or wait for it to fail before changing its AI setup.')

    existing = scope.filter(ProcessingJob.payload['continued_from_job_id'].as_string() == source.id).with_for_update().first()
    if existing:
        if (existing.payload or {}).get('_inference_profile') != active_profile():
            raise HTTPException(409, 'This paper already has a continuation with a different AI setup. Open the latest job in Activity.')
        return {'submission_id': submission_id, 'job': job_to_dict(existing)}

    report = _require_verified_mapping(submission_id, db)
    saved_ids = [row['answer']['id'] for row in report['questions'] if row.get('answer') and
                 (row['answer'].get('score') is not None or row['answer'].get('teacher_override_score') is not None)]
    if len(saved_ids) == len(report['questions']):
        raise HTTPException(409, 'Every paper answer already has a saved grade.')

    job, created = create_processing_job(db, institution_id=user.institution_id, requested_by=user.id,
        job_type='grade_submission', submission_id=submission_id, progress_total=len(report['questions']),
        payload={'mode': (source.payload or {}).get('mode', 'auto'), 'completed_answer_ids': saved_ids,
                 'continued_from_job_id': source.id})
    if not created:
        raise HTTPException(409, 'Another grading job is already active for this paper. Open Activity to follow it.')
    record_audit_event(db, institution_id=user.institution_id, actor_id=user.id,
        action='grading_job_continued', entity_type='processing_job', entity_id=job.id,
        details={'previous_job_id': source.id, 'preserved_answer_count': len(saved_ids)})
    db.commit()
    return {'submission_id': submission_id, 'job': job_to_dict(job)}


@router.get("/answers/{answer_id}/grading-runs", response_model=list[GradingRunRecord])
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
