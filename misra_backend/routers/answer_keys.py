from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session
from database import get_db
from models import AnswerKeyVersion, ProcessingJob, Question, User
from schemas.answer_keys import AnswerKeyDraftRequest
from services.auth_dependencies import require_instructor
from services.answer_key_service import SETUP_DIR, approve_key, public_snapshot, public_version, resolve_answer_key, save_draft
from services.audit_service import record_audit_event
from services.rubric_version_service import get_effective_rubric
from services.upload_security_service import UploadValidationError, remove_stored_uploads, store_validated_batch

router = APIRouter(prefix='/api', tags=['answer-keys'])


def owned_question(db, user, question_id):
    question = db.query(Question).filter(Question.id == question_id, Question.institution_id == user.institution_id).first()
    if not question:
        raise HTTPException(404, 'Question not found')
    return question


def owned_version(db, question, version_id):
    version = db.query(AnswerKeyVersion).filter(AnswerKeyVersion.id == version_id, AnswerKeyVersion.question_id == question.id).first()
    if not version:
        raise HTTPException(404, 'Answer-key version not found')
    return version


def finish_change(db, user, version, action):
    record_audit_event(db, institution_id=user.institution_id, actor_id=user.id,
        action=action, entity_type='answer_key_version', entity_id=version.id,
        details={'question_id': version.question_id, 'version_number': version.version_number})
    db.commit()
    db.refresh(version)
    return public_version(version)


@router.get('/questions/{question_id}/answer-key-versions')
def list_versions(question_id: str, db: Session = Depends(get_db), user: User = Depends(require_instructor)):
    question = owned_question(db, user, question_id)
    return [public_version(v) for v in db.query(AnswerKeyVersion).filter(AnswerKeyVersion.question_id == question.id).order_by(AnswerKeyVersion.version_number.desc()).all()]


@router.get('/questions/{question_id}/answer-key')
def get_key(question_id: str, db: Session = Depends(get_db), user: User = Depends(require_instructor)):
    question = owned_question(db, user, question_id)
    try:
        try:
            rubric, _ = get_effective_rubric(question, db)
        except ValueError:
            rubric = {}  # Keys can be managed before a scoring rubric is approved.
        return public_snapshot(resolve_answer_key(question, db, rubric))
    except ValueError as error:
        raise HTTPException(409, str(error)) from error


@router.post('/questions/{question_id}/answer-key-versions', status_code=201)
def create_version(question_id: str, payload: AnswerKeyDraftRequest, db: Session = Depends(get_db), user: User = Depends(require_instructor)):
    question = owned_question(db, user, question_id)
    try:
        version = save_draft(question, payload, db, user)
        return finish_change(db, user, version, 'answer_key_draft_created')
    except ValueError as error:
        db.rollback()
        raise HTTPException(422, str(error)) from error


@router.put('/questions/{question_id}/answer-key-versions/{version_id}')
def edit_version(question_id: str, version_id: str, payload: AnswerKeyDraftRequest, db: Session = Depends(get_db), user: User = Depends(require_instructor)):
    question = owned_question(db, user, question_id)
    version = owned_version(db, question, version_id)
    try:
        return finish_change(db, user, save_draft(question, payload, db, user, version), 'answer_key_draft_updated')
    except ValueError as error:
        db.rollback()
        raise HTTPException(409, str(error)) from error


@router.post('/questions/{question_id}/answer-key-versions/{version_id}/approve')
def approve_version(question_id: str, version_id: str, db: Session = Depends(get_db), user: User = Depends(require_instructor)):
    question = owned_question(db, user, question_id)
    version = owned_version(db, question, version_id)
    try:
        return finish_change(db, user, approve_key(question, version, db, user), 'answer_key_approved')
    except ValueError as error:
        db.rollback()
        raise HTTPException(409, str(error)) from error


@router.post('/questions/{question_id}/answer-key-documents', status_code=201)
async def upload_document(question_id: str, file: UploadFile = File(...), db: Session = Depends(get_db), user: User = Depends(require_instructor)):
    question = owned_question(db, user, question_id)
    stored = []
    try:
        stored = await store_validated_batch([file], SETUP_DIR)
        document = stored[0]
        # This job records completed validation/ingestion only, NOT OCR extraction.
        job = ProcessingJob(institution_id=user.institution_id, requested_by=user.id,
            job_type='exam_setup', status='completed', progress_current=1, progress_total=1,
            completed_at=datetime.now(timezone.utc).replace(tzinfo=None),
            progress_message='Reference document stored; no extraction requested',
            payload=dict(exam_id=question.exam_id, purpose='answer_key_reference', documents=[dict(
                role='answer_key', path=str(document.path.resolve()), media_type=document.media_type, page_count=document.page_count)]))
        db.add(job)
        db.flush()
        record_audit_event(db, institution_id=user.institution_id, actor_id=user.id,
            action='answer_key_document_uploaded', entity_type='processing_job', entity_id=job.id,
            details={'question_id': question.id, 'exam_id': question.exam_id})
        db.commit()
        return dict(job_id=job.id, document_index=0, page_count=document.page_count, media_type=document.media_type)
    except Exception as error:
        db.rollback()
        remove_stored_uploads(stored)
        if isinstance(error, UploadValidationError):
            raise HTTPException(error.status_code, error.detail) from error
        raise
    finally:
        await file.close()
