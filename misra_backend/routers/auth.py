from __future__ import annotations

from datetime import datetime, timezone
import secrets

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, Response, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from database import get_db
from models import User, Institution, InstructorAccountSettings, PasswordResetToken, ProcessingJob
from schemas.auth_input import AccountSettingsRequest, AccountSettingsResponse, DeleteAccountRequest, ChangePasswordRequest, ForgotPasswordRequest, LoginRequest, ResetPasswordRequest
from services.account_settings_service import account_settings, public_settings
from services.auth_dependencies import authenticated_instructor
from services.auth_service import (
    CSRF_COOKIE,
    SESSION_COOKIE,
    cookie_secure,
    create_csrf_token,
    create_session_token,
    hash_password,
    dummy_password_hash,
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
def login(payload: LoginRequest, request: Request, response: Response, db: Session = Depends(get_db)):
    email = payload.email.strip().lower()
    from services.login_security_service import record_login_attempt
    record_login_attempt(db, email, request.client.host if request.client else None)
    users = db.query(User).filter(func.lower(User.email) == email).limit(2).all()
    candidate = users[0] if len(users) == 1 and users[0].is_active else None
    password_valid = verify_password(payload.password, candidate.hashed_password if candidate else dummy_password_hash())
    if not candidate or not password_valid:
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


@router.get("/settings", response_model=AccountSettingsResponse)
def get_account_settings(user: User = Depends(authenticated_instructor), db: Session = Depends(get_db)):
    return public_settings(db, user)


@router.put("/settings", response_model=AccountSettingsResponse)
def update_account_settings(payload: AccountSettingsRequest, user: User = Depends(authenticated_instructor), db: Session = Depends(get_db)):
    db.query(User).filter_by(id=user.id).with_for_update().populate_existing().first()
    if not user.is_active:
        raise HTTPException(401, "Sign in required")
    settings = account_settings(db, user, lock=True)
    if not settings:
        settings = InstructorAccountSettings(user_id=user.id, institution_id=user.institution_id)
        db.add(settings)
    settings.use_marking_preferences = payload.use_marking_preferences
    record_audit_event(db, institution_id=user.institution_id, actor_id=user.id,
        action="account_settings_updated", entity_type="user", entity_id=user.id,
        details={"use_marking_preferences": payload.use_marking_preferences})
    db.commit()
    return public_settings(db, user)


@router.delete("/account", status_code=204)
def delete_account(payload: DeleteAccountRequest, response: Response,
    user: User = Depends(authenticated_instructor), db: Session = Depends(get_db)):
    # Serialize administrator self-deletions within an institution.
    db.query(Institution).filter_by(id=user.institution_id).with_for_update().first()
    db.query(User).filter_by(id=user.id).with_for_update().populate_existing().first()
    if not user.is_active or not verify_password(payload.current_password, user.hashed_password):
        raise HTTPException(400, "Current password is incorrect")
    if user.role == "admin" and db.query(User).filter(User.institution_id == user.institution_id,
        User.role == "admin", User.is_active.is_(True), User.id != user.id).with_for_update().first() is None:
        raise HTTPException(409, "You are the last active administrator. Another active administrator is required before deleting this account.")
    if db.query(ProcessingJob.id).filter(ProcessingJob.institution_id == user.institution_id,
        ProcessingJob.requested_by == user.id, ProcessingJob.status.in_(["queued", "processing", "retrying"])).first():
        raise HTTPException(409, "Your background tasks are still running. Wait for them to finish before deleting your account.")
    settings = account_settings(db, user, lock=True)
    if not settings:
        settings = InstructorAccountSettings(user_id=user.id, institution_id=user.institution_id)
        db.add(settings)
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    settings.deleted_at = now
    settings.use_marking_preferences = False
    user.is_active = False
    user.session_version = (user.session_version or 1) + 1
    user.full_name = "Deleted instructor"
    user.email = f"deleted-{user.id}@deleted.invalid"
    user.hashed_password = hash_password(secrets.token_urlsafe(48))
    user.must_change_password = False
    db.query(PasswordResetToken).filter(PasswordResetToken.user_id == user.id,
        PasswordResetToken.used_at.is_(None)).update({PasswordResetToken.used_at: now}, synchronize_session=False)
    record_audit_event(db, institution_id=user.institution_id, actor_id=user.id,
        action="account_deleted", entity_type="user", entity_id=user.id,
        details={"academic_history_retained": True})
    db.commit()
    _clear_auth_cookies(response)


@router.post("/logout", status_code=204)
def logout(request: Request, response: Response, db: Session = Depends(get_db)):
    token = request.cookies.get(SESSION_COOKIE)
    session = read_session_token(token) if token else None
    user = db.query(User).filter(User.id == session.user_id).first() if session else None
    if user and user.is_active and user.session_version == session.session_version:
        # Validate CSRF before invalidating credentials. The version revokes
        # existing sessions on all devices, including copies of this cookie.
        authenticated_instructor(request, db)
        db.refresh(user, with_for_update=True)
        user.session_version = (user.session_version or 1) + 1
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
