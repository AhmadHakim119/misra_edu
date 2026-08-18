from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from datetime import datetime, timezone

from database import get_db
from models import RubricSuggestion, Question, Exam
from schemas.rubric_input import RubricResolutionRequest
from services.rubric_service import build_rubric
from services.rubric_version_service import attach_initial_approved_rubric

router = APIRouter(prefix="/api", tags=["rubric-suggestions"])


@router.post("/rubric-suggestions/{suggestion_id}/resolve")
async def resolve_rubric_suggestion(
    suggestion_id: str,
    payload: RubricResolutionRequest,
    exam_id: str,
    db: Session = Depends(get_db)
):
    suggestion = db.query(RubricSuggestion).filter(RubricSuggestion.id == suggestion_id).first()
    if not suggestion:
        raise HTTPException(status_code=404, detail=f"RubricSuggestion {suggestion_id} not found")

    if suggestion.status != "pending":
        raise HTTPException(status_code=409, detail=f"Suggestion already resolved with status '{suggestion.status}'")

    if payload.action == "reject":
        suggestion.status = "rejected"
        suggestion.resolved_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(suggestion)
        return suggestion

    # action == "accept"
    exam = db.query(Exam).filter(Exam.id == exam_id).first()
    if not exam:
        raise HTTPException(status_code=404, detail=f"Exam {exam_id} not found")

    if not payload.criteria or payload.max_score is None or not payload.question_number or not payload.question_text:
        raise HTTPException(status_code=422, detail="Accepting a suggestion requires question_number, question_text, max_score, and criteria")

    try:
        rubric = build_rubric(
            max_score=payload.max_score,
            criteria=[criterion.model_dump() for criterion in payload.criteria],
            grading_approach=payload.grading_approach,
            policy=payload.policy,
            acceptable_answers=payload.acceptable_answers,
            notes=payload.notes,
            reference_context=payload.reference_context,
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=f"Invalid rubric: {error}") from error

    existing_count = db.query(Question).filter(Question.exam_id == exam_id).count()

    question = Question(
        institution_id=exam.institution_id,
        exam_id=exam_id,
        question_number=payload.question_number,
        question_text=payload.question_text,
        max_score=payload.max_score,
        rubric_json=rubric.model_dump(),
        order_index=existing_count + 1,
        language=payload.language or "en"
    )
    db.add(question)
    db.flush()

    attach_initial_approved_rubric(
        question=question,
        rubric=rubric,
        source="ai",
        change_summary="Initial rubric accepted from an AI suggestion.",
        db=db,
    )

    suggestion.status = "accepted" if rubric.model_dump() == suggestion.suggested_json else "edited"
    suggestion.final_json = rubric.model_dump()
    suggestion.question_id = question.id
    suggestion.resolved_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(question)
    db.refresh(suggestion)

    return {
        "suggestion": {
            "id": suggestion.id,
            "question_id": suggestion.question_id,
            "status": suggestion.status,
            "suggested_json": suggestion.suggested_json,
            "final_json": suggestion.final_json,
            "generated_at": suggestion.generated_at,
            "resolved_at": suggestion.resolved_at,
        },
        "question": {
            "id": question.id,
            "exam_id": question.exam_id,
            "question_number": question.question_number,
            "question_text": question.question_text,
            "max_score": question.max_score,
            "rubric_json": question.rubric_json,
            "order_index": question.order_index,
            "language": question.language,
            "created_at": question.created_at,
        }
    }
