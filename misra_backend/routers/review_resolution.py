from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from database import get_db
from models import Answer, GradingRun, ReviewLabel
from schemas.review_input import ReviewResolutionRequest

router = APIRouter(prefix="/api", tags=["review"])


@router.post("/answers/{answer_id}/resolve-review")
def resolve_review(
    answer_id: str,
    request: ReviewResolutionRequest,
    db: Session = Depends(get_db),
):
    answer = db.query(Answer).filter(Answer.id == answer_id).first()
    if not answer:
        raise HTTPException(status_code=404, detail="Answer not found")

    if answer.score is None or answer.max_score is None:
        raise HTTPException(
            status_code=409,
            detail="Grade the answer before resolving its review.",
        )

    latest_run = (
        db.query(GradingRun)
        .filter(GradingRun.answer_id == answer.id)
        .order_by(GradingRun.created_at.desc(), GradingRun.id.desc())
        .first()
    )
    selected_run = latest_run
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
        and latest_run
        and selected_run.id != latest_run.id
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

    if request.apply_as_current:
        if request.action == "override":
            answer.teacher_override_score = human_score
            answer.review_status = "overridden"
        else:
            answer.teacher_override_score = None
            answer.review_status = "approved"

        answer.teacher_notes = request.reviewer_notes
        answer.needs_review = False
        answer.reviewed_at = func.now()

    if selected_run:
        label = (
            db.query(ReviewLabel)
            .filter(ReviewLabel.grading_run_id == selected_run.id)
            .first()
        )
    else:
        label = (
            db.query(ReviewLabel)
            .filter(
                ReviewLabel.answer_id == answer.id,
                ReviewLabel.grading_run_id.is_(None),
            )
            .first()
        )

    if not label:
        label = ReviewLabel(
            answer_id=answer.id,
            grading_run_id=selected_run.id if selected_run else None,
            rubric_version_id=(
                selected_run.rubric_version_id if selected_run else None
            ),
        )
        db.add(label)

    label.ai_score_snapshot = ai_score
    label.human_score = human_score
    label.ai_final_confidence_snapshot = ai_final_confidence_snapshot
    label.ai_needs_review_snapshot = ai_needs_review_snapshot
    label.ai_criteria_scores_snapshot = ai_criteria_scores_snapshot
    label.was_review_warranted = request.was_review_warranted
    label.human_criteria_scores = request.human_criteria_scores
    label.reviewer_notes = request.reviewer_notes
    label.label_source = request.label_source
    label.rubric_version_id = (
        selected_run.rubric_version_id if selected_run else None
    )

    db.commit()
    db.refresh(answer)
    db.refresh(label)

    return {"answer": answer, "review_label": label}
