from __future__ import annotations

from datetime import datetime
import os
import uuid

from redis import Redis
from rq import Queue, Retry
from rq.serializers import JSONSerializer
from sqlalchemy.orm import Session

from models import ProcessingJob
from services.audit_service import safe_error_message


ACTIVE_JOB_STATUSES = ("queued", "processing", "retrying")
QUEUE_BY_JOB_TYPE = {
    "ocr_submission": "ocr",
    "ocr_batch": "ocr",
    "grade_submission": "grading",
}


def _max_attempts() -> int:
    return max(1, int(os.getenv("JOB_MAX_ATTEMPTS", "3")))


def _retry_intervals(max_retries: int) -> list[int]:
    configured = [
        max(0, int(value.strip()))
        for value in os.getenv("JOB_RETRY_INTERVALS", "10,30").split(",")
        if value.strip()
    ]
    if not configured:
        configured = [10]
    while len(configured) < max_retries:
        configured.append(configured[-1])
    return configured[:max_retries]


def redis_connection() -> Redis:
    return Redis.from_url(
        os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0"),
        decode_responses=False,
        socket_connect_timeout=1,
        socket_timeout=1,
    )


def queue_for(job_type: str) -> Queue:
    try:
        queue_name = QUEUE_BY_JOB_TYPE[job_type]
    except KeyError as error:
        raise ValueError(f"Unsupported processing job type: {job_type}") from error
    return Queue(
        queue_name,
        connection=redis_connection(),
        serializer=JSONSerializer,
        default_timeout=-1,
    )


def job_to_dict(job: ProcessingJob) -> dict:
    total = int(job.progress_total or 0)
    current = int(job.progress_current or 0)
    percentage = round((current / total) * 100, 1) if total else 0.0
    if job.status == "completed":
        percentage = 100.0
    duration_seconds = None
    if job.started_at:
        end = job.completed_at or datetime.now()
        duration_seconds = max(0, round((end - job.started_at).total_seconds(), 1))
    return {
        "id": job.id,
        "job_type": job.job_type,
        "status": job.status,
        "submission_id": job.submission_id,
        "batch_id": job.batch_id,
        "requested_by": job.requested_by,
        "progress_current": current,
        "progress_total": total,
        "progress_percent": percentage,
        "progress_message": job.progress_message,
        "attempt_count": int(job.attempt_count or 0),
        "max_attempts": int(job.max_attempts or 0),
        "error_message": safe_error_message(job.error_message) if job.error_message else None,
        "duration_seconds": duration_seconds,
        "created_at": job.created_at,
        "started_at": job.started_at,
        "completed_at": job.completed_at,
        "updated_at": job.updated_at,
    }


def _matching_active_job(
    db: Session,
    *,
    institution_id: str,
    job_type: str,
    submission_id: str | None,
    batch_id: str | None,
) -> ProcessingJob | None:
    query = db.query(ProcessingJob).filter(
        ProcessingJob.institution_id == institution_id,
        ProcessingJob.job_type == job_type,
        ProcessingJob.status.in_(ACTIVE_JOB_STATUSES),
    )
    if submission_id:
        query = query.filter(ProcessingJob.submission_id == submission_id)
    if batch_id:
        query = query.filter(ProcessingJob.batch_id == batch_id)
    return query.order_by(ProcessingJob.created_at.desc()).first()


def create_processing_job(
    db: Session,
    *,
    institution_id: str,
    requested_by: str | None,
    job_type: str,
    submission_id: str | None = None,
    batch_id: str | None = None,
    progress_total: int = 0,
    payload: dict | None = None,
) -> tuple[ProcessingJob, bool]:
    """Create and dispatch a job, or return the matching active job.

    The active-job check prevents double-clicks from launching duplicate OCR or
    grading work. The database row is committed before contacting Redis so a
    queue outage remains visible and safely retryable.
    """
    existing = _matching_active_job(
        db,
        institution_id=institution_id,
        job_type=job_type,
        submission_id=submission_id,
        batch_id=batch_id,
    )
    if existing:
        return existing, False

    job = ProcessingJob(
        institution_id=institution_id,
        requested_by=requested_by,
        job_type=job_type,
        submission_id=submission_id,
        batch_id=batch_id,
        status="queued",
        progress_total=max(0, progress_total),
        progress_message="Waiting for a worker",
        max_attempts=_max_attempts(),
        payload=payload or {},
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    dispatch_processing_job(job, db)
    return job, True


def dispatch_processing_job(job: ProcessingJob, db: Session) -> ProcessingJob:
    max_retries = max(0, int(job.max_attempts or 1) - 1)
    retry = Retry(max=max_retries, interval=_retry_intervals(max_retries)) if max_retries else None
    # RQ reserves ``:`` for its Redis key structure and rejects it in custom
    # job IDs. Keep this identifier limited to letters, numbers, underscores,
    # and hyphens so dispatch behaves consistently across RQ versions.
    rq_id = f"misra-{job.id}-{uuid.uuid4()}"
    try:
        queued = queue_for(job.job_type).enqueue(
            "services.job_execution_service.execute_processing_job",
            job.id,
            job_id=rq_id,
            retry=retry,
            result_ttl=86400,
            failure_ttl=604800,
        )
    except Exception as error:
        job.status = "failed"
        job.error_message = f"Queue unavailable: {safe_error_message(error)}"
        job.progress_message = "Could not reach the job queue"
        job.completed_at = datetime.now()
        db.commit()
        db.refresh(job)
        return job

    job.rq_job_id = queued.id
    job.status = "queued"
    job.error_message = None
    job.progress_message = "Waiting for a worker"
    db.commit()
    db.refresh(job)
    return job


def retry_processing_job(job: ProcessingJob, db: Session) -> ProcessingJob:
    if job.status != "failed":
        raise ValueError("Only failed jobs can be retried")
    job.status = "retrying"
    job.attempt_count = 0
    job.error_message = None
    job.completed_at = None
    job.started_at = None
    job.progress_message = "Retry queued"
    db.commit()
    return dispatch_processing_job(job, db)
