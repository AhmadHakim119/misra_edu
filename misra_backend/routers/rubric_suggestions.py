from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from database import get_db
from models import Exam, Question, RubricSuggestion
from schemas.rubric_input import RubricSuggestionRequest
from services.rubric_service import suggest_rubric

router = APIRouter(prefix="/api", tags=["rubric-suggestions"])

@router.post("/exams/{exam_id}/suggest-rubric")
async def create_rubric_suggestion(exam_id: str, payload: RubricSuggestionRequest, db: Session = Depends(get_db)):
    exam = db.query(Exam).filter(Exam.id == exam_id).first()
    if not exam:
        raise HTTPException(status_code=404, detail=f"Exam {exam_id} not found")

    try:
        rubric = suggest_rubric(
            question_text=payload.question_text,
            subject=exam.title,
            max_score=payload.max_score,
            language=payload.language,
            answer_key=payload.answer_key,
            course_level=payload.course_level,
            expected_method=payload.expected_method,
            instructor_notes=payload.instructor_notes,
            grading_approach=payload.grading_approach,
            policy=payload.policy,
        )
    except ValueError as e:
        raise HTTPException(status_code=502, detail=f"Rubric suggestion failed: {e}")

    suggestion = RubricSuggestion(
        question_id=None,
        suggested_json=rubric.model_dump(),
        status="pending"
    )
    db.add(suggestion)
    db.commit()
    db.refresh(suggestion)

    return suggestion
