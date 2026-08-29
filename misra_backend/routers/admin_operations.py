from __future__ import annotations

import csv
from datetime import datetime
import io
import os
from pathlib import Path
import shutil

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from redis import Redis
from rq import Queue, Worker
from rq.serializers import JSONSerializer
from sqlalchemy import text
from sqlalchemy.orm import Session

from database import get_db
from models import AuditLog, ProcessingJob, User
from services.audit_service import (
    audit_category,
    audit_retention_days,
    record_audit_event,
    safe_error_message,
)
from services.auth_dependencies import require_admin
from services.job_queue_service import job_to_dict, redis_connection
from services.job_recovery_service import recover_orphaned_jobs


router = APIRouter(prefix="/api/admin/operations", tags=["admin operations"])


def _event_metadata(event: AuditLog) -> dict:
    return event.extra_data if isinstance(event.extra_data, dict) else {}


def _serialize_event(event: AuditLog, actors: dict[str, User]) -> dict:
    metadata = _event_metadata(event)
    actor = actors.get(event.actor_id) if event.actor_id else None
    return {
        "id": event.id,
        "timestamp": event.created_at,
        "category": metadata.get("category") or audit_category(event.action),
        "actor": {
            "id": actor.id,
            "name": actor.full_name or actor.email,
            "email": actor.email,
        } if actor else None,
        "action": event.action,
        "target": {
            "type": event.entity_type,
            "id": event.entity_id,
        },
        "outcome": metadata.get("outcome") or "success",
        "details": metadata.get("details") if isinstance(metadata.get("details"), dict) else {},
    }


def _filtered_events(
    db: Session,
    admin: User,
    *,
    category: str | None,
    outcome: str | None,
    action: str | None,
    search: str | None,
    date_from: datetime | None,
    date_to: datetime | None,
    maximum: int = 5000,
) -> list[dict]:
    query = db.query(AuditLog).filter(AuditLog.institution_id == admin.institution_id)
    if action:
        query = query.filter(AuditLog.action == action)
    if date_from:
        query = query.filter(AuditLog.created_at >= date_from)
    if date_to:
        query = query.filter(AuditLog.created_at <= date_to)
    events = query.order_by(AuditLog.created_at.desc()).limit(maximum).all()
    actor_ids = {event.actor_id for event in events if event.actor_id}
    actors = {
        user.id: user
        for user in db.query(User).filter(
            User.id.in_(actor_ids),
            User.institution_id == admin.institution_id,
        ).all()
    } if actor_ids else {}
    rows = [_serialize_event(event, actors) for event in events]
    if category:
        rows = [row for row in rows if row["category"] == category]
    if outcome:
        rows = [row for row in rows if row["outcome"] == outcome]
    if search:
        needle = search.strip().lower()
        rows = [
            row for row in rows
            if needle in " ".join(
                [
                    row["action"],
                    row["target"]["type"],
                    row["target"]["id"] or "",
                    row["actor"]["name"] if row["actor"] else "system",
                ]
            ).lower()
        ]
    return rows


@router.get("/audit")
def list_audit_events(
    category: str | None = Query(default=None, pattern="^(activity|security|background_jobs|system)$"),
    outcome: str | None = Query(default=None, max_length=30),
    action: str | None = Query(default=None, max_length=100),
    search: str | None = Query(default=None, max_length=100),
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    limit: int = Query(default=100, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    rows = _filtered_events(
        db,
        admin,
        category=category,
        outcome=outcome,
        action=action,
        search=search,
        date_from=date_from,
        date_to=date_to,
    )
    return {
        "total": len(rows),
        "items": rows[offset:offset + limit],
        "retention_days": audit_retention_days(),
    }


@router.get("/audit.csv")
def export_audit_events(
    category: str | None = Query(default=None, pattern="^(activity|security|background_jobs|system)$"),
    outcome: str | None = Query(default=None, max_length=30),
    action: str | None = Query(default=None, max_length=100),
    search: str | None = Query(default=None, max_length=100),
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    rows = _filtered_events(
        db,
        admin,
        category=category,
        outcome=outcome,
        action=action,
        search=search,
        date_from=date_from,
        date_to=date_to,
    )
    stream = io.StringIO(newline="")
    writer = csv.writer(stream)
    writer.writerow(["Timestamp", "Category", "Actor", "Action", "Target type", "Target ID", "Outcome", "Safe details"])
    for row in rows:
        writer.writerow([
            row["timestamp"].isoformat() if row["timestamp"] else "",
            row["category"],
            row["actor"]["name"] if row["actor"] else "System",
            row["action"],
            row["target"]["type"],
            row["target"]["id"] or "",
            row["outcome"],
            "; ".join(f"{key}={value}" for key, value in row["details"].items()),
        ])
    record_audit_event(
        db,
        institution_id=admin.institution_id,
        actor_id=admin.id,
        action="audit_log_exported",
        entity_type="audit_log",
        details={"row_count": len(rows), "category": category or "all"},
    )
    db.commit()
    return Response(
        content="\ufeff" + stream.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=misra-audit-log.csv"},
    )


@router.get("/jobs")
def list_processing_jobs(
    status: str | None = Query(default=None, pattern="^(queued|processing|completed|failed|retrying)$"),
    job_type: str | None = Query(default=None, pattern="^(ocr_submission|ocr_batch|grade_submission)$"),
    limit: int = Query(default=100, ge=1, le=200),
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    query = db.query(ProcessingJob).filter(
        ProcessingJob.institution_id == admin.institution_id
    )
    if status:
        query = query.filter(ProcessingJob.status == status)
    if job_type:
        query = query.filter(ProcessingJob.job_type == job_type)
    jobs = query.order_by(ProcessingJob.created_at.desc()).limit(limit).all()
    return [job_to_dict(job) for job in jobs]


@router.post("/jobs/recover")
def recover_jobs(
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    summary = recover_orphaned_jobs(db, institution_id=admin.institution_id)
    record_audit_event(
        db,
        institution_id=admin.institution_id,
        actor_id=admin.id,
        action="job_recovery_requested",
        entity_type="processing_job",
        outcome="success" if summary.get("queue_available") else "failure",
        details={
            "checked": summary["checked"],
            "requeued": summary["requeued"],
            "failed_at_limit": summary["failed_at_limit"],
            "dispatch_failed": summary["dispatch_failed"],
        },
    )
    db.commit()
    return summary


def _storage_health() -> dict:
    storage = Path(__file__).resolve().parent.parent / "storage" / "uploads"
    available = storage.exists() and storage.is_dir() and os.access(storage, os.R_OK | os.W_OK)
    detail = "Upload storage is readable and writable" if available else "Upload storage is unavailable"
    free_bytes = None
    try:
        free_bytes = shutil.disk_usage(storage if storage.exists() else storage.parent).free
    except OSError:
        available = False
        detail = "Upload storage disk information is unavailable"
    return {"status": "online" if available else "offline", "detail": detail, "free_bytes": free_bytes}


@router.get("/health")
def operations_health(
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    services = {"api": {"status": "online", "detail": "FastAPI is responding"}}
    try:
        db.execute(text("SELECT 1"))
        services["database"] = {"status": "online", "detail": "MariaDB connection succeeded"}
    except Exception as error:
        services["database"] = {"status": "offline", "detail": safe_error_message(error, 160)}

    connection: Redis | None = None
    try:
        connection = redis_connection()
        connection.ping()
        services["redis"] = {"status": "online", "detail": "Redis queue storage is responding"}
    except Exception as error:
        services["redis"] = {"status": "offline", "detail": safe_error_message(error, 160)}

    if connection:
        try:
            workers = Worker.all(connection=connection)
            active_workers = []
            for worker in workers:
                state = worker.get_state()
                normalized = str(getattr(state, "value", state)).lower()
                if normalized in {"idle", "busy", "suspended"}:
                    active_workers.append(worker)
            queues = {
                name: Queue(name, connection=connection, serializer=JSONSerializer).count
                for name in ("ocr", "grading")
            }
            services["worker"] = {
                "status": "online" if active_workers else "offline",
                "detail": f"{len(active_workers)} active worker(s)",
                "active_count": len(active_workers),
                "queue_depth": queues,
            }
        except Exception as error:
            services["worker"] = {"status": "offline", "detail": safe_error_message(error, 160)}
    else:
        services["worker"] = {"status": "offline", "detail": "Worker state requires Redis"}
    services["storage"] = _storage_health()

    return {
        "checked_at": datetime.now(),
        "retention_days": audit_retention_days(),
        "services": services,
        "institution_id": admin.institution_id,
    }
