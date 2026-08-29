from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from database import get_db
from models import ProcessingJob, User
from services.auth_dependencies import require_instructor
from services.job_queue_service import job_to_dict, retry_processing_job
from services.audit_service import record_audit_event


router = APIRouter(prefix="/api", tags=["jobs"])


def _owned_job(job_id: str, db: Session, user: User) -> ProcessingJob | None:
    return db.query(ProcessingJob).filter(
        ProcessingJob.id == job_id,
        ProcessingJob.institution_id == user.institution_id,
    ).first()


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
