import io
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Response
from PIL import Image
from pdf2image import convert_from_bytes
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from database import get_db
from models import (
    Answer,
    AnswerSource,
    Batch,
    Course,
    Exam,
    GradingRun,
    ProcessingJob,
    Question,
    ReviewLabel,
    Student,
    Submission,
    User,
)
from schemas.page_recovery_input import (
    PageRecoveryConfirmRequest,
    PageRecoveryPreviewRequest,
)
from schemas.source_mapping_input import SourceMappingRequest, UnmatchedSegmentResolutionRequest
from schemas.source_mapping_input import BulkSegmentResolutionRequest
from schemas.submission_metadata_input import SubmissionMetadataUpdate
from services.extraction_review_service import (
    bulk_resolve_segments,
    build_extraction_review,
    move_answer_source,
    remove_manually_assigned_source,
    resolve_unmatched_segment,
)
from services.page_recovery_service import (
    confirm_page_recovery,
    preview_page_recovery,
)
from services.auth_dependencies import require_instructor
from services.audit_service import record_audit_event
from services.job_queue_service import job_to_dict

router = APIRouter(prefix="/api", tags=["results"])


def _owned_submission(submission_id: str, db: Session, user: User) -> Submission | None:
    return db.query(Submission).filter(
        Submission.id == submission_id,
        Submission.institution_id == user.institution_id,
    ).first()


def _owned_source(source_id: str, db: Session, user: User) -> AnswerSource | None:
    return (
        db.query(AnswerSource)
        .join(Answer, Answer.id == AnswerSource.answer_id)
        .join(Submission, Submission.id == Answer.submission_id)
        .filter(
            AnswerSource.id == source_id,
            Submission.institution_id == user.institution_id,
        )
        .first()
    )

@router.get("/results/{submission_id}")
async def get_results(
    submission_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_instructor),
):
    submission = _owned_submission(submission_id, db, user)
    if not submission:
        raise HTTPException(status_code=404, detail=f"Submission {submission_id} not found")

    answers = db.query(Answer).filter(Answer.submission_id == submission_id).all()
    latest_review_labels = []
    for answer in answers:
        label = (
            db.query(ReviewLabel)
            .filter(ReviewLabel.answer_id == answer.id)
            .order_by(ReviewLabel.created_at.desc(), ReviewLabel.id.desc())
            .first()
        )
        if label:
            latest_review_labels.append(label)

    return {
        "submission": submission,
        "answers": answers,
        "latest_review_labels": latest_review_labels,
    }


@router.get("/submissions")
def list_submissions(
    exam_id: str = None,
    db: Session = Depends(get_db),
    user: User = Depends(require_instructor),
):
    query = db.query(Submission).filter(Submission.institution_id == user.institution_id)
    if exam_id:
        query = query.filter(Submission.exam_id == exam_id)

    submissions = query.order_by(Submission.uploaded_at.desc()).all()
    latest_ocr_jobs = {}
    submission_ids = [submission.id for submission in submissions]
    if submission_ids:
        jobs = (
            db.query(ProcessingJob)
            .filter(
                ProcessingJob.submission_id.in_(submission_ids),
                ProcessingJob.job_type == "ocr_submission",
            )
            .order_by(ProcessingJob.created_at.desc())
            .all()
        )
        for job in jobs:
            latest_ocr_jobs.setdefault(job.submission_id, job)

    items = []
    for submission in submissions:
        report = build_extraction_review(submission.id, db)
        latest_job = latest_ocr_jobs.get(submission.id)
        items.append(
            {
                **report["submission"],
                "readiness": report["readiness"],
                "latest_ocr_job": job_to_dict(latest_job) if latest_job else None,
            }
        )
    return items


@router.get("/submissions/{submission_id}/extraction-review")
def get_extraction_review(
    submission_id: str,
    response: Response,
    db: Session = Depends(get_db),
    user: User = Depends(require_instructor),
):
    response.headers["Cache-Control"] = "no-store, max-age=0"
    if not _owned_submission(submission_id, db, user):
        raise HTTPException(status_code=404, detail="Submission not found")
    try:
        return build_extraction_review(submission_id, db)
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.delete("/submissions/{submission_id}")
def delete_submission(
    submission_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_instructor),
):
    submission = _owned_submission(submission_id, db, user)
    if not submission:
        raise HTTPException(status_code=404, detail="Submission not found")

    active_job = db.query(ProcessingJob.id).filter(
        ProcessingJob.submission_id == submission.id,
        ProcessingJob.status.in_(("queued", "processing", "retrying")),
    ).first()
    if active_job:
        raise HTTPException(
            status_code=409,
            detail="This paper is still being processed. Wait for the job to finish before deleting it.",
        )

    stored_path = _stored_submission_path(submission.original_file_path)
    batch_id = submission.batch_id
    answer_ids = [
        answer_id
        for (answer_id,) in db.query(Answer.id).filter(
            Answer.submission_id == submission.id
        ).all()
    ]

    try:
        if answer_ids:
            db.query(ReviewLabel).filter(
                ReviewLabel.answer_id.in_(answer_ids)
            ).delete(synchronize_session=False)
            db.query(AnswerSource).filter(
                AnswerSource.answer_id.in_(answer_ids)
            ).delete(synchronize_session=False)
            db.query(GradingRun).filter(
                GradingRun.answer_id.in_(answer_ids)
            ).delete(synchronize_session=False)
            db.query(Answer).filter(
                Answer.id.in_(answer_ids)
            ).delete(synchronize_session=False)

        db.query(ProcessingJob).filter(
            ProcessingJob.submission_id == submission.id
        ).delete(synchronize_session=False)
        db.delete(submission)
        db.flush()

        record_audit_event(
            db,
            institution_id=user.institution_id,
            actor_id=user.id,
            action="submission_deleted",
            entity_type="submission",
            entity_id=submission_id,
            details={
                "exam_id": submission.exam_id,
                "page_count": submission.page_count,
                "answer_count": len(answer_ids),
            },
        )

        if batch_id:
            batch = db.query(Batch).filter(Batch.id == batch_id).first()
            if batch:
                remaining = db.query(Submission).filter(Submission.batch_id == batch.id).all()
                batch.total_count = len(remaining)
                batch.completed_count = sum(
                    item.status in {"extracted", "graded", "needs_review", "reviewed"}
                    for item in remaining
                )
                batch.failed_count = sum(item.status == "error" for item in remaining)

        db.commit()
    except Exception:
        db.rollback()
        raise

    file_removed = False
    try:
        stored_path.unlink(missing_ok=True)
        file_removed = not stored_path.exists()
    except OSError:
        file_removed = False

    return {
        "deleted": True,
        "submission_id": submission_id,
        "file_removed": file_removed,
    }


@router.patch("/submissions/{submission_id}/metadata")
def update_submission_metadata(
    submission_id: str,
    payload: SubmissionMetadataUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_instructor),
):
    submission = db.query(Submission).filter(
        Submission.id == submission_id,
        Submission.institution_id == user.institution_id,
    ).first()
    if not submission:
        raise HTTPException(status_code=404, detail="Submission not found")

    student_name = payload.student_name.strip() if payload.student_name else None
    student_number = payload.student_number.strip() if payload.student_number else None
    instructor_name = payload.instructor_name.strip() if payload.instructor_name else None
    if student_name and student_number:
        student = db.query(Student).filter(
            Student.institution_id == submission.institution_id,
            Student.student_number == student_number,
        ).first()
        if not student:
            student = Student(
                id=str(uuid.uuid4()),
                institution_id=submission.institution_id,
                student_number=student_number,
                full_name=student_name,
            )
            db.add(student)
        else:
            student.full_name = student_name
        submission.student_id = student.id
        submission.extracted_student_name = student.full_name
        submission.extracted_student_number = student.student_number
        submission.identity_status = "matched"
    else:
        submission.student_id = None
        submission.extracted_student_name = student_name or None
        submission.extracted_student_number = student_number or None
    if not student_name and not student_number:
        submission.identity_status = "unmatched_blank"
    elif not (student_name and student_number):
        submission.identity_status = "unmatched_extracted"

    exam = db.query(Exam).filter(Exam.id == submission.exam_id).first()
    course = db.query(Course).filter(Course.id == exam.course_id).first() if exam else None
    if course:
        course.instructor_name = instructor_name or None

    try:
        db.commit()
    except IntegrityError as error:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="That student number already belongs to another student record. Check the name and number, then try again.",
        ) from error
    return build_extraction_review(submission.id, db)


@router.put("/submissions/{submission_id}/unmatched-segments/{unmatched_index}")
def update_unmatched_segment(
    submission_id: str,
    unmatched_index: int,
    payload: UnmatchedSegmentResolutionRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_instructor),
):
    submission = _owned_submission(submission_id, db, user)
    if not submission:
        raise HTTPException(status_code=404, detail="Submission not found")
    if payload.question_id:
        question = db.query(Question).filter(
            Question.id == payload.question_id,
            Question.exam_id == submission.exam_id,
            Question.institution_id == user.institution_id,
        ).first()
        if not question:
            raise HTTPException(status_code=404, detail="Question not found")
    try:
        return resolve_unmatched_segment(
            submission_id=submission_id,
            unmatched_index=unmatched_index,
            action=payload.action,
            question_id=payload.question_id,
            page_index=payload.page_index,
            db=db,
        )
    except ValueError as error:
        status_code = 404 if "not found" in str(error).lower() else 409
        raise HTTPException(status_code=status_code, detail=str(error)) from error


@router.put("/submissions/{submission_id}/segments/bulk-resolve")
def bulk_resolve_submission_segments(
    submission_id: str,
    payload: BulkSegmentResolutionRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_instructor),
):
    if not _owned_submission(submission_id, db, user):
        raise HTTPException(status_code=404, detail="Submission not found")
    if payload.question_id:
        question = db.query(Question).filter(
            Question.id == payload.question_id,
            Question.institution_id == user.institution_id,
        ).first()
        if not question:
            raise HTTPException(status_code=404, detail="Question not found")
    try:
        return bulk_resolve_segments(
            submission_id=submission_id,
            action=payload.action,
            question_id=payload.question_id,
            source_ids=payload.source_ids,
            unmatched_indices=payload.unmatched_indices,
            db=db,
        )
    except ValueError as error:
        message = str(error)
        status_code = 404 if "not found" in message.lower() else 409
        raise HTTPException(status_code=status_code, detail=message) from error


def _stored_submission_path(raw_path: str) -> Path:
    path = Path(raw_path)
    if path.is_absolute():
        return path
    backend_root = Path(__file__).resolve().parent.parent
    candidates = [Path.cwd() / path, backend_root / path]
    for candidate in candidates:
        if candidate.exists():
            return candidate.resolve()
    return candidates[-1].resolve()


@router.get("/submissions/{submission_id}/pages/{page_index}")
def get_submission_page(
    submission_id: str,
    page_index: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_instructor),
):
    submission = _owned_submission(submission_id, db, user)
    if not submission:
        raise HTTPException(status_code=404, detail="Submission not found")
    if page_index < 0 or page_index >= submission.page_count:
        raise HTTPException(status_code=404, detail="Page not found")

    path = _stored_submission_path(submission.original_file_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Stored submission file not found")
    file_bytes = path.read_bytes()
    if path.suffix.lower() == ".pdf":
        pages = convert_from_bytes(
            file_bytes,
            first_page=page_index + 1,
            last_page=page_index + 1,
        )
        if not pages:
            raise HTTPException(status_code=404, detail="Page not found")
        buffer = io.BytesIO()
        pages[0].save(buffer, format="JPEG", quality=86, optimize=True)
        return Response(content=buffer.getvalue(), media_type="image/jpeg")

    image = Image.open(io.BytesIO(file_bytes))
    media_type = Image.MIME.get(image.format, "application/octet-stream")
    return Response(content=file_bytes, media_type=media_type)


@router.put("/answer-sources/{source_id}/question")
def update_answer_source_question(
    source_id: str,
    payload: SourceMappingRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_instructor),
):
    source = _owned_source(source_id, db, user)
    if not source:
        raise HTTPException(status_code=404, detail="Answer source not found")
    answer = db.query(Answer).filter(Answer.id == source.answer_id).first()
    submission = _owned_submission(answer.submission_id, db, user) if answer else None
    if not submission:
        raise HTTPException(status_code=404, detail="Submission not found")
    question = db.query(Question).filter(
        Question.id == payload.question_id,
        Question.institution_id == user.institution_id,
        Question.exam_id == submission.exam_id,
    ).first()
    if not question:
        raise HTTPException(status_code=404, detail="Question not found")
    try:
        return move_answer_source(source_id, payload.question_id, db)
    except ValueError as error:
        status_code = 404 if "not found" in str(error).lower() else 409
        raise HTTPException(status_code=status_code, detail=str(error)) from error


@router.delete("/answer-sources/{source_id}")
def delete_manually_assigned_answer_source(
    source_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_instructor),
):
    if not _owned_source(source_id, db, user):
        raise HTTPException(status_code=404, detail="Answer source not found")
    try:
        return remove_manually_assigned_source(source_id, db)
    except ValueError as error:
        status_code = 404 if "not found" in str(error).lower() else 409
        raise HTTPException(status_code=status_code, detail=str(error)) from error


@router.post("/submissions/{submission_id}/pages/{page_index}/reextract")
def reextract_submission_page(
    submission_id: str,
    page_index: int,
    payload: PageRecoveryPreviewRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_instructor),
):
    if not _owned_submission(submission_id, db, user):
        raise HTTPException(status_code=404, detail="Submission not found")
    try:
        return preview_page_recovery(
            submission_id,
            page_index,
            payload.question_numbers,
            db,
        )
    except ValueError as error:
        status_code = 404 if "not found" in str(error).lower() else 400
        raise HTTPException(status_code=status_code, detail=str(error)) from error
    except Exception as error:
        raise HTTPException(
            status_code=502,
            detail=f"Page recovery OCR failed: {error}",
        ) from error


@router.post("/submissions/{submission_id}/pages/{page_index}/confirm-reextract")
def confirm_submission_page_reextract(
    submission_id: str,
    page_index: int,
    payload: PageRecoveryConfirmRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_instructor),
):
    if not _owned_submission(submission_id, db, user):
        raise HTTPException(status_code=404, detail="Submission not found")
    try:
        return confirm_page_recovery(
            submission_id,
            page_index,
            payload.question_numbers,
            payload.segments,
            payload.preview_signature,
            db,
        )
    except ValueError as error:
        status_code = 404 if "not found" in str(error).lower() else 409
        raise HTTPException(status_code=status_code, detail=str(error)) from error

@router.get("/review-queue")
async def get_review_queue(
    exam_id: str = None,
    db: Session = Depends(get_db),
    user: User = Depends(require_instructor),
):
    query = (
        db.query(Answer)
        .join(Submission, Submission.id == Answer.submission_id)
        .filter(
            Answer.needs_review.is_(True),
            Submission.institution_id == user.institution_id,
        )
    )
    if exam_id:
        query = query.filter(Submission.exam_id == exam_id)

    answers = query.all()
    return answers
