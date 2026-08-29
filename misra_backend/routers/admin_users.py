from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from database import get_db
from models import User
from schemas.auth_input import (
    AdminCreateInstructorRequest,
    AdminResetPasswordRequest,
    AdminUpdateInstructorRequest,
)
from services.auth_dependencies import require_admin
from services.auth_service import hash_password
from services.audit_service import record_audit_event


router = APIRouter(prefix="/api/admin/instructors", tags=["instructor administration"])


def _public_instructor(user: User) -> dict:
    return {
        "id": user.id,
        "email": user.email,
        "full_name": user.full_name,
        "role": user.role,
        "is_active": user.is_active,
        "must_change_password": user.must_change_password,
        "created_at": user.created_at,
    }


def _owned_teacher(db: Session, admin: User, user_id: str) -> User:
    user = db.query(User).filter(
        User.id == user_id,
        User.institution_id == admin.institution_id,
        User.role == "teacher",
    ).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Instructor not found")
    return user


def _audit(db: Session, admin: User, action: str, target: User, extra_data: dict | None = None) -> None:
    record_audit_event(
        db,
        institution_id=admin.institution_id,
        actor_id=admin.id,
        action=action,
        entity_type="user",
        entity_id=target.id,
        details=extra_data,
    )


@router.get("")
def list_instructors(admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    users = db.query(User).filter(
        User.institution_id == admin.institution_id,
        User.role == "teacher",
    ).order_by(User.full_name, User.email).all()
    return [_public_instructor(user) for user in users]


@router.post("", status_code=201)
def create_instructor(
    payload: AdminCreateInstructorRequest,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    email = str(payload.email).strip().lower()
    if db.query(User.id).filter(func.lower(User.email) == email).first():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="That email is already in use")

    instructor = User(
        institution_id=admin.institution_id,
        email=email,
        full_name=payload.full_name.strip(),
        hashed_password=hash_password(payload.temporary_password),
        role="teacher",
        is_active=True,
        must_change_password=True,
        session_version=1,
    )
    db.add(instructor)
    db.flush()
    _audit(db, admin, "instructor_created", instructor)
    db.commit()
    db.refresh(instructor)
    return _public_instructor(instructor)


@router.patch("/{user_id}")
def update_instructor(
    user_id: str,
    payload: AdminUpdateInstructorRequest,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    instructor = _owned_teacher(db, admin, user_id)
    if instructor.is_active != payload.is_active:
        instructor.is_active = payload.is_active
        instructor.session_version = (instructor.session_version or 1) + 1
        _audit(
            db,
            admin,
            "instructor_enabled" if payload.is_active else "instructor_disabled",
            instructor,
        )
        db.commit()
        db.refresh(instructor)
    return _public_instructor(instructor)


@router.post("/{user_id}/reset-password")
def admin_reset_password(
    user_id: str,
    payload: AdminResetPasswordRequest,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    instructor = _owned_teacher(db, admin, user_id)
    instructor.hashed_password = hash_password(payload.temporary_password)
    instructor.password_changed_at = datetime.now(timezone.utc).replace(tzinfo=None)
    instructor.must_change_password = True
    instructor.session_version = (instructor.session_version or 1) + 1
    _audit(db, admin, "instructor_password_reset", instructor)
    db.commit()
    db.refresh(instructor)
    return _public_instructor(instructor)
