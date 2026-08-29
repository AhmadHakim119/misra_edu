from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from database import SessionLocal
from models import Answer, GradingRun, ProcessingJob, Question, Submission
from services.grading_service import process_grading, process_grading_with_policy
from services.ocr_service import process_batch, process_submission
from services.audit_service import safe_error_message


def _progress_callback(job: ProcessingJob, db: Session):
    def update(current: int, total: int, message: str) -> None:
        job.progress_current = max(0, current)
        job.progress_total = max(0, total)
        job.progress_message = message[:255]
        db.commit()

    return update


def _grade_submission(job: ProcessingJob, db: Session) -> None:
    submission = db.query(Submission).filter(Submission.id == job.submission_id).first()
    if not submission:
        raise ValueError(f"Submission {job.submission_id} not found")

    answers = (
        db.query(Answer)
        .join(Question, Question.id == Answer.question_id)
        .filter(Answer.submission_id == submission.id)
        .order_by(Question.order_index.asc())
        .all()
    )
    if not answers:
        raise ValueError("This submission has no mapped answers to grade")

    payload = dict(job.payload or {})
    mode = payload.get("mode", "auto")
    completed_answer_ids = set(payload.get("completed_answer_ids") or [])
    submission.status = "grading"
    submission.error_message = None
    job.progress_total = len(answers)
    db.commit()

    for index, answer in enumerate(answers):
        if answer.id in completed_answer_ids:
            job.progress_current = index + 1
            job.progress_message = f"Already graded answer {index + 1} of {len(answers)}"
            db.commit()
            continue

        # A worker may fail after one mode was recorded but before an adaptive
        # dual-mode answer finished. Remove only this job's incomplete runs and
        # repeat that answer, preserving every historical run from other jobs.
        db.query(GradingRun).filter(
            GradingRun.processing_job_id == job.id,
            GradingRun.answer_id == answer.id,
        ).delete(synchronize_session=False)
        db.commit()

        if mode == "auto":
            process_grading_with_policy(answer.id, db, processing_job_id=job.id)
        else:
            process_grading(
                answer.id,
                db,
                mode=mode,
                processing_job_id=job.id,
            )

        completed_answer_ids.add(answer.id)
        payload["completed_answer_ids"] = sorted(completed_answer_ids)
        job.payload = payload
        job.progress_current = index + 1
        job.progress_message = f"Graded answer {index + 1} of {len(answers)}"
        db.commit()

    db.refresh(submission)
    graded_answers = db.query(Answer).filter(Answer.submission_id == submission.id).all()
    submission.status = (
        "needs_review"
        if any(answer.needs_review for answer in graded_answers)
        else "graded"
    )
    db.commit()


def execute_processing_job(processing_job_id: str) -> None:
    """RQ entry point. The queue passes only the durable job UUID."""
    db = SessionLocal()
    job: ProcessingJob | None = None
    try:
        job = db.query(ProcessingJob).filter(ProcessingJob.id == processing_job_id).first()
        if not job:
            raise ValueError(f"Processing job {processing_job_id} not found")
        if job.status == "completed":
            return

        job.status = "processing"
        job.attempt_count = int(job.attempt_count or 0) + 1
        job.started_at = job.started_at or datetime.now()
        job.completed_at = None
        job.error_message = None
        job.progress_message = "Worker started"
        db.commit()

        progress = _progress_callback(job, db)
        if job.job_type == "ocr_submission":
            process_submission(job.submission_id, db, progress_callback=progress)
        elif job.job_type == "ocr_batch":
            payload = job.payload or {}
            process_batch(
                job.batch_id,
                db,
                progress_callback=progress,
                submission_ids=payload.get("submission_ids"),
            )
        elif job.job_type == "grade_submission":
            _grade_submission(job, db)
        else:
            raise ValueError(f"Unsupported processing job type: {job.job_type}")

        job.status = "completed"
        job.progress_current = job.progress_total
        job.progress_message = "Completed"
        job.completed_at = datetime.now()
        db.commit()
    except Exception as error:
        db.rollback()
        job = db.query(ProcessingJob).filter(ProcessingJob.id == processing_job_id).first()
        if job:
            safe_error = safe_error_message(error)
            exhausted = int(job.attempt_count or 0) >= int(job.max_attempts or 1)
            job.status = "failed" if exhausted else "retrying"
            job.error_message = safe_error
            job.progress_message = (
                "Retry limit reached" if exhausted else "Failed; waiting to retry"
            )
            job.completed_at = datetime.now() if exhausted else None
            if exhausted and job.job_type == "grade_submission" and job.submission_id:
                submission = (
                    db.query(Submission)
                    .filter(Submission.id == job.submission_id)
                    .first()
                )
                if submission and submission.status == "grading":
                    submission.status = "extracted"
                    submission.error_message = safe_error
            db.commit()
        raise
    finally:
        db.close()
