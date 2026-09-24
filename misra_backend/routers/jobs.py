from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_
from sqlalchemy.orm import Session

from database import get_db
from models import Batch, Course, Exam, ProcessingJob, Submission, User
from services.auth_dependencies import require_instructor
from services.job_queue_service import job_to_dict, retry_processing_job
from services.audit_service import record_audit_event


router = APIRouter(prefix="/api", tags=["jobs"])


def _owned_job(job_id: str, db: Session, user: User) -> ProcessingJob | None:
    return db.query(ProcessingJob).filter(
        ProcessingJob.id == job_id,
        ProcessingJob.institution_id == user.institution_id,
    ).first()


def _workspace_job(job: ProcessingJob, db: Session) -> dict:
    """Attach safe navigation context without exposing a job payload."""
    exam_id = None
    batch = None
    if job.submission_id:
        exam_id = db.query(Submission.exam_id).filter(
            Submission.id == job.submission_id,
            Submission.institution_id == job.institution_id,
        ).scalar()
    elif job.batch_id:
        batch = db.query(Batch).filter(
            Batch.id == job.batch_id,
            Batch.institution_id == job.institution_id,
        ).first()
        exam_id = batch.exam_id if batch else None
    elif isinstance(job.payload, dict):
        exam_id = job.payload.get("exam_id")

    exam = None
    course = None
    if exam_id:
        exam = db.query(Exam).filter(
            Exam.id == exam_id,
            Exam.institution_id == job.institution_id,
        ).first()
        if exam:
            course = db.query(Course).filter(
                Course.id == exam.course_id,
                Course.institution_id == job.institution_id,
            ).first()

    return {
        **job_to_dict(job),
        "exam_id": exam.id if exam else None,
        "exam_title": exam.title if exam else None,
        "course_code": course.course_code if course else None,
        "batch_status": batch.status if batch else None,
        "batch_total_count": int(batch.total_count or 0) if batch else None,
        "batch_completed_count": int(batch.completed_count or 0) if batch else None,
        "batch_failed_count": int(batch.failed_count or 0) if batch else None,
    }


@router.get("/jobs")
def list_workspace_jobs(
    limit: int = Query(default=8, ge=1, le=20),
    db: Session = Depends(get_db),
    user: User = Depends(require_instructor),
):
    """Return this instructor's durable activity for the shared workspace UI.

    Active jobs remain visible regardless of age. Recently terminal jobs are
    included for 24 hours so completion or failure is not lost on navigation.
    """
    active_statuses = ("queued", "processing", "retrying")
    recent_cutoff = datetime.now() - timedelta(hours=24)
    jobs = db.query(ProcessingJob).filter(
        ProcessingJob.institution_id == user.institution_id,
        ProcessingJob.requested_by == user.id,
        or_(
            ProcessingJob.status.in_(active_statuses),
            ProcessingJob.completed_at >= recent_cutoff,
        ),
    ).order_by(ProcessingJob.created_at.desc()).limit(limit).all()
    active_count = db.query(ProcessingJob).filter(
        ProcessingJob.institution_id == user.institution_id,
        ProcessingJob.requested_by == user.id,
        ProcessingJob.status.in_(active_statuses),
    ).count()
    return {
        "items": [_workspace_job(job, db) for job in jobs],
        "active_count": active_count,
    }


@router.get("/jobs/{job_id}")
def get_job(
    job_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_instructor),
):
    job = _owned_job(job_id, db, user)
    if not job:
        raise HTTPException(status_code=404, detail="Processing job not found")
    return job_to_dict(job)


@router.get("/submissions/{submission_id}/jobs")
def get_submission_jobs(
    submission_id: str,
    job_type: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(require_instructor),
):
    query = db.query(ProcessingJob).filter(
        ProcessingJob.submission_id == submission_id,
        ProcessingJob.institution_id == user.institution_id,
    )
    if job_type:
        query = query.filter(ProcessingJob.job_type == job_type)
    jobs = query.order_by(ProcessingJob.created_at.desc()).limit(20).all()
    return [job_to_dict(job) for job in jobs]


@router.post("/jobs/{job_id}/retry", status_code=202)
def retry_job(
    job_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_instructor),
):
    job = _owned_job(job_id, db, user)
    if not job:
        raise HTTPException(status_code=404, detail="Processing job not found")
    try:
        retried = retry_processing_job(job, db)
        record_audit_event(
            db,
            institution_id=user.institution_id,
            actor_id=user.id,
            action="job_retry_requested",
            entity_type="processing_job",
            entity_id=job.id,
            details={"job_type": job.job_type, "attempt_count": retried.attempt_count},
        )
        db.commit()
        return job_to_dict(retried)
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
