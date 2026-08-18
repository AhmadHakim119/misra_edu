import io
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Response
from PIL import Image
from pdf2image import convert_from_bytes
from sqlalchemy.orm import Session

from database import get_db
from models import Submission, Answer, Course, Exam
from schemas.page_recovery_input import (
    PageRecoveryConfirmRequest,
    PageRecoveryPreviewRequest,
)
from schemas.source_mapping_input import SourceMappingRequest, UnmatchedSegmentResolutionRequest
from schemas.submission_metadata_input import SubmissionMetadataUpdate
from services.extraction_review_service import (
    build_extraction_review,
    move_answer_source,
    remove_manually_assigned_source,
    resolve_unmatched_segment,
)
from services.page_recovery_service import (
    confirm_page_recovery,
    preview_page_recovery,
)

router = APIRouter(prefix="/api", tags=["results"])

@router.get("/results/{submission_id}")
async def get_results(submission_id: str, db: Session = Depends(get_db)):
    submission = db.query(Submission).filter(Submission.id == submission_id).first()
    if not submission:
        raise HTTPException(status_code=404, detail=f"Submission {submission_id} not found")

    answers = db.query(Answer).filter(Answer.submission_id == submission_id).all()

    return {
        "submission": submission,
        "answers": answers
    }


@router.get("/submissions")
def list_submissions(exam_id: str = None, db: Session = Depends(get_db)):
    query = db.query(Submission)
    if exam_id:
        query = query.filter(Submission.exam_id == exam_id)

    submissions = query.order_by(Submission.uploaded_at.desc()).all()
    items = []
    for submission in submissions:
        report = build_extraction_review(submission.id, db)
        items.append(
            {
                **report["submission"],
                "readiness": report["readiness"],
            }
        )
    return items


@router.get("/submissions/{submission_id}/extraction-review")
def get_extraction_review(
    submission_id: str,
    response: Response,
    db: Session = Depends(get_db),
):
    response.headers["Cache-Control"] = "no-store, max-age=0"
    try:
        return build_extraction_review(submission_id, db)
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.patch("/submissions/{submission_id}/metadata")
def update_submission_metadata(
    submission_id: str,
    payload: SubmissionMetadataUpdate,
    db: Session = Depends(get_db),
):
    submission = db.query(Submission).filter(Submission.id == submission_id).first()
    if not submission:
        raise HTTPException(status_code=404, detail="Submission not found")

    student_name = payload.student_name.strip() if payload.student_name else None
    student_number = payload.student_number.strip() if payload.student_number else None
    instructor_name = payload.instructor_name.strip() if payload.instructor_name else None
    submission.extracted_student_name = student_name or None
    submission.extracted_student_number = student_number or None
    if submission.student_id:
        submission.identity_status = "matched"
    elif student_name or student_number:
        submission.identity_status = "unmatched_extracted"
    else:
        submission.identity_status = "unmatched_blank"

    exam = db.query(Exam).filter(Exam.id == submission.exam_id).first()
    course = db.query(Course).filter(Course.id == exam.course_id).first() if exam else None
    if course:
        course.instructor_name = instructor_name or None

    db.commit()
    return build_extraction_review(submission.id, db)


@router.put("/submissions/{submission_id}/unmatched-segments/{unmatched_index}")
def update_unmatched_segment(
    submission_id: str,
    unmatched_index: int,
    payload: UnmatchedSegmentResolutionRequest,
    db: Session = Depends(get_db),
):
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
):
    submission = db.query(Submission).filter(Submission.id == submission_id).first()
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
):
    try:
        return move_answer_source(source_id, payload.question_id, db)
    except ValueError as error:
        status_code = 404 if "not found" in str(error).lower() else 409
        raise HTTPException(status_code=status_code, detail=str(error)) from error


@router.delete("/answer-sources/{source_id}")
def delete_manually_assigned_answer_source(
    source_id: str,
    db: Session = Depends(get_db),
):
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
):
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
):
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
async def get_review_queue(exam_id: str = None, db: Session = Depends(get_db)):
    query = db.query(Answer).filter(Answer.needs_review == True)
    if exam_id:
        query = query.join(Submission).filter(Submission.exam_id == exam_id)

    answers = query.all()
    return answers
