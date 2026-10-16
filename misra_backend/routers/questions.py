from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from database import get_db
from models import Exam, Question, RubricVersion, User
from services.auth_dependencies import require_instructor
from schemas.rubric_input import QuestionCreateRequest
from services.rubric_service import build_rubric
from services.rubric_version_service import attach_initial_approved_rubric

router = APIRouter(prefix="/api", tags=["questions"])


@router.delete('/questions/{question_id}', status_code=204)
def delete_question(question_id: str, db: Session = Depends(get_db), user: User = Depends(require_instructor)):
    from services.question_deletion_service import delete_draft_question
    delete_draft_question(db, user, question_id)


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

    if not payload.approve_initial_rubric and payload.policy is None:
        from services.account_settings_service import apply_to_new_draft
        rubric = apply_to_new_draft(db, user, rubric)

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
    if payload.approve_initial_rubric:
        attach_initial_approved_rubric(
            question=question,
            rubric=rubric,
            source="manual",
            change_summary="Initial instructor-created rubric.",
            approved_by=user.id,
            db=db,
        )
    else:
        # Keep question and initial draft atomic. The presence of an unapproved
        # version blocks the legacy-JSON fallback in get_effective_rubric.
        db.add(RubricVersion(
            question_id=question.id,
            version_number=1,
            schema_version=2,
            rubric_json=rubric.model_dump(),
            grading_approach=rubric.policy.grading_approach,
            source="manual",
            status="draft",
            change_summary="Initial instructor draft; approval required.",
            created_by=user.id,
        ))
    db.commit()
    db.refresh(question)

    return question
