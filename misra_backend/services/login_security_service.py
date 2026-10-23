"""Database-backed login attempt budget shared by API processes."""
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy import func

from models import AuditLog
from services.audit_service import record_audit_event
from services.auth_service import keyed_hash


def record_login_attempt(db, email, address):
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    cutoff = now - timedelta(minutes=15)
    keys = {'email_hash': keyed_hash('login-email:' + email),
            'ip_hash': keyed_hash('login-ip:' + (address or 'unknown'))}
    for key, limit in (('email_hash', 10), ('ip_hash', 50)):
        count = db.query(func.count(AuditLog.id)).filter(
            AuditLog.action == 'login_attempt', AuditLog.created_at >= cutoff,
            AuditLog.extra_data['details'][key].as_string() == keys[key]).scalar() or 0
        if count >= limit:
            raise HTTPException(429, 'Too many sign-in attempts. Try again in 15 minutes.',
                                headers={'Retry-After': '900'})
    event = record_audit_event(db, institution_id=None, actor_id=None, action='login_attempt',
                              entity_type='authentication', details=keys)
    event.created_at = now  # Do not depend on the database server's local timezone.
    db.commit()
