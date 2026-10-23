from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from database import get_db
from models import Answer, GradingRun, ReviewLabel, Submission, User
from schemas.review_input import PREFERENCE_REASON_CODES, ReviewResolutionRequest, ReopenReviewRequest
from services.auth_dependencies import require_instructor
from services.audit_service import record_audit_event
from schemas.public_results import ReviewResolutionRecord, ReviewRecord

router = APIRouter(prefix="/api", tags=["review"])


@router.post('/answers/{answer_id}/reopen-review')
def reopen_review(answer_id: str, request: ReopenReviewRequest,
                  db: Session = Depends(get_db), user: User = Depends(require_instructor)):
    from models import ProcessingJob
    from schemas.public_results import AnswerRecord
    answer = db.query(Answer).join(Submission, Submission.id == Answer.submission_id).filter(
        Answer.id == answer_id, Submission.institution_id == user.institution_id).first()
    if not answer:
        raise HTTPException(404, 'Answer not found')
    db.query(Submission).filter(Submission.id == answer.submission_id).with_for_update().one()
    db.refresh(answer, with_for_update=True)
    from services.review_state_service import latest_operational_label
    latest = latest_operational_label(db, answer)
    if (answer.review_status not in {'approved','overridden'} or answer.reviewed_at is None
            or answer.reviewed_at.replace(tzinfo=None) != request.expected_reviewed_at.replace(tzinfo=None)
            or (answer.grading_raw_response or {}).get('grading_run_id') != request.expected_run_id
            or (latest.id if latest else None) != request.expected_label_id):
        raise HTTPException(409, 'The saved decision changed. Reload its history before reopening.')
    if db.query(ProcessingJob).filter(ProcessingJob.submission_id == answer.submission_id,
            ProcessingJob.institution_id == user.institution_id,
            ProcessingJob.status.in_(('queued','processing','retrying'))).first():
        raise HTTPException(409, 'Paper processing is active. Wait for it to finish before reopening review.')
    raw = dict(answer.grading_raw_response or {})
    raw['review_reopened'] = {'reason':request.reason.strip(), 'previous_review_status':answer.review_status}
    answer.grading_raw_response = raw
    answer.review_status = 'pending'
    answer.needs_review = True
    # Previous human score/notes and immutable labels remain available, but the
    # answer is no longer finalized. Reopening is not a new reference label.
    record_audit_event(db, institution_id=user.institution_id, actor_id=user.id,
        action='grade_review_reopened', entity_type='answer', entity_id=answer.id,
        details={'previous_reviewed_at':answer.reviewed_at.isoformat(), 'reason':request.reason.strip()})
    db.commit(); db.refresh(answer)
    return AnswerRecord.model_validate(answer)


@router.get("/answers/{answer_id}/review-history", response_model=list[ReviewRecord])
def review_history(answer_id: str, db: Session = Depends(get_db), user: User = Depends(require_instructor)):
    answer = db.query(Answer).join(Submission, Submission.id == Answer.submission_id).filter(
        Answer.id == answer_id, Submission.institution_id == user.institution_id).first()
    if not answer:
        raise HTTPException(status_code=404, detail="Answer not found")
    return db.query(ReviewLabel).filter(ReviewLabel.answer_id == answer_id).order_by(
        ReviewLabel.created_at.asc(), ReviewLabel.id.asc()).all()


@router.get('/answers/{answer_id}/review-events')
def review_events(answer_id: str, db: Session = Depends(get_db), user: User = Depends(require_instructor)):
    from models import AuditLog
    answer = db.query(Answer).join(Submission, Submission.id == Answer.submission_id).filter(
        Answer.id == answer_id, Submission.institution_id == user.institution_id).first()
    if not answer:
        raise HTTPException(404, 'Answer not found')
    rows = db.query(AuditLog).filter(AuditLog.institution_id == user.institution_id,
        AuditLog.entity_type == 'answer', AuditLog.entity_id == answer_id,
        AuditLog.action.in_(('grade_approved','grade_overridden','grade_review_reopened'))).order_by(AuditLog.created_at, AuditLog.id).all()
    return [dict(id=row.id, action=row.action, created_at=row.created_at,
        **{key:((row.extra_data or {}).get('details') or {}).get(key) for key in ('reason','ai_score','human_score','apply_as_current','grading_run_id','review_label_id')}) for row in rows]


@router.post("/answers/{answer_id}/resolve-review", response_model=ReviewResolutionRecord)
def resolve_review(
    answer_id: str,
    request: ReviewResolutionRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_instructor),
):
    answer = (
        db.query(Answer)
        .join(Submission, Submission.id == Answer.submission_id)
        .filter(
            Answer.id == answer_id,
            Submission.institution_id == user.institution_id,
        )
        .first()
    )
    if not answer:
        raise HTTPException(status_code=404, detail="Answer not found")
    if request.apply_as_current:
        from models import ProcessingJob
        # Serialize with corrected-regrade acceptance. A pending proposal must not
        # race a new official decision against the older displayed AI run.
        db.query(Submission).filter(Submission.id==answer.submission_id,
            Submission.institution_id==user.institution_id).with_for_update().one()
        db.refresh(answer,with_for_update=True)
        from services.review_state_service import review_token
        if request.expected_review_token != review_token(answer):
            raise HTTPException(409, 'This decision changed or the page is out of date. Reload the saved decision before submitting your edits again.')
        running=db.query(ProcessingJob).filter(ProcessingJob.institution_id==user.institution_id,
            ProcessingJob.submission_id==answer.submission_id,
            ProcessingJob.status.in_(('queued','processing','retrying')),
            ProcessingJob.payload['operation'].as_string()=='regrade_corrected_answer',
            ProcessingJob.payload['answer_id'].as_string()==answer.id).with_for_update().first()
        if running:
            raise HTTPException(409,'A corrected-answer proposal is processing. Review the new proposal before saving an instructor decision.')
    from models import Question
    from services.grading_scope_service import is_external_question
    question = db.query(Question).filter(Question.id == answer.question_id).first()
    if request.apply_as_current and question and is_external_question(question):
        raise HTTPException(status_code=409, detail="This question is assessed outside MISRA. Historical evaluation-only labels remain allowed.")

    if answer.score is None or answer.max_score is None:
        raise HTTPException(
            status_code=409,
            detail="Grade the answer before resolving its review.",
        )

    from services.review_state_service import operational_run as find_operational_run
    operational_run = find_operational_run(db, answer)

    selected_run = operational_run
    if request.grading_run_id:
        selected_run = (
            db.query(GradingRun)
            .filter(GradingRun.id == request.grading_run_id)
            .first()
        )
        if not selected_run:
            raise HTTPException(status_code=404, detail="Grading run not found")
        if selected_run.answer_id != answer.id:
            raise HTTPException(
                status_code=409,
                detail="Grading run does not belong to this answer",
            )

    if (
        request.apply_as_current
        and selected_run
        and operational_run
        and selected_run.id != operational_run.id
    ):
        raise HTTPException(
            status_code=409,
            detail=(
                "A historical grading run cannot replace the current answer. "
                "Set apply_as_current to false to create an evaluation-only label."
            ),
        )

    ai_score = float(selected_run.score if selected_run else answer.score)
    max_score = float(selected_run.max_score if selected_run else answer.max_score)
    ai_final_confidence_snapshot = (
        selected_run.final_confidence if selected_run else answer.final_confidence
    )
    ai_needs_review_snapshot = (
        selected_run.needs_review if selected_run else answer.needs_review
    )
    ai_criteria_scores_snapshot = (
        selected_run.criteria_scores if selected_run else answer.criteria_scores
    )
    human_score = (
        request.human_score
        if request.action == "override"
        else ai_score
    )

    if human_score is None or human_score > max_score:
        raise HTTPException(
            status_code=422,
            detail=f"human_score must be between 0 and {max_score}.",
        )

    human_criteria_scores = (
        [item.model_dump() for item in request.human_criteria_scores]
        if request.human_criteria_scores
        else None
    )
    if human_criteria_scores:
        expected_criteria = {
            str(item.get("criterion_id")): float(item.get("max_points") or 0)
            for item in (ai_criteria_scores_snapshot or [])
        }
        supplied_criteria = {
            item["criterion_id"]: float(item["max_points"])
            for item in human_criteria_scores
        }
        if expected_criteria and supplied_criteria != expected_criteria:
            raise HTTPException(
                status_code=422,
                detail="Instructor criterion scores must match the graded rubric criteria.",
            )
        if abs(
            sum(float(item["points_earned"]) for item in human_criteria_scores)
            - float(human_score)
        ) > 0.01:
            raise HTTPException(
                status_code=422,
                detail="Instructor criterion scores must add up to the human score.",
            )

    if request.apply_as_current:
        raw = dict(answer.grading_raw_response or {})
        raw.pop('review_reopened', None)
        raw.pop('guide_review_required', None)
        answer.grading_raw_response = raw
        if request.action == "override":
            answer.teacher_override_score = human_score
            answer.review_status = "overridden"
        else:
            answer.teacher_override_score = None
            answer.review_status = "approved"

        answer.teacher_notes = request.reviewer_notes
        answer.needs_review = False
        answer.reviewed_by = user.id
        answer.reviewed_at = func.now()

    if selected_run:
        previous_label = (
            db.query(ReviewLabel)
            .filter(ReviewLabel.grading_run_id == selected_run.id)
            .order_by(ReviewLabel.created_at.desc(), ReviewLabel.id.desc())
            .first()
        )
    else:
        previous_label = (
            db.query(ReviewLabel)
            .filter(
                ReviewLabel.answer_id == answer.id,
                ReviewLabel.grading_run_id.is_(None),
            )
            .order_by(ReviewLabel.created_at.desc(), ReviewLabel.id.desc())
            .first()
        )

    label = ReviewLabel(
        answer_id=answer.id,
        grading_run_id=selected_run.id if selected_run else None,
        rubric_version_id=(
            selected_run.rubric_version_id if selected_run else None
        ),
        supersedes_label_id=previous_label.id if previous_label else None,
    )
    db.add(label)

    label.ai_score_snapshot = ai_score
    label.human_score = human_score
    label.ai_final_confidence_snapshot = ai_final_confidence_snapshot
    label.ai_needs_review_snapshot = ai_needs_review_snapshot
    label.ai_criteria_scores_snapshot = ai_criteria_scores_snapshot
    label.was_review_warranted = request.was_review_warranted
    label.human_criteria_scores = human_criteria_scores
    label.reviewer_notes = request.reviewer_notes
    label.review_reason_codes = [code.value for code in request.review_reason_codes]
    label.review_reason_note = request.review_reason_note
    label.label_source = "instructor_review"
    label.labeled_by = user.id
    label.rubric_version_id = (
        selected_run.rubric_version_id if selected_run else None
    )

    db.flush()
    if request.apply_as_current:
        answer.grading_raw_response = {**(answer.grading_raw_response or {}),
                                       'applied_review_label_id': label.id}
    record_audit_event(
        db,
        institution_id=user.institution_id,
        actor_id=user.id,
        action="grade_overridden" if request.action == "override" else "grade_approved",
        entity_type="answer",
        entity_id=answer.id,
        details={
            "submission_id": answer.submission_id,
            "grading_run_id": selected_run.id if selected_run else None,
            "ai_score": ai_score,
            "human_score": human_score,
            "apply_as_current": request.apply_as_current,
            "review_label_id": label.id,
            "review_reason_codes": label.review_reason_codes,
            "preference_reason_codes": [
                code.value
                for code in request.review_reason_codes
                if code in PREFERENCE_REASON_CODES
            ],
        },
    )

    db.commit()
    db.refresh(answer)
    db.refresh(label)

    return {"answer": answer, "review_label": label}
