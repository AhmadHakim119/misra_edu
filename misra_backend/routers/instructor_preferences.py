from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from database import get_db
from models import InstructorPreferenceVersion, User
from schemas.instructor_preferences import (
    InstructorPreferenceDraftRequest,
    InstructorPreferenceSuggestionsResponse,
)
from services.audit_service import record_audit_event
from services.auth_dependencies import require_instructor
from services.instructor_preference_service import (
    approve_draft,
    public_version,
    repeated_decision_suggestions,
    save_draft,
)


router = APIRouter(prefix="/api", tags=["instructor-preferences"])


def _owned_version(db: Session, user: User, version_id: str) -> InstructorPreferenceVersion:
    version = (
        db.query(InstructorPreferenceVersion)
        .filter(
            InstructorPreferenceVersion.id == version_id,
            InstructorPreferenceVersion.institution_id == user.institution_id,
            InstructorPreferenceVersion.user_id == user.id,
        )
        .first()
    )
    if not version:
        # A uniform 404 prevents disclosing whether another instructor has a
        # preference profile with this identifier.
        raise HTTPException(status_code=404, detail="Preference profile version not found")
    return version


def _finish(db: Session, user: User, version: InstructorPreferenceVersion, action: str):
    record_audit_event(
        db,
        institution_id=user.institution_id,
        actor_id=user.id,
        action=action,
        entity_type="instructor_preference_version",
        entity_id=version.id,
        details={
            "version_number": version.version_number,
            "status": version.status,
            "applies_automatically": False,
        },
    )
    db.commit()
    db.refresh(version)
    return public_version(version)


@router.get("/instructor-preference-versions")
def list_versions(
    db: Session = Depends(get_db),
    user: User = Depends(require_instructor),
):
    versions = (
        db.query(InstructorPreferenceVersion)
        .filter(
            InstructorPreferenceVersion.institution_id == user.institution_id,
            InstructorPreferenceVersion.user_id == user.id,
        )
        .order_by(InstructorPreferenceVersion.version_number.desc())
        .all()
    )
    return [public_version(version) for version in versions]


@router.get(
    "/instructor-preference-suggestions",
    response_model=InstructorPreferenceSuggestionsResponse,
    response_model_exclude_none=True,
)
def list_suggestions(
    db: Session = Depends(get_db),
    user: User = Depends(require_instructor),
):
    return repeated_decision_suggestions(db, user)


@router.post("/instructor-preference-versions", status_code=201)
def create_version(
    payload: InstructorPreferenceDraftRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_instructor),
):
    try:
        version = save_draft(payload, db, user)
        return _finish(db, user, version, "instructor_preference_draft_created")
    except ValueError as error:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.put("/instructor-preference-versions/{version_id}")
def update_version(
    version_id: str,
    payload: InstructorPreferenceDraftRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_instructor),
):
    version = _owned_version(db, user, version_id)
    try:
        version = save_draft(payload, db, user, version)
        return _finish(db, user, version, "instructor_preference_draft_updated")
    except ValueError as error:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.post("/instructor-preference-versions/{version_id}/approve")
def approve_version(
    version_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_instructor),
):
    version = _owned_version(db, user, version_id)
    try:
        version = approve_draft(version, db, user)
        return _finish(db, user, version, "instructor_preference_approved")
    except ValueError as error:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(error)) from error
