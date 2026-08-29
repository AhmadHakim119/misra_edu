from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, Response, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from database import get_db
from models import User
from schemas.auth_input import ChangePasswordRequest, ForgotPasswordRequest, LoginRequest, ResetPasswordRequest
from services.auth_dependencies import authenticated_instructor
from services.auth_service import (
    CSRF_COOKIE,
    SESSION_COOKIE,
    cookie_secure,
    create_csrf_token,
    create_session_token,
    hash_password,
    read_session_token,
    verify_password,
)
from services.audit_service import record_audit_event
from services.password_recovery_service import (
    GENERIC_RESET_MESSAGE,
    consume_password_reset,
    request_password_reset,
    send_password_reset_email,
)


router = APIRouter(prefix="/api/auth", tags=["authentication"])


def _public_user(user: User) -> dict:
    return {
        "id": user.id,
        "institution_id": user.institution_id,
        "email": user.email,
        "full_name": user.full_name,
        "role": user.role,
        "is_active": user.is_active,
        "must_change_password": user.must_change_password,
    }


def _clear_auth_cookies(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/")
    response.delete_cookie(CSRF_COOKIE, path="/")


@router.post("/login")
def login(payload: LoginRequest, response: Response, db: Session = Depends(get_db)):
    email = payload.email.strip().lower()
    users = db.query(User).filter(func.lower(User.email) == email).limit(2).all()
    if len(users) != 1 or not users[0].is_active or not verify_password(payload.password, users[0].hashed_password):
        candidate = users[0] if len(users) == 1 else None
        record_audit_event(
            db,
            institution_id=candidate.institution_id if candidate else None,
            actor_id=candidate.id if candidate else None,
            action="login_failed",
            entity_type="user",
            entity_id=candidate.id if candidate else None,
            outcome="failure",
            details={
                "reason": "inactive_account" if candidate and not candidate.is_active else "invalid_credentials",
            },
        )
        db.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")

    token, max_age = create_session_token(
        users[0].id,
        payload.remember,
        session_version=users[0].session_version,
    )
    csrf_token = create_csrf_token()
    secure = cookie_secure()
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=max_age,
        httponly=True,
        secure=secure,
        samesite="strict",
        path="/",
    )
    response.set_cookie(
        CSRF_COOKIE,
        csrf_token,
        max_age=max_age,
        httponly=False,
        secure=secure,
        samesite="strict",
        path="/",
    )
    record_audit_event(
        db,
        institution_id=users[0].institution_id,
        actor_id=users[0].id,
        action="login_succeeded",
        entity_type="user",
        entity_id=users[0].id,
        details={"remember_session": payload.remember},
    )
    db.commit()
    return {"ok": True, "user": _public_user(users[0])}


@router.get("/me")
def current_user(user: User = Depends(authenticated_instructor)):
    return _public_user(user)


@router.post("/logout", status_code=204)
def logout(request: Request, response: Response, db: Session = Depends(get_db)):
    token = request.cookies.get(SESSION_COOKIE)
    session = read_session_token(token) if token else None
    user = db.query(User).filter(User.id == session.user_id).first() if session else None
    if user:
        record_audit_event(
            db,
            institution_id=user.institution_id,
            actor_id=user.id,
            action="logout_succeeded",
            entity_type="user",
            entity_id=user.id,
        )
        db.commit()
    _clear_auth_cookies(response)


@router.post("/change-password", status_code=204)
def change_password(
    payload: ChangePasswordRequest,
    response: Response,
    user: User = Depends(authenticated_instructor),
    db: Session = Depends(get_db),
):
    if not verify_password(payload.current_password, user.hashed_password):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Current password is incorrect")

    user.hashed_password = hash_password(payload.new_password)
    user.password_changed_at = datetime.now(timezone.utc).replace(tzinfo=None)
    user.must_change_password = False
    user.session_version = (user.session_version or 1) + 1
    record_audit_event(
        db,
        institution_id=user.institution_id,
        actor_id=user.id,
        action="password_changed",
        entity_type="user",
        entity_id=user.id,
    )
    db.commit()
    _clear_auth_cookies(response)


@router.post("/forgot-password", status_code=202)
def forgot_password(
    payload: ForgotPasswordRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    request_ip = request.client.host if request.client else None
    delivery = request_password_reset(db, str(payload.email), request_ip)
    if delivery:
        user = db.query(User).filter(func.lower(User.email) == delivery.email.lower()).first()
        if user:
            record_audit_event(
                db,
                institution_id=user.institution_id,
                actor_id=user.id,
                action="password_reset_requested",
                entity_type="user",
                entity_id=user.id,
            )
            db.commit()
        background_tasks.add_task(send_password_reset_email, delivery)
    return {"message": GENERIC_RESET_MESSAGE}


@router.post("/reset-password", status_code=204)
def reset_password(payload: ResetPasswordRequest, db: Session = Depends(get_db)):
    user = consume_password_reset(db, payload.token, hash_password(payload.new_password))
    if not user:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This password reset link is invalid or has expired",
        )
    record_audit_event(
        db,
        institution_id=user.institution_id,
        actor_id=user.id,
        action="password_reset_completed",
        entity_type="user",
        entity_id=user.id,
    )
    db.commit()
