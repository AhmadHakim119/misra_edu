"""Versioned assessment defaults, explicit question exceptions and legacy fallback."""
import json
from datetime import datetime, timezone

from sqlalchemy import func, inspect
from models import AssessmentMaterialScopeVersion, QuestionMaterialScopeVersion, Exam
from schemas.course_materials import AssessmentMaterialScopeRequest
from services.course_material_service import text_hash, scope_hash, validate_exam_bindings


def schema_available(db):
    return inspect(db.connection()).has_table(AssessmentMaterialScopeVersion.__tablename__)


def assessment_scope_hash(scope):
    return text_hash(json.dumps({"exam_id": scope.exam_id, "mode": scope.mode, "bindings": scope.bindings},
        sort_keys=True, ensure_ascii=False, separators=(",", ":")))


def public_scope(scope):
    return {"id": scope.id, "version_number": scope.version_number, "status": scope.status,
        "mode": scope.mode, "bindings": scope.bindings, "scope_sha256": scope.scope_sha256,
        "approved_at": scope.approved_at}


def save_default(db, exam, request, user):
    db.query(Exam).filter(Exam.id == exam.id).with_for_update().one()
    validate_exam_bindings(db, exam, request)
    number = db.query(func.max(AssessmentMaterialScopeVersion.version_number)).filter(
        AssessmentMaterialScopeVersion.exam_id == exam.id).scalar() or 0
    scope = AssessmentMaterialScopeVersion(exam_id=exam.id, version_number=number + 1,
        mode=request.mode, bindings=[b.model_dump() for b in request.bindings], created_by=user.id)
    db.add(scope)
    db.flush()
    return scope


def approve_default(db, exam, scope, user):
    db.query(Exam).filter(Exam.id == exam.id).with_for_update().one()
    db.refresh(scope)
    if scope.status != "draft" or scope.exam_id != exam.id:
        raise ValueError("Only a draft assessment source default can be approved.")
    request = AssessmentMaterialScopeRequest(mode=scope.mode, bindings=scope.bindings)
    validate_exam_bindings(db, exam, request)
    for old in db.query(AssessmentMaterialScopeVersion).filter(
        AssessmentMaterialScopeVersion.exam_id == exam.id, AssessmentMaterialScopeVersion.status == "approved").all():
        old.status = "superseded"
    scope.status, scope.approved_by = "approved", user.id
    scope.scope_sha256 = assessment_scope_hash(scope)
    scope.approved_at = datetime.now(timezone.utc).replace(tzinfo=None)
    db.flush()
    return scope


def active_scope(query, model):
    scope = query.filter(model.status == "approved").order_by(model.version_number.desc()).first()
    if scope is None and query.filter(model.status == "superseded").first():
        raise ValueError("No approved course-reference scope is active. Approve one before grading.")
    return scope


def resolve_scope(db, question):
    """A draft never changes grading. Approved `inherit` deliberately clears an exception."""
    override = active_scope(db.query(QuestionMaterialScopeVersion).filter(
        QuestionMaterialScopeVersion.question_id == question.id), QuestionMaterialScopeVersion)
    if override is not None:
        if override.scope_sha256 != scope_hash(override):
            raise ValueError("Approved source scope changed. Approve a new scope before grading.")
        if override.mode != "inherit":
            return override, "question", override
        if override.bindings:
            raise ValueError("Inherited source scope cannot contain bindings.")
    # Installing the new table is optional for pre-existing question-only assessments.
    if not schema_available(db):
        return None, "not_configured", override
    scope = active_scope(db.query(AssessmentMaterialScopeVersion).filter(
        AssessmentMaterialScopeVersion.exam_id == question.exam_id), AssessmentMaterialScopeVersion)
    if scope is not None and scope.scope_sha256 != assessment_scope_hash(scope):
        raise ValueError("Approved assessment source default changed. Approve a new version before grading.")
    return scope, "assessment" if scope else "not_configured", override
