from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from database import get_db
from models import Exam, Question, User
from services.auth_dependencies import require_instructor
from schemas.rubric_input import QuestionCreateRequest
from services.rubric_service import build_rubric
from services.rubric_version_service import attach_initial_approved_rubric

router = APIRouter(prefix="/api", tags=["questions"])


@router.get("/exams/{exam_id}/questions")
def list_exam_questions(
    exam_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_instructor),
):
    exam = db.query(Exam).filter(
        Exam.id == exam_id,
        Exam.institution_id == user.institution_id,
    ).first()
    if not exam:
        raise HTTPException(status_code=404, detail=f"Exam {exam_id} not found")

    return (
        db.query(Question)
        .filter(Question.exam_id == exam_id)
        .order_by(Question.order_index.asc(), Question.question_number.asc())
        .all()
    )

@router.post("/exams/{exam_id}/questions")
async def create_question(
    exam_id: str,
    payload: QuestionCreateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_instructor),
):
    exam = db.query(Exam).filter(
        Exam.id == exam_id,
        Exam.institution_id == user.institution_id,
    ).first()
    if not exam:
        raise HTTPException(status_code=404, detail=f"Exam {exam_id} not found")

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
        language=payload.language
    )
    db.add(question)
    db.flush()
    attach_initial_approved_rubric(
        question=question,
        rubric=rubric,
        source="manual",
        change_summary="Initial instructor-created rubric.",
        db=db,
    )
    db.commit()
    db.refresh(question)

    return question
