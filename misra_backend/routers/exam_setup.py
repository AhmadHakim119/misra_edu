from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from sqlalchemy import or_

from database import get_db
from models import Exam, ProcessingJob, User
from services.auth_dependencies import require_instructor
from services.audit_service import record_audit_event
from services.exam_setup_service import ConfirmImport, SETUP_DIR, confirm_import, owned_exam, safe_setup_path, setup_readiness
from services.job_queue_service import dispatch_processing_job, job_to_dict
from services.upload_security_service import UploadValidationError, remove_stored_uploads, store_validated_batch

router = APIRouter(prefix='/api', tags=['assessment-setup'])


def owned_import(db, user, exam_id, job_id, lock=False):
    query = db.query(ProcessingJob).filter(ProcessingJob.id == job_id,
        ProcessingJob.institution_id == user.institution_id, ProcessingJob.job_type == 'exam_setup')
    job = query.with_for_update().first() if lock else query.first()
    if not job or (job.payload or {}).get('exam_id') != exam_id:
        raise HTTPException(404, 'Setup import not found')
    return job


def public_import(job):
    payload = job.payload or {}
    return dict(job=job_to_dict(job), questions=payload.get('draft_questions', []),
        warnings=payload.get('warnings', []), imported_question_ids=payload.get('imported_question_ids', []),
        documents=[dict(role=d['role'], page_count=d['page_count']) for d in payload.get('documents', [])])


@router.get('/exams/{exam_id}/setup-readiness')
def readiness(exam_id: str, db: Session = Depends(get_db), user: User = Depends(require_instructor)):
    owned_exam(db, user, exam_id)
    return setup_readiness(db, exam_id)


@router.post('/exams/{exam_id}/setup-imports', status_code=202)
async def upload_setup(exam_id: str, exam_file: UploadFile = File(...),
    answer_key: UploadFile | None = File(None), db: Session = Depends(get_db),
    user: User = Depends(require_instructor)):
    owned_exam(db, user, exam_id)
    stored = []
    try:
        stored = await store_validated_batch([f for f in [exam_file, answer_key] if f is not None], SETUP_DIR)
        job = ProcessingJob(institution_id=user.institution_id, requested_by=user.id,
            job_type='exam_setup', status='queued', max_attempts=3,
            progress_total=sum(s.page_count for s in stored), progress_message='Waiting for a setup worker',
            payload=dict(exam_id=exam_id, documents=[dict(path=str(s.path.resolve()),
                media_type=s.media_type, page_count=s.page_count, role='blank_exam' if i == 0 else 'answer_key')
                for i, s in enumerate(stored)]))
        db.add(job)
        db.commit()
    except Exception as error:
        db.rollback()
        remove_stored_uploads(stored)
        if isinstance(error, UploadValidationError):
            raise HTTPException(error.status_code, error.detail) from error
        raise
    finally:
        await exam_file.close()
        if answer_key is not None:
            await answer_key.close()
    dispatch_processing_job(job, db)
    record_audit_event(db, institution_id=user.institution_id, actor_id=user.id,
        action='assessment_setup_uploaded', entity_type='processing_job', entity_id=job.id,
        details={'exam_id': exam_id, 'document_count': len(stored)})
    db.commit()
    return public_import(job)


@router.get('/exams/{exam_id}/setup-imports')
def list_imports(exam_id: str, db: Session = Depends(get_db), user: User = Depends(require_instructor)):
    owned_exam(db, user, exam_id)
    # JSON exam_id is scoped as well as institution_id; never expose file paths.
    jobs = db.query(ProcessingJob).filter(ProcessingJob.institution_id == user.institution_id,
        ProcessingJob.job_type == 'exam_setup', ProcessingJob.payload['exam_id'].as_string() == exam_id,
        or_(ProcessingJob.payload['purpose'].as_string().is_(None),
            ProcessingJob.payload['purpose'].as_string() != 'answer_key_reference')
        ).order_by(ProcessingJob.created_at.desc()).limit(20).all()
    return [public_import(job) for job in jobs]


@router.get('/exams/{exam_id}/setup-imports/{job_id}')
def get_import(exam_id: str, job_id: str, db: Session = Depends(get_db), user: User = Depends(require_instructor)):
    owned_exam(db, user, exam_id)
    return public_import(owned_import(db, user, exam_id, job_id))


@router.get('/exams/{exam_id}/setup-imports/{job_id}/documents/{index}')
def get_document(exam_id: str, job_id: str, index: int, db: Session = Depends(get_db), user: User = Depends(require_instructor)):
    owned_exam(db, user, exam_id)
    job = owned_import(db, user, exam_id, job_id)
    documents = job.payload.get('documents', [])
    if index < 0 or index >= len(documents):
        raise HTTPException(404, 'Document not found')
    document = documents[index]
    path = safe_setup_path(document)
    if not path.is_file():
        raise HTTPException(410, 'Setup document is no longer available')
    return FileResponse(path, media_type=document['media_type'], headers={'X-Content-Type-Options': 'nosniff'})


@router.post('/exams/{exam_id}/setup-imports/{job_id}/confirm')
def confirm(exam_id: str, job_id: str, payload: ConfirmImport,
            db: Session = Depends(get_db), user: User = Depends(require_instructor)):
    owned_exam(db, user, exam_id)
    db.query(Exam).filter(Exam.id == exam_id).with_for_update().first()
    job = owned_import(db, user, exam_id, job_id, lock=True)
    try:
        if (job.payload or {}).get('purpose') == 'answer_key_reference':
            raise HTTPException(409, 'Reference documents do not contain extracted questions to import.')
        ids = confirm_import(job, payload, db, user)
        record_audit_event(db, institution_id=user.institution_id, actor_id=user.id,
            action='assessment_questions_imported', entity_type='exam', entity_id=exam_id,
            details={'question_count': len(ids), 'job_id': job_id})
        db.commit()
        return {'question_ids': ids, 'message': 'Questions added. Review and approve their draft rubrics next.'}
    except Exception:
        db.rollback()
        raise
