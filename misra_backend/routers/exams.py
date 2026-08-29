from pathlib import Path

from fastapi import APIRouter, File, UploadFile, Form, Depends, HTTPException
from sqlalchemy.orm import Session
from database import get_db
from models import (
    Submission,
    Exam,
    Answer,
    Question,
    Course,
    User,
    RubricVersion,
    QuestionGradingPolicy,
)
from services.auth_dependencies import require_instructor
from services.audit_service import record_audit_event
from services.ocr_service import create_submissions_from_stored_upload
from services.job_queue_service import create_processing_job, job_to_dict
from services.upload_security_service import (
    UploadValidationError,
    remove_stored_uploads,
    store_validated_batch,
    store_validated_upload,
)
from models import Batch
from typing import Optional
from schemas.course_input import CourseCreateRequest
from schemas.exam_input import ExamCreateRequest, ExamDuplicateRequest

router = APIRouter(prefix="/api", tags=["exams"])

UPLOAD_DIR = "storage/uploads"


def _visible_courses(db: Session, user: User):
    """Return the institution's shared assessment workspace.

    MISRA's current instructor model is institution-scoped: authenticated
    instructors can work with their institution's courses, while ``teacher_id``
    remains the attribution for who created a course. Course/section-level
    permissions are a later multi-instructor administration feature.
    """
    return db.query(Course).filter(Course.institution_id == user.institution_id)


def _owned_exam(exam_id: str, db: Session, user: User) -> Exam | None:
    query = db.query(Exam).join(Course, Course.id == Exam.course_id).filter(
        Exam.id == exam_id,
        Exam.institution_id == user.institution_id,
    )
    return query.first()


@router.get("/courses")
def list_courses(db: Session = Depends(get_db), user: User = Depends(require_instructor)):
    return _visible_courses(db, user).order_by(Course.created_at.desc()).all()


@router.post("/courses", status_code=201)
def create_course(
    payload: CourseCreateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_instructor),
):
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
        Course.institution_id == user.institution_id,
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
        institution_id=user.institution_id,
        teacher_id=user.id,
        instructor_name=instructor_name or user.full_name,
        course_code=course_code,
        title=title,
        term=term,
    )
    db.add(course)
    db.flush()
    record_audit_event(
        db,
        institution_id=user.institution_id,
        actor_id=user.id,
        action="course_created",
        entity_type="course",
        entity_id=course.id,
        details={"course_code": course.course_code},
    )
    db.commit()
    db.refresh(course)
    return course


@router.post("/exams", status_code=201)
def create_exam(
    payload: ExamCreateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_instructor),
):
    course = _visible_courses(db, user).filter(Course.id == payload.course_id).first()
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")

    exam = Exam(
        institution_id=course.institution_id,
        course_id=course.id,
        title=payload.title.strip(),
        language=payload.language,
    )
    db.add(exam)
    db.flush()
    record_audit_event(
        db,
        institution_id=user.institution_id,
        actor_id=user.id,
        action="assessment_created",
        entity_type="exam",
        entity_id=exam.id,
        details={"course_id": course.id, "language": exam.language},
    )
    db.commit()
    db.refresh(exam)
    return exam


@router.get("/exams")
def list_exams(db: Session = Depends(get_db), user: User = Depends(require_instructor)):
    """Return the assessment catalog needed by the instructor workspace.

    This intentionally exposes persisted records only. The frontend never needs
    to invent exam names, course codes, or dashboard counts.
    """
    query = db.query(Exam).join(Course, Course.id == Exam.course_id).filter(
        Exam.institution_id == user.institution_id
    )
    exams = query.order_by(Exam.created_at.desc()).all()
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


@router.post("/exams/{exam_id}/duplicate", status_code=201)
def duplicate_exam(
    exam_id: str,
    payload: ExamDuplicateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_instructor),
):
    """Reuse an assessment structure without copying student work or grades."""
    source_exam = _owned_exam(exam_id, db, user)
    if not source_exam:
        raise HTTPException(status_code=404, detail="Assessment not found")

    title = payload.title.strip()
    if not title:
        raise HTTPException(status_code=422, detail="Assessment title is required")

    duplicate = Exam(
        institution_id=source_exam.institution_id,
        course_id=source_exam.course_id,
        title=title,
        language=source_exam.language,
    )
    db.add(duplicate)
    db.flush()

    source_questions = (
        db.query(Question)
        .filter(Question.exam_id == source_exam.id)
        .order_by(Question.order_index.asc(), Question.question_number.asc())
        .all()
    )
    copied_rubrics = 0
    copied_policies = 0

    for source_question in source_questions:
        question = Question(
            institution_id=source_question.institution_id,
            exam_id=duplicate.id,
            question_number=source_question.question_number,
            question_text=source_question.question_text,
            max_score=source_question.max_score,
            rubric_json=source_question.rubric_json,
            order_index=source_question.order_index,
            language=source_question.language,
        )
        db.add(question)
        db.flush()

        if payload.include_rubrics:
            source_version = None
            if source_question.active_rubric_version_id:
                source_version = db.query(RubricVersion).filter(
                    RubricVersion.id == source_question.active_rubric_version_id,
                    RubricVersion.question_id == source_question.id,
                    RubricVersion.status == "approved",
                ).first()
            if source_version:
                version = RubricVersion(
                    question_id=question.id,
                    version_number=1,
                    schema_version=source_version.schema_version,
                    rubric_json=source_version.rubric_json,
                    grading_approach=source_version.grading_approach,
                    source="imported",
                    status="approved",
                    change_summary=f"Reused from assessment {source_exam.title}.",
                    created_by=user.id,
                    approved_by=user.id,
                    approved_at=source_version.approved_at,
                )
                db.add(version)
                db.flush()
                question.active_rubric_version_id = version.id
                question.rubric_json = version.rubric_json
                copied_rubrics += 1

        if payload.include_grading_policies:
            source_policy = db.query(QuestionGradingPolicy).filter(
                QuestionGradingPolicy.question_id == source_question.id
            ).first()
            if source_policy:
                db.add(QuestionGradingPolicy(
                    question_id=question.id,
                    mode=source_policy.mode,
                    audit_rate=source_policy.audit_rate,
                    min_validated_samples=source_policy.min_validated_samples,
                    material_absolute_points=source_policy.material_absolute_points,
                    material_relative_ratio=source_policy.material_relative_ratio,
                    enabled=source_policy.enabled,
                    notes=source_policy.notes,
                ))
                copied_policies += 1

    record_audit_event(
        db,
        institution_id=user.institution_id,
        actor_id=user.id,
        action="assessment_duplicated",
        entity_type="exam",
        entity_id=duplicate.id,
        details={
            "source_exam_id": source_exam.id,
            "question_count": len(source_questions),
            "rubric_count": copied_rubrics,
            "policy_count": copied_policies,
        },
    )
    db.commit()
    db.refresh(duplicate)
    return {
        "exam": duplicate,
        "question_count": len(source_questions),
        "rubric_count": copied_rubrics,
        "policy_count": copied_policies,
    }

@router.post("/upload-exam", status_code=202)
async def upload_exam(
    exam_id: str = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(require_instructor),
):
    exam = _owned_exam(exam_id, db, user)
    if not exam:
        raise HTTPException(status_code=404, detail=f"Exam {exam_id} not found")

    try:
        stored = await store_validated_upload(file, UPLOAD_DIR)
    except UploadValidationError as error:
        raise HTTPException(status_code=error.status_code, detail=error.detail) from error

    try:
        submission = Submission(
            institution_id=exam.institution_id,
            exam_id=exam.id,
            original_file_path=str(stored.path),
            page_count=stored.page_count,
            status="uploaded",
        )
        db.add(submission)
        db.commit()
        db.refresh(submission)
    except Exception:
        db.rollback()
        remove_stored_uploads([stored])
        raise

    job, created = create_processing_job(
        db,
        institution_id=exam.institution_id,
        requested_by=user.id,
        job_type="ocr_submission",
        submission_id=submission.id,
        progress_total=submission.page_count,
    )
    record_audit_event(
        db,
        institution_id=exam.institution_id,
        actor_id=user.id,
        action="paper_uploaded",
        entity_type="submission",
        entity_id=submission.id,
        details={
            "exam_id": exam.id,
            "page_count": submission.page_count,
            "job_id": job.id,
            "job_created": created,
        },
    )
    db.commit()
    return {"submission": submission, "job": job_to_dict(job)}


@router.post("/upload-batch", status_code=202)
async def upload_batch(
    exam_id: str = Form(...),
    files: list[UploadFile] = File(...),
    pages_per_student: Optional[int] = Form(default=None),
    db: Session = Depends(get_db),
    user: User = Depends(require_instructor),
):
    exam = _owned_exam(exam_id, db, user)
    if not exam:
        raise HTTPException(status_code=404, detail=f"Exam {exam_id} not found")
    if pages_per_student is not None and pages_per_student <= 0:
        raise HTTPException(status_code=422, detail="pages_per_student must be a positive integer")

    try:
        stored_uploads = await store_validated_batch(files, UPLOAD_DIR)
    except UploadValidationError as error:
        raise HTTPException(status_code=error.status_code, detail=error.detail) from error

    all_submissions = []
    generated_paths: list[str] = []
    disposable_sources = []
    try:
        batch = Batch(
            institution_id=exam.institution_id,
            exam_id=exam.id,
            total_count=0,
            status="queued",
        )
        db.add(batch)
        db.flush()

        for stored in stored_uploads:
            submissions, paths, source_is_retained = create_submissions_from_stored_upload(
                exam_id=exam.id,
                institution_id=exam.institution_id,
                batch_id=batch.id,
                stored_upload=stored,
                pages_per_student=pages_per_student,
                db=db,
            )
            all_submissions.extend(submissions)
            generated_paths.extend(paths)
            if not source_is_retained:
                disposable_sources.append(stored)

        batch.total_count = len(all_submissions)
        db.commit()
        db.refresh(batch)
    except Exception:
        db.rollback()
        remove_stored_uploads(stored_uploads)
        for path in generated_paths:
            try:
                Path(path).unlink(missing_ok=True)
            except OSError:
                pass
        raise

    remove_stored_uploads(disposable_sources)

    submission_ids = [submission.id for submission in all_submissions]
    job, created = create_processing_job(
        db,
        institution_id=exam.institution_id,
        requested_by=user.id,
        job_type="ocr_batch",
        batch_id=batch.id,
        progress_total=len(all_submissions),
        payload={"submission_ids": submission_ids},
    )

    record_audit_event(
        db,
        institution_id=exam.institution_id,
        actor_id=user.id,
        action="paper_batch_uploaded",
        entity_type="batch",
        entity_id=batch.id,
        details={
            "exam_id": exam.id,
            "submission_count": len(all_submissions),
            "job_id": job.id,
            "job_created": created,
        },
    )
    db.commit()

    return {
        "batch_id": batch.id,
        "total_submissions": len(all_submissions),
        "status": batch.status,
        "job": job_to_dict(job),
    }

@router.post("/submissions/{submission_id}/promote-unmatched")
def promote_unmatched_segments(
    submission_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_instructor),
):
    submission = db.query(Submission).filter(
        Submission.id == submission_id,
        Submission.institution_id == user.institution_id,
    ).first()
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
