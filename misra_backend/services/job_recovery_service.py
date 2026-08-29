from __future__ import annotations

from datetime import datetime, timedelta, timezone
import os
from typing import Callable

from rq.exceptions import NoSuchJobError
from rq.job import Job
from sqlalchemy.orm import Session

from models import ProcessingJob
from services.audit_service import record_audit_event, safe_error_message
from services.job_queue_service import (
    ACTIVE_JOB_STATUSES,
    dispatch_processing_job,
    redis_connection,
)


ACTIVE_RQ_STATUSES = {"queued", "started", "deferred", "scheduled"}


def orphan_after_seconds() -> int:
    try:
        return max(60, int(os.getenv("JOB_ORPHAN_AFTER_SECONDS", "1800")))
    except ValueError:
        return 1800


def _naive_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo:
        return value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


def inspect_rq_job(job: ProcessingJob, connection) -> dict:
    if not job.rq_job_id:
        return {"status": "missing", "last_heartbeat": None}
    try:
        rq_job = Job.fetch(job.rq_job_id, connection=connection)
    except NoSuchJobError:
        return {"status": "missing", "last_heartbeat": None}
    status = rq_job.get_status(refresh=True)
    normalized = getattr(status, "value", str(status)).lower()
    return {
        "status": normalized,
        "last_heartbeat": _naive_utc(getattr(rq_job, "last_heartbeat", None)),
    }


def recover_orphaned_jobs(
    db: Session,
    *,
    institution_id: str | None = None,
    stale_after_seconds: int | None = None,
    now: datetime | None = None,
    inspector: Callable[[ProcessingJob, object], dict] | None = None,
) -> dict:
    """Reconcile stale MariaDB job rows with Redis and safely requeue orphans."""
    current_time = now or datetime.now()
    stale_seconds = stale_after_seconds or orphan_after_seconds()
    cutoff = current_time - timedelta(seconds=stale_seconds)
    summary = {
        "queue_available": True,
        "checked": 0,
        "healthy": 0,
        "requeued": 0,
        "reconciled_completed": 0,
        "failed_at_limit": 0,
        "dispatch_failed": 0,
        "job_ids": [],
    }

    try:
        connection = redis_connection()
        if inspector is None:
            connection.ping()
    except Exception as error:
        summary["queue_available"] = False
        summary["error"] = safe_error_message(error)
        return summary

    inspect = inspector or inspect_rq_job
    query = db.query(ProcessingJob).filter(
        ProcessingJob.status.in_(ACTIVE_JOB_STATUSES),
        ProcessingJob.updated_at < cutoff,
    )
    if institution_id:
        query = query.filter(ProcessingJob.institution_id == institution_id)
    candidates = query.order_by(ProcessingJob.updated_at.asc()).limit(250).all()

    for candidate in candidates:
        summary["checked"] += 1
        try:
            snapshot = inspect(candidate, connection)
        except Exception as error:
            summary["queue_available"] = False
            summary["error"] = safe_error_message(error)
            break
        rq_status = str(snapshot.get("status") or "missing").lower()
        heartbeat = _naive_utc(snapshot.get("last_heartbeat"))
        heartbeat_is_recent = bool(heartbeat and heartbeat >= cutoff)

        if rq_status in ACTIVE_RQ_STATUSES and (
            rq_status != "started" or heartbeat_is_recent
        ):
            summary["healthy"] += 1
            continue

        job = (
            db.query(ProcessingJob)
            .filter(
                ProcessingJob.id == candidate.id,
                ProcessingJob.status.in_(ACTIVE_JOB_STATUSES),
                ProcessingJob.updated_at < cutoff,
            )
            .with_for_update()
            .first()
        )
        if not job:
            continue

        if rq_status == "finished":
            job.status = "completed"
            job.progress_current = job.progress_total
            job.progress_message = "Recovered completed queue result"
            job.error_message = None
            job.completed_at = current_time
            record_audit_event(
                db,
                institution_id=job.institution_id,
                actor_id=None,
                action="job_completion_reconciled",
                entity_type="processing_job",
                entity_id=job.id,
                details={"job_type": job.job_type},
            )
            db.commit()
            summary["reconciled_completed"] += 1
            summary["job_ids"].append(job.id)
            continue

        if int(job.attempt_count or 0) >= int(job.max_attempts or 1):
            job.status = "failed"
            job.progress_message = "Orphaned job reached its retry limit"
            job.error_message = "Worker stopped before the job completed; retry limit reached."
            job.completed_at = current_time
            record_audit_event(
                db,
                institution_id=job.institution_id,
                actor_id=None,
                action="job_orphan_failed",
                entity_type="processing_job",
                entity_id=job.id,
                outcome="failure",
                details={"job_type": job.job_type, "attempt_count": job.attempt_count},
            )
            db.commit()
            summary["failed_at_limit"] += 1
            summary["job_ids"].append(job.id)
            continue

        job.status = "retrying"
        job.progress_message = "Recovered abandoned work; retry queued"
        job.error_message = None
        job.completed_at = None
        db.commit()
        dispatched = dispatch_processing_job(job, db)
        dispatch_succeeded = dispatched.status == "queued"
        record_audit_event(
            db,
            institution_id=job.institution_id,
            actor_id=None,
            action="job_orphan_requeued" if dispatch_succeeded else "job_orphan_requeue_failed",
            entity_type="processing_job",
            entity_id=job.id,
            outcome="success" if dispatch_succeeded else "failure",
            details={"job_type": job.job_type, "attempt_count": job.attempt_count},
        )
        db.commit()
        if dispatch_succeeded:
            summary["requeued"] += 1
        else:
            summary["dispatch_failed"] += 1
        summary["job_ids"].append(job.id)

    return summary
