import logging
import os, re
import uuid
from fastapi import APIRouter, File, UploadFile, Form, Depends, HTTPException
from sqlalchemy.orm import Session
from database import get_db
from models import Submission, Exam, Answer, Question, Course
from services.ocr_service import process_submission, create_submissions_from_upload, process_batch
from fastapi import BackgroundTasks
from database import SessionLocal
from models import Batch
from typing import Optional
from schemas.course_input import CourseCreateRequest
from schemas.exam_input import ExamCreateRequest

router = APIRouter(prefix="/api", tags=["exams"])
logger = logging.getLogger(__name__)

UPLOAD_DIR = "storage/uploads"


@router.get("/courses")
def list_courses(db: Session = Depends(get_db)):
    return db.query(Course).order_by(Course.created_at.desc()).all()


@router.post("/courses", status_code=201)
def create_course(payload: CourseCreateRequest, db: Session = Depends(get_db)):
    """Create a course under an existing persisted ownership profile.

    Authentication is not connected yet, so the caller selects an existing
    course whose institution and instructor ownership should be inherited.
    This avoids accepting or inventing raw tenant/user identifiers.
    """
    owner_course = db.query(Course).filter(Course.id == payload.owner_course_id).first()
    if not owner_course:
        raise HTTPException(status_code=404, detail="Ownership profile course not found")

    course_code = payload.course_code.strip()
    title = payload.title.strip()
    term = payload.term.strip() if payload.term and payload.term.strip() else None
    instructor_name = (
        payload.instructor_name.strip()
        if payload.instructor_name and payload.instructor_name.strip()
        else None
    )
    if not course_code or not title:
        raise HTTPException(status_code=422, detail="Course code and title are required")

    duplicate = db.query(Course).filter(
        Course.institution_id == owner_course.institution_id,
        Course.course_code == course_code,
        Course.title == title,
        Course.term == term,
    ).first()
    if duplicate:
        raise HTTPException(
            status_code=409,
            detail="This course already exists for the selected institution and term",
        )

    course = Course(
        institution_id=owner_course.institution_id,
        teacher_id=owner_course.teacher_id,
        instructor_name=instructor_name,
        course_code=course_code,
        title=title,
        term=term,
    )
    db.add(course)
    db.commit()
    db.refresh(course)
    return course


@router.post("/exams", status_code=201)
def create_exam(payload: ExamCreateRequest, db: Session = Depends(get_db)):
    course = db.query(Course).filter(Course.id == payload.course_id).first()
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")

    exam = Exam(
        institution_id=course.institution_id,
        course_id=course.id,
        title=payload.title.strip(),
        language=payload.language,
    )
    db.add(exam)
    db.commit()
    db.refresh(exam)
    return exam


@router.get("/exams")
def list_exams(db: Session = Depends(get_db)):
    """Return the assessment catalog needed by the instructor workspace.

    This intentionally exposes persisted records only. The frontend never needs
    to invent exam names, course codes, or dashboard counts.
    """
    exams = db.query(Exam).order_by(Exam.created_at.desc()).all()
    catalog = []

    for exam in exams:
        course = db.query(Course).filter(Course.id == exam.course_id).first()
        submission_count = (
            db.query(Submission).filter(Submission.exam_id == exam.id).count()
        )
        question_count = db.query(Question).filter(Question.exam_id == exam.id).count()
        review_count = (
            db.query(Answer)
            .join(Submission, Answer.submission_id == Submission.id)
            .filter(Submission.exam_id == exam.id, Answer.needs_review.is_(True))
            .count()
        )
        catalog.append(
            {
                "id": exam.id,
                "institution_id": exam.institution_id,
                "course_id": exam.course_id,
                "course_code": course.course_code if course else None,
                "course_title": course.title if course else None,
                "term": course.term if course else None,
                "title": exam.title,
                "language": exam.language,
                "created_at": exam.created_at,
                "question_count": question_count,
                "submission_count": submission_count,
                "review_count": review_count,
            }
        )

    return catalog

def _run_submission_in_background(submission_id: str):
    """Run OCR after the upload response using an independent DB session."""
    db = SessionLocal()
    try:
        process_submission(submission_id, db)
    except Exception:
        # process_submission persists the submission error state before raising.
        logger.exception("Background extraction failed for submission %s", submission_id)
    finally:
        db.close()


@router.post("/upload-exam", status_code=202)
async def upload_exam(
    background_tasks: BackgroundTasks,
    exam_id: str = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    exam = db.query(Exam).filter(Exam.id == exam_id).first()
    if not exam:
        raise HTTPException(status_code=404, detail=f"Exam {exam_id} not found")

    contents = await file.read()
    _, ext = os.path.splitext(file.filename)
    unique_name = f"{uuid.uuid4()}{ext}"
    upload_path = os.path.join(UPLOAD_DIR, unique_name)

    with open(upload_path, "wb") as f:
        f.write(contents)

    submission = Submission(
        institution_id=exam.institution_id,
        exam_id=exam.id,
        original_file_path=upload_path,
        status="uploaded"
    )
    db.add(submission)
    db.commit()
    db.refresh(submission)

    background_tasks.add_task(_run_submission_in_background, submission.id)
    return submission

def _run_batch_in_background(batch_id: str):
    """Background task entrypoint — opens its OWN database session,
    since the request-scoped session will already be closed by the time
    this runs."""
    db = SessionLocal()
    try:
        process_batch(batch_id, db)
    finally:
        db.close()


@router.post("/upload-batch")
async def upload_batch(
    background_tasks: BackgroundTasks,
    exam_id: str = Form(...),
    files: list[UploadFile] = File(...),
    pages_per_student: Optional[int] = Form(default=None),
    db: Session = Depends(get_db)
):
    exam = db.query(Exam).filter(Exam.id == exam_id).first()
    if not exam:
        raise HTTPException(status_code=404, detail=f"Exam {exam_id} not found")

    all_submissions = []

    # Create the Batch row first with a placeholder count; update it once we know the real total.
    batch = Batch(
        institution_id=exam.institution_id,
        exam_id=exam.id,
        total_count=0,
        status="queued"
    )
    db.add(batch)
    db.commit()
    db.refresh(batch)

    for file in files:
        contents = await file.read()
        submissions = create_submissions_from_upload(
            exam_id=exam.id,
            institution_id=exam.institution_id,
            batch_id=batch.id,
            file_bytes=contents,
            filename=file.filename,
            upload_dir=UPLOAD_DIR,
            pages_per_student=pages_per_student,
            db=db
        )
        all_submissions.extend(submissions)

    batch.total_count = len(all_submissions)
    db.commit()
    db.refresh(batch)

    background_tasks.add_task(_run_batch_in_background, batch.id)

    return {
        "batch_id": batch.id,
        "total_submissions": len(all_submissions),
        "status": batch.status
    }

@router.post("/submissions/{submission_id}/promote-unmatched")
def promote_unmatched_segments(submission_id: str, db: Session = Depends(get_db)):
    submission = db.query(Submission).filter(Submission.id == submission_id).first()
    if not submission:
        raise HTTPException(status_code=404, detail="Submission not found")
    if not submission.unmatched_segments:
        return {"promoted": 0, "still_unmatched": 0}

    questions = db.query(Question).filter(Question.exam_id == submission.exam_id).all()
    exact_lookup = {q.question_number: q.id for q in questions}

    still_unmatched = []
    promoted_count = 0

    for segment in submission.unmatched_segments:
        question_id = exact_lookup.get(segment.get("question_number"))
        if not question_id:
            still_unmatched.append(segment)
            continue

        existing = db.query(Answer).filter(
            Answer.submission_id == submission.id,
            Answer.question_id == question_id
        ).first()

        if existing:
            existing.raw_ocr_text = f"{existing.raw_ocr_text}\n{segment['text']}"
            existing.ocr_legibility = segment.get("legibility")
            existing.ocr_raw_response = segment
        else:
            answer = Answer(
                institution_id=submission.institution_id,
                submission_id=submission.id,
                question_id=question_id,
                raw_ocr_text=segment["text"],
                ocr_legibility=segment.get("legibility"),
                ocr_raw_response=segment
            )
            db.add(answer)
            db.flush()

        promoted_count += 1

    submission.unmatched_segments = still_unmatched if still_unmatched else None
    db.commit()
    return {"promoted": promoted_count, "still_unmatched": len(still_unmatched)}
