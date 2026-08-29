from __future__ import annotations

import hmac

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from database import get_db
from models import User
from services.auth_service import CSRF_COOKIE, SESSION_COOKIE, read_session_token
from services.audit_service import record_audit_event


SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def authenticated_instructor(request: Request, db: Session = Depends(get_db)) -> User:
    claims = read_session_token(request.cookies.get(SESSION_COOKIE))
    if not claims:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Sign in required")

    user = db.query(User).filter(User.id == claims.user_id).first()
    if not user or not user.is_active or user.session_version != claims.session_version:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Sign in required")
    if user.role not in {"teacher", "admin"}:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Instructor access required")

    if request.method.upper() not in SAFE_METHODS:
        cookie_token = request.cookies.get(CSRF_COOKIE, "")
        header_token = request.headers.get("X-CSRF-Token", "")
        if not cookie_token or not hmac.compare_digest(cookie_token, header_token):
            record_audit_event(
                db,
                institution_id=user.institution_id,
                actor_id=user.id,
                action="csrf_validation_failed",
                entity_type="request",
                outcome="failure",
                details={"method": request.method.upper(), "path": request.url.path},
            )
            db.commit()
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid CSRF token")

    return user


def require_instructor(user: User = Depends(authenticated_instructor)) -> User:
    if user.must_change_password:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "password_change_required",
                "message": "Change your temporary password before continuing.",
            },
        )
    return user


def require_admin(
    request: Request,
    user: User = Depends(require_instructor),
    db: Session = Depends(get_db),
) -> User:
    if user.role != "admin":
        record_audit_event(
            db,
            institution_id=user.institution_id,
            actor_id=user.id,
            action="admin_access_denied",
            entity_type="request",
            outcome="failure",
            details={"method": request.method.upper(), "path": request.url.path},
        )
        db.commit()
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Administrator access required")
    return user
