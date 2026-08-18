from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from database import get_db
from models import Exam, Question, RubricVersion
from schemas.rubric_input import (
    ExistingQuestionRubricSuggestionRequest,
    RubricVersionApprovalRequest,
    RubricVersionCreateRequest,
    RubricVersionUpdateRequest,
)
from services.rubric_service import suggest_rubric
from services.rubric_version_service import (
    approve_rubric_version,
    create_rubric_version,
    get_effective_rubric,
    update_rubric_version,
)


router = APIRouter(prefix="/api", tags=["rubric-versions"])


@router.post("/questions/{question_id}/suggest-rubric-version")
def suggest_existing_question_rubric_version(
    question_id: str,
    payload: ExistingQuestionRubricSuggestionRequest,
    db: Session = Depends(get_db),
):
    question = db.query(Question).filter(Question.id == question_id).first()
    if not question:
        raise HTTPException(status_code=404, detail="Question not found")
    if not question.question_text or not question.question_text.strip():
        raise HTTPException(
            status_code=422,
            detail="Question text is required before AI can suggest a rubric",
        )

    exam = db.query(Exam).filter(Exam.id == question.exam_id).first()
    if not exam:
        raise HTTPException(status_code=404, detail="Question exam not found")
    if payload.grading_approach == "custom" and payload.policy is None:
        raise HTTPException(
            status_code=422,
            detail="A custom grading approach requires an explicit policy",
        )

    current_rubric, _ = get_effective_rubric(question, db)
    try:
        rubric = suggest_rubric(
            question_text=question.question_text,
            subject=exam.title,
            max_score=float(question.max_score),
            language=question.language,
            answer_key=payload.answer_key,
            course_level=payload.course_level,
            expected_method=payload.expected_method,
            instructor_notes=payload.instructor_notes,
            grading_approach=payload.grading_approach,
            policy=payload.policy,
            current_rubric=current_rubric,
        )
    except ValueError as error:
        raise HTTPException(
            status_code=502,
            detail=f"Rubric suggestion failed: {error}",
        ) from error

    try:
        version = create_rubric_version(
            question=question,
            rubric_json=rubric.model_dump(),
            source="ai",
            change_summary=(
                payload.change_summary
                or "AI-generated Rubric V2 draft for instructor review."
            ),
            db=db,
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error

    return {
        "rubric_version": version,
        "active_rubric_version_id": question.active_rubric_version_id,
        "message": (
            "AI rubric draft created. Review or edit it, then approve it explicitly "
            "to make it active."
        ),
    }


@router.get("/questions/{question_id}/rubric")
def get_active_rubric(question_id: str, db: Session = Depends(get_db)):
    question = db.query(Question).filter(Question.id == question_id).first()
    if not question:
        raise HTTPException(status_code=404, detail="Question not found")

    rubric, version_id = get_effective_rubric(question, db)
    return {
        "question_id": question.id,
        "rubric_version_id": version_id,
        "is_legacy_fallback": version_id is None,
        "rubric": rubric,
    }


@router.get("/questions/{question_id}/rubric-versions")
def list_rubric_versions(question_id: str, db: Session = Depends(get_db)):
    question = db.query(Question).filter(Question.id == question_id).first()
    if not question:
        raise HTTPException(status_code=404, detail="Question not found")

    return (
        db.query(RubricVersion)
        .filter(RubricVersion.question_id == question_id)
        .order_by(RubricVersion.version_number.desc())
        .all()
    )


@router.post("/questions/{question_id}/rubric-versions")
def create_draft_rubric_version(
    question_id: str,
    payload: RubricVersionCreateRequest,
    db: Session = Depends(get_db),
):
    question = db.query(Question).filter(Question.id == question_id).first()
    if not question:
        raise HTTPException(status_code=404, detail="Question not found")

    try:
        return create_rubric_version(
            question=question,
            rubric_json=payload.rubric,
            source=payload.source,
            change_summary=payload.change_summary,
            db=db,
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.put("/rubric-versions/{version_id}")
def update_draft_rubric_version(
    version_id: str,
    payload: RubricVersionUpdateRequest,
    db: Session = Depends(get_db),
):
    version = db.query(RubricVersion).filter(RubricVersion.id == version_id).first()
    if not version:
        raise HTTPException(status_code=404, detail="Rubric version not found")
    if version.status != "draft":
        raise HTTPException(
            status_code=409,
            detail="Only draft rubric versions can be edited",
        )

    try:
        return update_rubric_version(
            version=version,
            rubric_json=payload.rubric,
            change_summary=payload.change_summary,
            db=db,
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.post("/rubric-versions/{version_id}/approve")
def approve_draft_rubric_version(
    version_id: str,
    payload: RubricVersionApprovalRequest,
    db: Session = Depends(get_db),
):
    version = db.query(RubricVersion).filter(RubricVersion.id == version_id).first()
    if not version:
        raise HTTPException(status_code=404, detail="Rubric version not found")

    try:
        approved, regrade_required = approve_rubric_version(
            version=version,
            approved_by=payload.approved_by,
            db=db,
        )
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error

    return {
        "rubric_version": approved,
        "regrade_required": regrade_required,
        "message": (
            "Approved. Existing grading runs retain their original rubric snapshots; "
            "regrade answers explicitly to apply this version."
            if regrade_required
            else "Approved and activated."
        ),
    }
