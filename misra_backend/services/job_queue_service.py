from __future__ import annotations

from datetime import datetime
import os
import uuid

from redis import Redis
from rq import Queue, Retry
from rq.serializers import JSONSerializer
from sqlalchemy.orm import Session

from models import ProcessingJob, Submission
from services.audit_service import safe_error_message


ACTIVE_JOB_STATUSES = ("queued", "processing", "retrying")
QUEUE_BY_JOB_TYPE = {
    "material_ingestion": "ocr",
    "exam_setup": "ocr",
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
    payload = job.payload or {}
    stage = payload.get('grading_stage') if job.job_type == 'grade_submission' else None
    phase_progress = payload.get('grading_stage_progress', 0) if stage else 0
    percentage = round(min(1, (current + phase_progress) / total) * 100, 1) if total else 0.0
    if job.status == "completed":
        percentage = 100.0
    duration_seconds = None
    if job.started_at:
        end = job.completed_at or datetime.now()
        duration_seconds = max(0, round((end - job.started_at).total_seconds(), 1))
    return {
        "id": job.id,
        "job_type": job.job_type,
        "operation": (job.payload or {}).get('operation') if (job.payload or {}).get('operation') in {'locate_answers','read_answer_area','regrade_corrected_answer'} else None,
        "page_index": (job.payload or {}).get('page_index') if (job.payload or {}).get('operation') == 'locate_answers' else None,
        "status": ('stopped' if job.status == 'failed' else 'stopping')
        if stop_requested(job) else job.status,
        "incomplete_comparison_count": (job.payload or {}).get('incomplete_comparison_count', 0),
        "submission_id": job.submission_id,
        "batch_id": job.batch_id,
        "requested_by": job.requested_by,
        "progress_current": current,
        "progress_total": total,
        "progress_percent": percentage,
        "grading_stage": stage,
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
    return query.order_by(ProcessingJob.created_at.desc()).with_for_update().first()


def lock_job(db: Session, job_id: str) -> ProcessingJob | None:
    return db.query(ProcessingJob).filter_by(id=job_id).populate_existing().with_for_update().first()


def lock_grading_paper(db, job_type, submission_id, institution_id):
    if job_type == 'grade_submission' and submission_id:
        db.query(Submission.id).filter_by(id=submission_id, institution_id=institution_id).with_for_update().scalar()


def stop_requested(job):
    return bool((job.payload or {}).get('grading_stop_requested'))


def finish_stopped_job(job: ProcessingJob, db: Session) -> None:
    # Reuse the persisted terminal state on existing installations. The API
    # distinguishes a deliberate stop from a failure using the job payload.
    job.status = 'failed'
    job.progress_message = 'Grading stopped'
    job.error_message = None
    job.completed_at = datetime.now()
    if job.submission_id:
        submission = db.get(Submission, job.submission_id)
        if submission and submission.status == 'grading':
            submission.status = 'extracted'
            submission.error_message = None


def stop_grading_job(job: ProcessingJob, db: Session) -> ProcessingJob:
    lock_grading_paper(db, job.job_type, job.submission_id, job.institution_id)
    job = lock_job(db, job.id)
    if not job or job.job_type != 'grade_submission':
        raise ValueError('Only grading jobs can be stopped.')
    if stop_requested(job):
        return job
    if job.status not in ACTIVE_JOB_STATUSES:
        raise ValueError('This grading job is no longer running.')
    job.payload = {**(job.payload or {}), 'grading_stop_requested': True}
    if job.status == 'processing':
        job.progress_message = 'Stopping after the current AI request'
    else:
        finish_stopped_job(job, db)
    return job


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
    lock_grading_paper(db, job_type, submission_id, institution_id)
    existing = _matching_active_job(
        db,
        institution_id=institution_id,
        job_type=job_type,
        submission_id=submission_id,
        batch_id=batch_id,
    )
    if existing:
        return existing, False

    from services.inference_profiles import active_profile
    job_payload = dict(payload or {})
    job_payload.pop('_inference_profile', None)
    profile = active_profile()
    if profile:
        job_payload['_inference_profile'] = profile
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
        payload=job_payload,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    dispatch_processing_job(job, db)
    return job, True


def dispatch_processing_job(job: ProcessingJob, db: Session) -> ProcessingJob:
    job = lock_job(db, job.id)
    if job.status not in ('queued', 'retrying') or stop_requested(job):
        return job
    max_retries = max(0, int(job.max_attempts or 1) - 1)
    retry = Retry(max=max_retries, interval=_retry_intervals(max_retries)) if max_retries else None
    # RQ reserves ``:`` for its Redis key structure and rejects it in custom
    # job IDs. Keep this identifier limited to letters, numbers, underscores,
    # and hyphens so dispatch behaves consistently across RQ versions.
    rq_id = f"misra-{job.id}-{uuid.uuid4()}"
    job.rq_job_id = rq_id
    job.status = 'queued'
    job.error_message = None
    job.progress_message = 'Waiting for a worker'
    db.commit()
    try:
        target = ('services.inference_profiles.execute_profile_job' if (job.payload or {}).get('_inference_profile')
                  else 'services.job_execution_service.execute_processing_job')
        queue_for(job.job_type).enqueue(
            target,
            job.id,
            job_id=rq_id,
            retry=retry,
            result_ttl=86400,
            failure_ttl=604800,
        )
    except Exception as error:
        job = lock_job(db, job.id)
        if job.rq_job_id != rq_id or job.status != 'queued':
            return job
        job.status = "failed"
        job.error_message = f"Queue unavailable: {safe_error_message(error)}"
        job.progress_message = "Could not reach the job queue"
        job.completed_at = datetime.now()
        db.commit()
        db.refresh(job)
        return job

    db.refresh(job)
    return job


def retry_processing_job(job: ProcessingJob, db: Session) -> ProcessingJob:
    lock_grading_paper(db, job.job_type, job.submission_id, job.institution_id)
    job = lock_job(db, job.id)
    if not job:
        raise ValueError('Processing job not found')
    if job.status != "failed":
        raise ValueError("Only failed jobs can be retried")
    if job.job_type == 'grade_submission' and job.submission_id and _matching_active_job(
        db, institution_id=job.institution_id, job_type=job.job_type,
        submission_id=job.submission_id, batch_id=None,
    ):
        raise ValueError('Another grading job is already active for this paper. Open Activity to follow it.')
    if job.job_type == 'grade_submission' and job.submission_id and db.query(ProcessingJob.id).filter(
        ProcessingJob.institution_id == job.institution_id,
        ProcessingJob.submission_id == job.submission_id,
        ProcessingJob.job_type == job.job_type,
        ProcessingJob.id != job.id,
        ProcessingJob.created_at >= job.created_at,
    ).first():
        raise ValueError('This paper has another grading job from the same time or later. Open the paper to review the saved work.')
    from services.inference_profiles import TEXT_ONLY_IMAGE_ERROR
    if job.job_type == 'grade_submission' and (job.error_message or '').startswith(TEXT_ONLY_IMAGE_ERROR):
        raise ValueError('This job uses text-only Qwen. Save Qwen Vision in AI services, then open the paper and select Grade with current AI setup.')
    job.status = "retrying"
    job.rq_job_id = None
    if stop_requested(job):
        job.payload = {key: value for key, value in job.payload.items() if key != 'grading_stop_requested'}
    job.attempt_count = 0
    job.error_message = None
    job.completed_at = None
    job.started_at = None
    job.progress_message = "Retry queued"
    db.commit()
    return dispatch_processing_job(job, db)
