from __future__ import annotations

from datetime import datetime
import logging

from rq import get_current_job
from sqlalchemy.orm import Session

from database import SessionLocal
from models import Answer, GradingRun, ProcessingJob, Question, Submission
from services.grading_service import process_grading, process_grading_with_policy
from services.ocr_service import process_batch, process_submission
from services.audit_service import safe_error_message
from services.grading_scope_service import is_external_question, is_paper_question
from services.grading_errors import GradingResponseValidationError
from services.grading_control import GradingStopped, STAGE_PROGRESS, check_grading_active, grading_checkpoint, grading_stage
from services.inference_service import LocalInferenceError, LocalInferenceInputError
from services.job_queue_service import finish_stopped_job, lock_grading_paper, lock_job, stop_requested

PROFILE_SUPPORT_VERSION = 3
logger = logging.getLogger(__name__)


def _progress_callback(job: ProcessingJob, db: Session):
    def update(current: int, total: int, message: str) -> None:
        check_grading_active(lock=True)
        job.progress_current = max(0, current)
        job.progress_total = max(0, total)
        job.progress_message = message[:255]
        db.commit()

    return update


def _grade_submission(job: ProcessingJob, db: Session) -> None:
    submission = db.query(Submission).filter(Submission.id == job.submission_id).first()
    if not submission:
        raise ValueError(f"Submission {job.submission_id} not found")

    answers = (
        db.query(Answer)
        .join(Question, Question.id == Answer.question_id)
        .filter(Answer.submission_id == submission.id)
        .order_by(Question.order_index.asc())
        .all()
    )
    if not answers:
        raise ValueError("This submission has no mapped answers to grade")

    scoped_questions = {q.id: q for q in db.query(Question).filter(Question.exam_id == submission.exam_id).all()}
    answers = [a for a in answers if is_paper_question(scoped_questions[a.question_id])]
    if not answers:
        raise ValueError("No paper-assessed answers are available to grade.")

    payload = dict(job.payload or {})
    mode = payload.get("mode", "auto")
    completed_answer_ids = set(payload.get("completed_answer_ids") or [])
    saved_runs = db.query(GradingRun).filter_by(processing_job_id=job.id).all()
    saved_answer_ids = {run.answer_id for run in saved_runs}
    comparison_pairs = {'text_only': set(), 'image_text': set()}
    for run in saved_runs:
        package = (run.response_json or {}).get('grading_package') or {}
        routing = package.get('routing') or {}
        pair_id = routing.get('comparison_pair_id')
        if pair_id and run.mode in comparison_pairs:
            comparison_pairs[run.mode].add((run.answer_id, pair_id))
    incomplete_comparisons = len(comparison_pairs['text_only'] - comparison_pairs['image_text'])
    lock_grading_paper(db, job.job_type, job.submission_id, job.institution_id)
    check_grading_active(lock=True)
    submission.status = "grading"
    submission.error_message = None
    job.progress_total = len(answers)
    db.commit()

    for index, answer in enumerate(answers):
        check_grading_active(lock=True)
        # A primary proposal can commit before its optional image comparison or
        # progress checkpoint. Keep that recorded run and any instructor review.
        recorded = answer.score is not None or answer.teacher_override_score is not None
        saved = answer.id in saved_answer_ids or (recorded and answer.id in completed_answer_ids)
        if not saved:
            job.payload = {**(job.payload or {}), 'grading_stage': 'preparing', 'grading_stage_progress': STAGE_PROGRESS['preparing']}
            job.progress_message = f"Assessment and verification agents: answer {index + 1} of {len(answers)}"
            db.commit()
            if mode == "auto":
                process_grading_with_policy(answer.id, db, processing_job_id=job.id)
            else:
                process_grading(answer.id, db, mode=mode, processing_job_id=job.id)
            check_grading_active(lock=True)
        db.refresh(answer, attribute_names=['score', 'teacher_override_score'])
        if answer.score is None and answer.teacher_override_score is None:
            raise GradingResponseValidationError('missing_saved_grade', 'An expected grade is missing from the saved results. Review the paper and retry.')
        completed_answer_ids.add(answer.id)
        payload = dict(job.payload or {})
        payload["completed_answer_ids"] = sorted(completed_answer_ids)
        payload.pop('grading_stage', None)
        payload.pop('grading_stage_progress', None)
        job.payload = payload
        job.progress_current = index + 1
        prefix = 'Kept the saved grade for' if saved else 'Graded'
        job.progress_message = f"{prefix} answer {index + 1} of {len(answers)}"
        db.commit()

    lock_grading_paper(db, job.job_type, job.submission_id, job.institution_id)
    check_grading_active(lock=True)
    db.refresh(submission)
    if incomplete_comparisons:
        job.payload = {**(job.payload or {}), 'incomplete_comparison_count': incomplete_comparisons}
    graded_answers = db.query(Answer).filter(Answer.submission_id == submission.id).all()
    paper_grades = [answer for answer in graded_answers if is_paper_question(scoped_questions[answer.question_id])]
    submission.status = (
        "needs_review"
        if incomplete_comparisons or any(answer.needs_review for answer in paper_grades)
        else "graded"
    )
    db.commit()


def execute_processing_job(processing_job_id: str) -> None:
    """RQ entry point. The queue passes only the durable job UUID."""
    db = SessionLocal()
    job: ProcessingJob | None = None
    from services.inference_profiles import activate, reset
    from services.inference_profiles import TEXT_ONLY_IMAGE_ERROR
    profile_token = checkpoint_token = stage_token = None
    rq_job = get_current_job()
    dispatch_id = None
    claimed = False

    def current_attempt(current):
        return current and current.status == 'processing' and current.rq_job_id == dispatch_id

    def checkpoint(*, lock=False):
        if lock:
            current = lock_job(db, processing_job_id)
            if not current_attempt(current) or stop_requested(current):
                raise GradingStopped()
        else:
            with SessionLocal() as reader:
                current = reader.get(ProcessingJob, processing_job_id)
                if not current_attempt(current) or stop_requested(current):
                    raise GradingStopped()

    def report_stage(stage):
        with SessionLocal() as writer:
            current = lock_job(writer, processing_job_id)
            if not current_attempt(current) or stop_requested(current):
                raise GradingStopped()
            payload = dict(current.payload or {})
            progress = max(payload.get('grading_stage_progress', 0), STAGE_PROGRESS[stage])
            if payload.get('grading_stage') != stage:
                current.payload = {**payload, 'grading_stage': stage, 'grading_stage_progress': progress}
                writer.commit()

    try:
        job = lock_job(db, processing_job_id)
        if not job:
            raise ValueError(f"Processing job {processing_job_id} not found")
        if job.status not in {'queued', 'retrying'} or stop_requested(job) or (rq_job and job.rq_job_id != rq_job.id):
            return

        dispatch_id = job.rq_job_id
        claimed = True
        job.status = "processing"
        job.attempt_count = int(job.attempt_count or 0) + 1
        job.started_at = job.started_at or datetime.now()
        job.completed_at = None
        job.error_message = None
        job.progress_message = "Worker started"
        db.commit()

        profile_token = activate((job.payload or {}).get('_inference_profile'))
        if job.job_type == 'grade_submission':
            checkpoint_token = grading_checkpoint.set(checkpoint)
            stage_token = grading_stage.set(report_stage)
        progress = _progress_callback(job, db)
        if job.job_type == "material_ingestion":
            from services.course_material_service import ingest_material_job
            ingest_material_job(job, db, progress)
        elif job.job_type == "exam_setup":
            from services.exam_setup_service import extract_setup_documents
            extract_setup_documents(job, db, progress)
        elif job.job_type == "ocr_submission":
            if (job.payload or {}).get('operation') == 'read_answer_area':
                from services.answer_area_service import read_area_job
                read_area_job(job,db,progress)
            elif (job.payload or {}).get('operation') == 'locate_answers':
                from services.answer_location_service import run_location_job
                run_location_job(job, db, progress)
            else:
                options = {"reprocess": True} if (job.payload or {}).get("reprocess") else {}
                if job.submission_id not in (job.payload or {}).get('extracted_submission_ids', []):
                    process_submission(job.submission_id, db, progress_callback=progress,
                                       processing_job_id=job.id, **options)
                from services.answer_location_service import automatic_locations
                automatic_locations(job, db, progress)
        elif job.job_type == "ocr_batch":
            payload = job.payload or {}
            process_batch(
                job.batch_id,
                db,
                progress_callback=progress,
                submission_ids=payload.get("submission_ids"),
                processing_job_id=job.id,
            )
            from services.answer_location_service import automatic_locations
            automatic_locations(job, db, progress)
        elif job.job_type == "grade_submission":
            if (job.payload or {}).get('operation') == 'regrade_corrected_answer':
                from services.answer_area_service import regrade_corrected_answer
                regrade_corrected_answer(job,db,progress)
            else:
                _grade_submission(job, db)
        else:
            raise ValueError(f"Unsupported processing job type: {job.job_type}")

        checkpoint(lock=True)
        job.status = "completed"
        job.progress_current = job.progress_total
        job.progress_message = ('Saved primary grades. An image comparison is incomplete; review the saved proposals.'
                                if (job.payload or {}).get('incomplete_comparison_count') else 'Completed')
        job.completed_at = datetime.now()
        db.commit()
    except Exception as error:
        db.rollback()
        job = db.get(ProcessingJob, processing_job_id)
        if job and claimed:
            lock_grading_paper(db, job.job_type, job.submission_id, job.institution_id)
        job = lock_job(db, processing_job_id)
        if claimed and not current_attempt(job):
            return
        if job and claimed:
            if stop_requested(job):
                finish_stopped_job(job, db)
                db.commit()
                logger.info('Grading stopped for job %s. No further answers will be processed.', processing_job_id)
                return
            safe_error = safe_error_message(error)
            validation_failed = isinstance(error, GradingResponseValidationError)
            local_failed = isinstance(error, (LocalInferenceError, LocalInferenceInputError)) or str(error).startswith(TEXT_ONLY_IMAGE_ERROR)
            exhausted = validation_failed or local_failed or int(job.attempt_count or 0) >= int(job.max_attempts or 1)
            if exhausted and rq_job:
                rq_job.retries_left = 0
            job.status = "failed" if exhausted else "retrying"
            job.error_message = safe_error
            job.progress_message = (
                "AI response rejected; review or retry grading" if validation_failed
                else "Local AI needs attention" if local_failed
                else "Retry limit reached" if exhausted else "Failed; waiting to retry"
            )
            job.completed_at = datetime.now() if exhausted else None
            if job.job_type == "material_ingestion":
                from models import MaterialVersion
                version = db.query(MaterialVersion).filter(
                    MaterialVersion.id == (job.payload or {}).get("material_version_id"),
                    MaterialVersion.processing_job_id == job.id,
                    MaterialVersion.status == "draft",
                ).first()
                if version:
                    version.ingestion_status = "failed" if exhausted else "retrying"
                    version.error_message = safe_error
            if exhausted and job.job_type == "grade_submission" and job.submission_id:
                submission = (
                    db.query(Submission)
                    .filter(Submission.id == job.submission_id)
                    .first()
                )
                if submission and submission.status == "grading":
                    submission.status = "extracted"
                    submission.error_message = safe_error
            db.commit()
        raise
    finally:
        if stage_token is not None:
            grading_stage.reset(stage_token)
        if checkpoint_token is not None:
            grading_checkpoint.reset(checkpoint_token)
        if profile_token is not None:
            reset(profile_token)
        db.close()
