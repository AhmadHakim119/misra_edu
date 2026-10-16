"""Local document ingestion, explicit approvals, and immutable source integrity."""
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import pypdf
from sqlalchemy import func, inspect
from models import CourseMaterial, MaterialVersion, MaterialPage, MaterialChunk, QuestionMaterialScopeVersion, Exam, Course, Question
from schemas.course_materials import MaterialScopeRequest

MATERIAL_DIR = Path(__file__).resolve().parents[1] / "storage" / "uploads" / "course_materials"
MATERIAL_TABLES = (CourseMaterial, MaterialVersion, MaterialPage, MaterialChunk, QuestionMaterialScopeVersion)
MAX_EXTRACTED_CHARS = 5_000_000


def schema_available(db):
    inspector = inspect(db.connection())
    return all(inspector.has_table(model.__tablename__) for model in MATERIAL_TABLES)


def text_hash(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def document_path(version, *, verify_hash=True):
    path = Path(version.original_file_path or "").resolve()
    if path.parent != MATERIAL_DIR.resolve() or not path.is_file():
        raise ValueError("Reference document is missing. Upload a new material version.")
    if verify_hash:
        with path.open("rb") as stream:
            if hashlib.file_digest(stream, "sha256").hexdigest() != version.document_sha256:
                raise ValueError("Reference document changed. Upload and approve a new material version.")
    return path


def chunks_for_text(text, max_chars=1600, overlap=180):
    if max_chars <= 0 or overlap < 0 or overlap >= max_chars:
        raise ValueError("Invalid passage limits")
    start = 0
    while start < len(text):
        end = min(len(text), start + max_chars)
        if end < len(text):
            boundary = text.rfind("\n", start + max_chars // 2, end)
            if boundary > start:
                end = boundary + 1
        if text[start:end].strip():
            yield start, end, text[start:end]
        if end == len(text):
            break
        start = max(start + 1, end - overlap)


def replace_page(db, version, index, text, *, origin, printed_page_label=None):
    if version.status != "draft" or not 0 <= index < version.page_count:
        raise ValueError("Only existing pages of a draft reference can be changed.")
    if len(text) > 50000:
        raise ValueError("A reference page has excessive text. Import a smaller or cleaner document.")
    db.query(MaterialChunk).filter(MaterialChunk.version_id == version.id, MaterialChunk.page_index == index).delete(synchronize_session=False)
    page = db.query(MaterialPage).filter(MaterialPage.version_id == version.id, MaterialPage.page_index == index).first()
    if not page:
        page = MaterialPage(version_id=version.id, page_index=index)
        db.add(page)
    page.text, page.text_sha256 = text, text_hash(text)
    page.origin, page.printed_page_label = origin, printed_page_label
    for ordinal, (start, end, passage) in enumerate(chunks_for_text(text)):
        db.add(MaterialChunk(version_id=version.id, page_index=index, ordinal=ordinal,
            char_start=start, char_end=end, text=passage, text_sha256=text_hash(passage)))
    db.flush()
    return page


def content_hash(db, version, *, validate=False):
    pages = db.query(MaterialPage).filter(MaterialPage.version_id == version.id).order_by(MaterialPage.page_index).all()
    chunks = db.query(MaterialChunk).filter(MaterialChunk.version_id == version.id).order_by(MaterialChunk.page_index, MaterialChunk.ordinal).all()
    by_index = {p.page_index:p for p in pages}
    if validate:
        if set(by_index) != set(range(version.page_count)):
            raise ValueError("Reference page inventory is incomplete. Re-ingest before approval.")
        for page in pages:
            if text_hash(page.text) != page.text_sha256:
                raise ValueError("Reference text integrity check failed.")
        for chunk in chunks:
            page = by_index.get(chunk.page_index)
            if (not page or chunk.char_start < 0 or chunk.char_end <= chunk.char_start
                    or page.text[chunk.char_start:chunk.char_end] != chunk.text
                    or text_hash(chunk.text) != chunk.text_sha256):
                raise ValueError("Reference passage integrity check failed.")
    values = {"approved_page_indices":version.approved_page_indices, "parser_version":version.parser_version,
        "document_sha256":version.document_sha256, "page_count":version.page_count,
        "pages":[[p.page_index,p.printed_page_label,p.text_sha256,p.origin] for p in pages],
        "chunks":[[c.id,c.page_index,c.ordinal,c.char_start,c.char_end,c.text_sha256] for c in chunks]}
    return text_hash(json.dumps(values, sort_keys=True, separators=(",", ":")))


def verify_approved_version(db, version):
    if version.status not in {"approved", "superseded"} or not version.approved_at:
        raise ValueError("Select an approved reference-material version.")
    if version.content_sha256 != content_hash(db, version, validate=True):
        raise ValueError("Approved reference content changed. Approve a new version before grading.")
    if version.original_file_path:
        document_path(version)


def public_version(db, version):
    result = {field:deepcopy(getattr(version, field)) for field in ("id","material_id","version_number","status","ingestion_status","media_type","document_sha256","content_sha256","page_count","approved_page_indices","parser_version","processing_job_id","error_message","created_at","approved_at")}
    result["chunk_count"] = db.query(MaterialChunk).filter(MaterialChunk.version_id == version.id).count()
    from models import ProcessingJob
    from services.job_queue_service import job_to_dict
    job = db.get(ProcessingJob, version.processing_job_id) if version.processing_job_id else None
    result["job"] = job_to_dict(job) if job else None
    return result


def new_version(db, material, user, *, media_type, document_sha256, page_count, path=None):
    db.query(CourseMaterial).filter(CourseMaterial.id == material.id).with_for_update().one()
    number = db.query(func.max(MaterialVersion.version_number)).filter(MaterialVersion.material_id == material.id).scalar() or 0
    version = MaterialVersion(material_id=material.id, version_number=number + 1, created_by=user.id,
        media_type=media_type, document_sha256=document_sha256, page_count=page_count,
        original_file_path=str(path.resolve()) if path else None)
    db.add(version)
    db.flush()
    return version


def ingest_material_job(job, db, progress):
    """Native reading is local. Explicit scan reading resumes verified saved pages."""
    version = db.query(MaterialVersion).filter(MaterialVersion.id == (job.payload or {}).get("material_version_id")).with_for_update().first()
    material = db.get(CourseMaterial, version.material_id) if version else None
    course = db.get(Course, material.course_id) if material else None
    if not version or not material or not course or not (material.institution_id == course.institution_id == job.institution_id):
        raise ValueError("Reference ingestion does not belong to this workspace.")
    if (version.processing_job_id != job.id or (job.payload or {}).get("material_id") != material.id
            or (job.payload or {}).get("course_id") != course.id):
        raise ValueError("Reference ingestion job does not match this version.")
    if version.status != "draft":
        if version.ingestion_status in {"ready", "needs_transcription"}:
            return
        raise ValueError("Approved reference versions cannot be re-ingested.")
    path = document_path(version)
    from services.presentation_material_service import PPTX_TYPE,read_slides
    presentation=version.media_type==PPTX_TYPE
    reader=None if presentation else pypdf.PdfReader(path)
    source_pages=read_slides(path) if presentation else reader.pages
    if len(source_pages) != version.page_count or (reader and reader.is_encrypted):
        raise ValueError("Reference PDF page inventory changed.")
    version.ingestion_status = "processing"
    scan_reading=(job.payload or {}).get('ocr_scans') is True
    existing={page.page_index:page for page in db.query(MaterialPage).filter_by(version_id=version.id).all()} if scan_reading else {}
    if not scan_reading:
        db.query(MaterialChunk).filter(MaterialChunk.version_id == version.id).delete(synchronize_session=False)
        db.query(MaterialPage).filter(MaterialPage.version_id == version.id).delete(synchronize_session=False)
    total_chars, nonempty = 0, 0
    for index, source_page in enumerate(source_pages):
        saved=existing.get(index)
        if saved and saved.text_sha256!=text_hash(saved.text):
            raise ValueError('Saved reference transcription changed. Correct the draft before retrying.')
        keep=saved and (saved.text.strip() or saved.origin in {'ocr_text_unverified','instructor_corrected'})
        text=saved.text if keep else source_page if presentation else source_page.extract_text() or ''
        origin=saved.origin if keep else 'slide_text_unverified' if presentation else 'native_text_unverified'
        if scan_reading and not presentation and not keep and not text.strip():
            from services.material_ocr_service import read_page
            text=read_page(path,index);origin='ocr_text_unverified'
        total_chars += len(text)
        if total_chars > MAX_EXTRACTED_CHARS:
            raise ValueError("Reference text exceeds the ingestion limit. Import chapter-sized files.")
        nonempty += bool(text.strip())
        if not keep:replace_page(db, version, index, text, origin=origin)
        progress(index + 1, version.page_count, f"Reading reference page {index + 1} of {version.page_count}")
    version.ingestion_status = "ready" if nonempty == version.page_count else "needs_transcription"
    version.parser_version = 'pptx-xml/slides-v1' if presentation else f"pypdf-{pypdf.__version__}/page-chars-v1"+('/scan-ocr-v1' if scan_reading else '')
    version.error_message = None
    version.content_sha256 = content_hash(db, version)
    db.flush()


def approve_material(db, version, request, user):
    db.query(CourseMaterial).filter(CourseMaterial.id == version.material_id).with_for_update().one()
    db.query(MaterialVersion).filter(MaterialVersion.id == version.id).with_for_update().one()
    db.refresh(version)
    if version.status != "draft" or version.ingestion_status not in {"ready", "needs_transcription"}:
        raise ValueError("Only a fully ingested draft can be approved. Wait for processing or retry its job.")
    selected = sorted(request.page_indices)
    if any(index >= version.page_count for index in selected):
        raise ValueError("Select existing zero-based reference pages.")
    pages = db.query(MaterialPage).filter(MaterialPage.version_id == version.id, MaterialPage.page_index.in_(selected)).all()
    if len(pages) != len(selected) or any(not p.text.strip() for p in pages):
        raise ValueError("Selected pages have no readable text. Correct their transcription before approval.")
    if version.original_file_path:
        document_path(version)
    version.approved_page_indices = selected
    version.content_sha256 = content_hash(db, version, validate=True)
    for old in db.query(MaterialVersion).filter(MaterialVersion.material_id == version.material_id, MaterialVersion.status == "approved").all():
        old.status = "superseded"
    version.status, version.approved_by = "approved", user.id
    version.approved_at = datetime.now(timezone.utc).replace(tzinfo=None)
    db.flush()
    return version


def validate_bindings(db, question, request, rubric):
    exam = db.query(Exam).filter(Exam.id == question.exam_id, Exam.institution_id == question.institution_id).first()
    if not exam:
        raise ValueError("Question assessment is unavailable.")
    validate_exam_bindings(db, exam, request, rubric)


def validate_exam_bindings(db, exam, request, rubric=None, *, allow_pending_sources=False):
    if request.bindings and not db.query(Course).filter(Course.id == exam.course_id, Course.institution_id == exam.institution_id).first():
        raise ValueError("Question course is unavailable in this workspace.")
    criteria = {c["id"] for c in (rubric or {}).get("criteria", [])}
    for binding in request.bindings:
        row = db.query(MaterialVersion, CourseMaterial).join(CourseMaterial, CourseMaterial.id == MaterialVersion.material_id).filter(
            MaterialVersion.id == binding.version_id, CourseMaterial.course_id == exam.course_id,
            CourseMaterial.institution_id == exam.institution_id).first()
        if not row:
            raise ValueError("Reference version is not available in this assessment's course.")
        version, material = row
        from services.material_library_service import attachment_exam
        attached_exam = attachment_exam(db,material.id)
        if attached_exam and attached_exam != exam.id:
            raise ValueError('Extra assessment material belongs to another assessment.')
        if allow_pending_sources and version.status == 'draft':
            if version.ingestion_status not in {'ready','needs_transcription'} or version.page_count < 1:
                raise ValueError('Wait for this material to finish reading before selecting its chapters.')
            if any(index >= version.page_count for index in binding.page_indices):
                raise ValueError('Selected source pages exceed the document page count.')
        else:
            verify_approved_version(db, version)
            if not set(binding.page_indices).issubset(set(version.approved_page_indices)):
                raise ValueError("Select only pages included in the source approval.")
        if binding.criterion_id is not None and binding.criterion_id not in criteria:
            raise ValueError("Reference binding cites an unknown criterion. Review the current rubric.")
        if binding.chunk_ids:
            chunks = db.query(MaterialChunk).filter(MaterialChunk.id.in_(binding.chunk_ids), MaterialChunk.version_id == version.id,
                MaterialChunk.page_index.in_(binding.page_indices)).all()
            if len(chunks) != len(binding.chunk_ids):
                raise ValueError("Reference passages do not belong to the selected version/pages.")


def save_scope(db, question, request, user, rubric):
    db.query(Question).filter(Question.id == question.id).with_for_update().one()
    validate_bindings(db, question, request, rubric)
    number = db.query(func.max(QuestionMaterialScopeVersion.version_number)).filter(QuestionMaterialScopeVersion.question_id == question.id).scalar() or 0
    scope = QuestionMaterialScopeVersion(question_id=question.id, version_number=number + 1,
        mode=request.mode, bindings=[b.model_dump() for b in request.bindings], created_by=user.id)
    db.add(scope)
    db.flush()
    return scope


def approve_scope(db, question, scope, user, rubric):
    db.query(Question).filter(Question.id == question.id).with_for_update().one()
    db.refresh(scope)
    if scope.status != "draft" or scope.question_id != question.id:
        raise ValueError("Only draft source scopes can be approved.")
    request = MaterialScopeRequest(mode=scope.mode, bindings=scope.bindings)
    validate_bindings(db, question, request, rubric)
    for old in db.query(QuestionMaterialScopeVersion).filter(QuestionMaterialScopeVersion.question_id == question.id, QuestionMaterialScopeVersion.status == "approved").all():
        old.status = "superseded"
    scope.status, scope.approved_by = "approved", user.id
    scope.scope_sha256 = scope_hash(scope)
    scope.approved_at = datetime.now(timezone.utc).replace(tzinfo=None)
    db.flush()
    return scope


def scope_hash(scope):
    return text_hash(json.dumps({"question_id":scope.question_id, "mode":scope.mode, "bindings":scope.bindings},
        sort_keys=True, ensure_ascii=False, separators=(",", ":")))
