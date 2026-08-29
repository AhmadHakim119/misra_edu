from __future__ import annotations

from datetime import datetime, timedelta
import os
import re
from typing import Any

from sqlalchemy.orm import Session

from models import AuditLog


_BLOCKED_KEY_PARTS = (
    "password",
    "token",
    "cookie",
    "secret",
    "api_key",
    "authorization",
    "ocr_text",
    "paper_content",
)


def audit_category(action: str) -> str:
    value = action.lower()
    if any(part in value for part in ("login", "password", "account", "instructor_", "access", "csrf", "forbidden")):
        return "security"
    if any(part in value for part in ("job", "ocr", "grading_worker", "queue")):
        return "background_jobs"
    if any(part in value for part in ("health", "storage", "database", "redis", "worker")):
        return "system"
    return "activity"


def _safe_value(value: Any, depth: int = 0) -> Any:
    if depth > 2:
        return None
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return value.replace("\r", " ").replace("\n", " ")[:300]
    if isinstance(value, dict):
        return {
            str(key)[:60]: _safe_value(item, depth + 1)
            for key, item in value.items()
            if not any(blocked in str(key).lower() for blocked in _BLOCKED_KEY_PARTS)
        }
    if isinstance(value, (list, tuple)):
        return [_safe_value(item, depth + 1) for item in list(value)[:25]]
    return str(value)[:300]


def safe_error_message(error: Any, limit: int = 700) -> str:
    message = str(error or "Unknown error")
    message = re.split(r"\braw response\s*:", message, flags=re.IGNORECASE)[0]
    message = re.sub(
        r"(?i)(password|token|cookie|api[_ -]?key|authorization|secret)\s*[:=]\s*\S+",
        r"\1=[redacted]",
        message,
    )
    return " ".join(message.split())[:limit] or "Unknown error"


def record_audit_event(
    db: Session,
    *,
    institution_id: str | None,
    actor_id: str | None,
    action: str,
    entity_type: str,
    entity_id: str | None = None,
    outcome: str = "success",
    details: dict | None = None,
) -> AuditLog:
    event = AuditLog(
        institution_id=institution_id,
        actor_id=actor_id,
        action=action[:100],
        entity_type=entity_type[:50],
        entity_id=entity_id,
        extra_data={
            "category": audit_category(action),
            "outcome": outcome[:30],
            "details": _safe_value(details or {}),
        },
    )
    db.add(event)
    return event


def audit_retention_days() -> int:
    try:
        return min(3650, max(30, int(os.getenv("AUDIT_RETENTION_DAYS", "180"))))
    except ValueError:
        return 180


def purge_expired_audit_logs(db: Session, now: datetime | None = None) -> int:
    cutoff = (now or datetime.now()) - timedelta(days=audit_retention_days())
    removed = db.query(AuditLog).filter(AuditLog.created_at < cutoff).delete(
        synchronize_session=False
    )
    db.commit()
    return int(removed or 0)
