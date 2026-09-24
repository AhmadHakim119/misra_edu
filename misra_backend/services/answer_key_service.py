"""Immutable approved answer-key definitions and fail-closed reference resolution."""
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
import hashlib

from sqlalchemy import func
from models import AnswerKeyVersion, ProcessingJob, Question

SETUP_DIR = Path(__file__).resolve().parents[1] / 'storage' / 'uploads' / 'exam_setup'


def resolve_document_refs(question, refs, db, *, verify_hash=False):
    if len(refs) > 5 or sum(len(ref.get('page_indices', [])) for ref in refs) > 20:
        raise ValueError('Select at most five documents and 20 reference pages in total.')
    resolved = []
    for ref in refs:
        job = db.query(ProcessingJob).filter(ProcessingJob.id == ref['job_id'],
            ProcessingJob.institution_id == question.institution_id,
            ProcessingJob.job_type == 'exam_setup').first()
        payload = (job.payload or {}) if job else {}
        if not job or job.status != 'completed' or payload.get('exam_id') != question.exam_id or job.submission_id or job.batch_id:
            raise ValueError('Reference document is not available for this assessment. Upload the answer key again.')
        documents = [(index, doc) for index, doc in enumerate(payload.get('documents', [])) if doc.get('role') == 'answer_key']
        if len(documents) != 1:
            raise ValueError('Select an import containing exactly one answer-key document.')
        index, document = documents[0]
        path = Path(document.get('path', '')).resolve()
        if path.parent != SETUP_DIR.resolve() or not path.is_file():
            raise ValueError('Answer-key reference document is missing. Upload it again and approve a new key version.')
        count = document.get('page_count')
        pages = ref.get('page_indices', [])
        if type(count) is not int or count < 1 or not pages or any(type(page) is not int or page < 0 or page >= count for page in pages):
            raise ValueError('Reference page selection is invalid. Select existing zero-based document pages.')
        try:
            with path.open('rb') as source:
                digest = hashlib.file_digest(source, 'sha256').hexdigest()
        except OSError as error:
            raise ValueError('Answer-key reference document cannot be read. Upload and approve it again.') from error
        if verify_hash and (ref.get('sha256') != digest or ref.get('document_index') != index
                or ref.get('page_count') != count or ref.get('media_type') != document.get('media_type')):
            raise ValueError('Approved answer-key document has changed. Upload it again and approve a new key version.')
        resolved.append(dict(job_id=job.id, page_indices=list(pages), document_index=index,
            path=str(path), page_count=count, media_type=document['media_type'], sha256=digest))
    return resolved


def public_version(version):
    return {field: deepcopy(getattr(version, field)) for field in (
        'id', 'question_id', 'version_number', 'status', 'mode', 'reference_text',
        'acceptable_answers', 'document_refs', 'change_summary', 'created_by',
        'approved_by', 'created_at', 'approved_at')}


def public_snapshot(snapshot):
    result = deepcopy(snapshot)
    for ref in result['document_refs']:
        ref.pop('path', None)
    return result


def _lock_question(question, db):
    db.query(Question).filter(Question.id == question.id,
        Question.institution_id == question.institution_id).with_for_update().one()


def save_draft(question, request, db, user, version=None):
    _lock_question(question, db)
    if version is not None:
        db.refresh(version)
        if version.question_id != question.id or version.status != 'draft':
            raise ValueError('Approved answer keys are immutable. Create a new draft version.')
    refs = [ref.model_dump() for ref in request.document_refs]
    resolve_document_refs(question, refs, db)
    if version is None:
        number = db.query(func.max(AnswerKeyVersion.version_number)).filter(AnswerKeyVersion.question_id == question.id).scalar() or 0
        version = AnswerKeyVersion(question_id=question.id, version_number=number + 1, status='draft', created_by=user.id)
        db.add(version)
    for field in ('mode', 'reference_text', 'acceptable_answers', 'change_summary'):
        setattr(version, field, deepcopy(getattr(request, field)))
    version.document_refs = refs
    db.flush()
    return version


def approve_key(question, version, db, user):
    _lock_question(question, db)
    db.refresh(version)
    if version.question_id != question.id or version.status != 'draft':
        raise ValueError('Only draft answer keys can be approved. Create a new draft version.')
    # Revalidate persisted data and references at the approval boundary.
    from schemas.answer_keys import AnswerKeyDraftRequest
    AnswerKeyDraftRequest(mode=version.mode, reference_text=version.reference_text,
        acceptable_answers=version.acceptable_answers, document_refs=version.document_refs,
        change_summary=version.change_summary)
    resolved = resolve_document_refs(question, version.document_refs, db)
    version.document_refs = [{key: value for key, value in ref.items() if key != 'path'} for ref in resolved]
    active = db.query(AnswerKeyVersion).filter(AnswerKeyVersion.question_id == question.id,
        AnswerKeyVersion.status == 'approved').all()
    for previous in active:
        previous.status = 'superseded'
    version.status = 'approved'
    version.approved_by = user.id
    version.approved_at = datetime.now(timezone.utc).replace(tzinfo=None)
    db.flush()
    return version


def resolve_answer_key(question, db, legacy_rubric):
    """Internal grading snapshot; paths MUST be removed before a public response.

    A draft does not replace legacy reference_context. Once any key is approved,
    absent/unavailable approved definitions must not silently fall back to legacy.
    """
    versions = db.query(AnswerKeyVersion).filter(AnswerKeyVersion.question_id == question.id)
    active = versions.filter(AnswerKeyVersion.status == 'approved').order_by(AnswerKeyVersion.version_number.desc()).first()
    if active is None:
        if versions.filter(AnswerKeyVersion.status == 'superseded').first():
            raise ValueError('No approved answer key is active. Approve a new answer-key version before grading.')
        context = (legacy_rubric or {}).get('reference_context') or ''
        alternatives = deepcopy((legacy_rubric or {}).get('acceptable_answers') or [])
        return dict(id=None, version=None, mode='reference' if context or alternatives else 'no_fixed_answer',
            reference_text=context, alternatives=alternatives, document_refs=[], is_legacy_fallback=True)
    return dict(id=active.id, version=active.version_number, mode=active.mode,
        reference_text=active.reference_text, alternatives=deepcopy(active.acceptable_answers),
        document_refs=resolve_document_refs(question, active.document_refs, db, verify_hash=True), is_legacy_fallback=False)
