"""Instructor-facing approved reference library, separate from student uploads."""
from dataclasses import replace
import hashlib
import os

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from database import get_db
from models import Course, CourseMaterial, MaterialVersion, MaterialPage, MaterialChunk, ProcessingJob, Question, QuestionMaterialScopeVersion, AssessmentMaterialScopeVersion, Exam, User, RubricVersion
from schemas.course_materials import MaterialTextRequest, MaterialPageEdit, MaterialApprovalRequest, MaterialScopeRequest, AssessmentMaterialScopeRequest
from services import course_material_service as service
from services import assessment_source_service as defaults
from services.auth_dependencies import require_instructor
from services.audit_service import record_audit_event
from services.job_queue_service import dispatch_processing_job
from services.rubric_version_service import get_effective_rubric
from services.upload_security_service import UploadValidationError, remove_stored_uploads, store_validated_upload, upload_limits

router = APIRouter(prefix="/api", tags=["course-materials"])


def ready(db):
    if not service.schema_available(db):
        raise HTTPException(503, "Course materials need the additive database upgrade. Back up, then run scripts/upgrade_course_materials.py.")


def owned_course(db, user, course_id, lock=False):
    query = db.query(Course).filter(Course.id == course_id, Course.institution_id == user.institution_id)
    course = query.with_for_update().first() if lock else query.first()
    if not course:
        raise HTTPException(404, "Course not found")
    return course


def owned_material(db, user, material_id):
    ready(db)
    material = db.query(CourseMaterial).filter(CourseMaterial.id == material_id, CourseMaterial.institution_id == user.institution_id).first()
    if not material:
        raise HTTPException(404, "Course material not found")
    owned_course(db, user, material.course_id)
    return material


def owned_version(db, material, version_id):
    version = db.query(MaterialVersion).filter(MaterialVersion.id == version_id, MaterialVersion.material_id == material.id).first()
    if not version:
        raise HTTPException(404, "Reference version not found")
    return version


def owned_question(db, user, question_id):
    question = db.query(Question).filter(Question.id == question_id, Question.institution_id == user.institution_id).first()
    if not question:
        raise HTTPException(404, "Question not found")
    return question


def owned_exam(db, user, exam_id):
    exam = db.query(Exam).filter(Exam.id == exam_id, Exam.institution_id == user.institution_id).first()
    if not exam:
        raise HTTPException(404, "Assessment not found")
    return exam


def defaults_ready(db):
    ready(db)
    if not defaults.schema_available(db):
        raise HTTPException(503, "Assessment source defaults need an additive upgrade. Back up, then run scripts/upgrade_assessment_sources.py.")


def public_material(db, material):
    return {"id":material.id, "course_id":material.course_id, "title":material.title,
        "versions":[service.public_version(db, version) for version in db.query(MaterialVersion).filter(MaterialVersion.material_id == material.id).order_by(MaterialVersion.version_number.desc()).all()]}


def finish(db, user, entity, action):
    record_audit_event(db, institution_id=user.institution_id, actor_id=user.id, action=action,
        entity_type="course_material", entity_id=entity.id, details={})
    db.commit()


@router.get("/courses/{course_id}/materials")
def list_materials(course_id: str, db: Session = Depends(get_db), user: User = Depends(require_instructor)):
    owned_course(db, user, course_id)
    ready(db)
    return [public_material(db, m) for m in db.query(CourseMaterial).filter(CourseMaterial.course_id == course_id,
        CourseMaterial.institution_id == user.institution_id).order_by(CourseMaterial.created_at.desc()).limit(200).all()]


@router.post("/courses/{course_id}/materials/text", status_code=201)
def create_text(course_id: str, payload: MaterialTextRequest, db: Session = Depends(get_db), user: User = Depends(require_instructor)):
    owned_course(db, user, course_id, lock=True)
    ready(db)
    material = CourseMaterial(course_id=course_id, institution_id=user.institution_id, title=payload.title, created_by=user.id)
    db.add(material)
    db.flush()
    version = service.new_version(db, material, user, media_type="text/plain", document_sha256=service.text_hash(payload.text), page_count=1)
    service.replace_page(db, version, 0, payload.text, origin="instructor_text")
    version.ingestion_status, version.parser_version = "ready", "instructor-text/page-chars-v1"
    version.content_sha256 = service.content_hash(db, version)
    finish(db, user, material, "course_material_text_created")
    return public_material(db, material)


async def store_pdf(db, user, course, file, title, material=None):
    ready(db)
    stored = []
    try:
        limits = replace(upload_limits(), max_pdf_pages=max(1, min(1000, int(os.getenv("MAX_MATERIAL_PDF_PAGES", "1000")))))
        item = await store_validated_upload(file, service.MATERIAL_DIR, limits=limits)
        stored.append(item)
        if item.media_type != "application/pdf":
            raise UploadValidationError(415, "Course references currently accept PDF files or typed text. Images require transcription first.")
        if material is None:
            display_title = (title or item.original_filename).strip()
            if not display_title or len(display_title) > 255:
                raise UploadValidationError(422, "Reference title must contain 1-255 characters.")
            material = CourseMaterial(course_id=course.id, institution_id=user.institution_id, title=display_title, created_by=user.id)
            db.add(material)
            db.flush()
        with item.path.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        version = service.new_version(db, material, user, media_type=item.media_type,
            document_sha256=digest, page_count=item.page_count, path=item.path)
        job = ProcessingJob(institution_id=user.institution_id, requested_by=user.id, job_type="material_ingestion",
            status="queued", progress_total=item.page_count, progress_message="Waiting to read course reference", max_attempts=3,
            payload={"material_version_id":version.id, "material_id":material.id, "course_id":course.id})
        db.add(job)
        db.flush()
        version.processing_job_id = job.id
        finish(db, user, material, "course_material_uploaded")
    except Exception as error:
        db.rollback()
        remove_stored_uploads(stored)
        if isinstance(error, UploadValidationError):
            raise HTTPException(error.status_code, error.detail) from error
        raise
    dispatch_processing_job(job, db)
    return public_material(db, material)


@router.post("/courses/{course_id}/materials", status_code=202)
async def upload_material(course_id: str, file: UploadFile = File(...), title: str | None = Form(None),
    db: Session = Depends(get_db), user: User = Depends(require_instructor)):
    try:
        course = owned_course(db, user, course_id, lock=True)
        return await store_pdf(db, user, course, file, title)
    finally:
        await file.close()


@router.post("/materials/{material_id}/versions", status_code=202)
async def upload_revision(material_id: str, file: UploadFile = File(...), db: Session = Depends(get_db), user: User = Depends(require_instructor)):
    try:
        material = owned_material(db, user, material_id)
        course = owned_course(db, user, material.course_id, lock=True)
        return await store_pdf(db, user, course, file, material.title, material)
    finally:
        await file.close()


@router.get("/materials/{material_id}/versions/{version_id}/pages")
def get_pages(material_id: str, version_id: str, offset: int = Query(0, ge=0), limit: int = Query(10, ge=1, le=20),
    db: Session = Depends(get_db), user: User = Depends(require_instructor)):
    material = owned_material(db, user, material_id)
    version = owned_version(db, material, version_id)
    pages = db.query(MaterialPage).filter(MaterialPage.version_id == version.id).order_by(MaterialPage.page_index).offset(offset).limit(limit).all()
    return {"version":service.public_version(db, version), "items":[{"page_index":p.page_index,
        "printed_page_label":p.printed_page_label, "text":p.text, "text_sha256":p.text_sha256, "origin":p.origin,
        "chunks":[{"id":c.id,"char_start":c.char_start,"char_end":c.char_end} for c in db.query(MaterialChunk).filter(
            MaterialChunk.version_id == version.id, MaterialChunk.page_index == p.page_index).order_by(MaterialChunk.ordinal).all()]} for p in pages]}


@router.put("/materials/{material_id}/versions/{version_id}/pages/{page_index}")
def edit_page(material_id: str, version_id: str, page_index: int, payload: MaterialPageEdit,
    db: Session = Depends(get_db), user: User = Depends(require_instructor)):
    material = owned_material(db, user, material_id)
    version = owned_version(db, material, version_id)
    db.query(MaterialVersion).filter(MaterialVersion.id == version.id).with_for_update().one()
    db.refresh(version)
    page = db.query(MaterialPage).filter(MaterialPage.version_id == version.id, MaterialPage.page_index == page_index).first()
    if not page:
        raise HTTPException(404, "Reference page not found")
    if version.status != "draft" or version.ingestion_status not in {"ready", "needs_transcription"}:
        raise HTTPException(409, "Only an ingested draft can be edited; approved content is immutable.")
    if page.text_sha256 != payload.expected_text_sha256:
        raise HTTPException(409, "This page changed. Reload it before saving your correction.")
    service.replace_page(db, version, page_index, payload.text, origin="instructor_corrected", printed_page_label=payload.printed_page_label)
    version.content_sha256 = service.content_hash(db, version)
    finish(db, user, material, "course_material_page_corrected")
    return service.public_version(db, version)


@router.post("/materials/{material_id}/versions/{version_id}/approve")
def approve_version(material_id: str, version_id: str, payload: MaterialApprovalRequest,
    db: Session = Depends(get_db), user: User = Depends(require_instructor)):
    material = owned_material(db, user, material_id)
    version = owned_version(db, material, version_id)
    try:
        service.approve_material(db, version, payload, user)
        finish(db, user, material, "course_material_approved")
        return service.public_version(db, version)
    except ValueError as error:
        db.rollback()
        raise HTTPException(409, str(error)) from error


@router.get("/materials/{material_id}/versions/{version_id}/document")
def get_document(material_id: str, version_id: str, db: Session = Depends(get_db), user: User = Depends(require_instructor)):
    material = owned_material(db, user, material_id)
    version = owned_version(db, material, version_id)
    try:
        return FileResponse(service.document_path(version), media_type=version.media_type, headers={"X-Content-Type-Options":"nosniff"})
    except ValueError as error:
        raise HTTPException(410, str(error)) from error


def current_rubric(db, question, allow_draft=False):
    if allow_draft:
        draft = db.query(RubricVersion).filter(RubricVersion.question_id == question.id,
            RubricVersion.status == 'draft').order_by(RubricVersion.version_number.desc()).first()
        if draft:
            from services.rubric_version_service import validate_rubric_v2
            return validate_rubric_v2(draft.rubric_json).model_dump()
    try:
        return get_effective_rubric(question, db)[0]
    except ValueError as error:
        raise HTTPException(409, "Approve the question rubric before configuring source retrieval.") from error


@router.get("/questions/{question_id}/material-scopes")
def list_scopes(question_id: str, db: Session = Depends(get_db), user: User = Depends(require_instructor)):
    question = owned_question(db, user, question_id)
    ready(db)
    return [{"id":s.id,"version_number":s.version_number,"status":s.status,"mode":s.mode,"bindings":s.bindings,
        "scope_sha256":s.scope_sha256,"approved_at":s.approved_at} for s in db.query(QuestionMaterialScopeVersion).filter(
        QuestionMaterialScopeVersion.question_id == question.id).order_by(QuestionMaterialScopeVersion.version_number.desc()).all()]


@router.post("/questions/{question_id}/material-scopes", status_code=201)
def create_scope(question_id: str, payload: MaterialScopeRequest, db: Session = Depends(get_db), user: User = Depends(require_instructor)):
    question = owned_question(db, user, question_id)
    ready(db)
    try:
        scope = service.save_scope(db, question, payload, user, current_rubric(db, question, allow_draft=True))
        finish(db, user, scope, "question_material_scope_drafted")
        return {"id":scope.id,"status":scope.status,"version_number":scope.version_number}
    except ValueError as error:
        db.rollback()
        raise HTTPException(422, str(error)) from error


@router.post("/questions/{question_id}/material-scopes/{scope_id}/approve")
def approve_scope(question_id: str, scope_id: str, db: Session = Depends(get_db), user: User = Depends(require_instructor)):
    question = owned_question(db, user, question_id)
    ready(db)
    scope = db.query(QuestionMaterialScopeVersion).filter(QuestionMaterialScopeVersion.id == scope_id,
        QuestionMaterialScopeVersion.question_id == question.id).first()
    if not scope:
        raise HTTPException(404, "Reference scope not found")
    try:
        service.approve_scope(db, question, scope, user, current_rubric(db, question))
        finish(db, user, scope, "question_material_scope_approved")
        return {"id":scope.id,"status":scope.status,"version_number":scope.version_number}
    except ValueError as error:
        db.rollback()
        raise HTTPException(409, str(error)) from error


@router.get("/questions/{question_id}/material-retrieval-preview")
def retrieval_preview(question_id: str, db: Session = Depends(get_db), user: User = Depends(require_instructor)):
    from services.material_retrieval_service import retrieve_for_question
    question = owned_question(db, user, question_id)
    ready(db)
    try:
        return retrieve_for_question(db, question, current_rubric(db, question))
    except ValueError as error:
        raise HTTPException(409, str(error)) from error


def effective_scope(db, question):
    scope, origin, override = defaults.resolve_scope(db, question)
    return {"question_id": question.id, "question_number": question.question_number,
        "origin": origin, "scope": defaults.public_scope(scope) if scope else None,
        "question_scope_version_id": override.id if override else None}


@router.get("/questions/{question_id}/effective-material-scope")
def get_effective_scope(question_id: str, db: Session = Depends(get_db), user: User = Depends(require_instructor)):
    question = owned_question(db, user, question_id)
    ready(db)
    try:
        return effective_scope(db, question)
    except ValueError as error:
        raise HTTPException(409, str(error)) from error


@router.get("/exams/{exam_id}/material-scopes")
def list_assessment_scopes(exam_id: str, db: Session = Depends(get_db), user: User = Depends(require_instructor)):
    exam = owned_exam(db, user, exam_id)
    defaults_ready(db)
    versions = db.query(AssessmentMaterialScopeVersion).filter(AssessmentMaterialScopeVersion.exam_id == exam.id).order_by(
        AssessmentMaterialScopeVersion.version_number.desc()).all()
    questions = db.query(Question).filter(Question.exam_id == exam.id, Question.institution_id == user.institution_id).order_by(Question.order_index).all()
    effective = []
    for question in questions:
        try:
            effective.append(effective_scope(db, question))
        except ValueError as error:
            effective.append({"question_id": question.id, "question_number": question.question_number, "origin": "blocked", "error": str(error)})
    return {"exam_id": exam.id, "versions": [defaults.public_scope(s) for s in versions], "questions": effective}


@router.post("/exams/{exam_id}/material-scopes", status_code=201)
def create_assessment_scope(exam_id: str, payload: AssessmentMaterialScopeRequest,
    db: Session = Depends(get_db), user: User = Depends(require_instructor)):
    exam = owned_exam(db, user, exam_id)
    defaults_ready(db)
    try:
        scope = defaults.save_default(db, exam, payload, user)
        record_audit_event(db, institution_id=user.institution_id, actor_id=user.id,
            action="assessment_material_scope_drafted", entity_type="exam", entity_id=exam.id, details={"scope_version_id": scope.id})
        db.commit()
        return defaults.public_scope(scope)
    except ValueError as error:
        db.rollback()
        raise HTTPException(422, str(error)) from error


@router.post("/exams/{exam_id}/material-scopes/{scope_id}/approve")
def approve_assessment_scope(exam_id: str, scope_id: str,
    db: Session = Depends(get_db), user: User = Depends(require_instructor)):
    exam = owned_exam(db, user, exam_id)
    defaults_ready(db)
    scope = db.query(AssessmentMaterialScopeVersion).filter(AssessmentMaterialScopeVersion.id == scope_id,
        AssessmentMaterialScopeVersion.exam_id == exam.id).first()
    if not scope:
        raise HTTPException(404, "Assessment source default not found")
    try:
        defaults.approve_default(db, exam, scope, user)
        record_audit_event(db, institution_id=user.institution_id, actor_id=user.id,
            action="assessment_material_scope_approved", entity_type="exam", entity_id=exam.id, details={"scope_version_id": scope.id})
        db.commit()
        return defaults.public_scope(scope)
    except ValueError as error:
        db.rollback()
        raise HTTPException(409, str(error)) from error
