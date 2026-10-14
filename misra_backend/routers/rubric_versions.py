from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from database import get_db
from models import Exam, Question, RubricVersion, User
from schemas.rubric_input import (
    ExistingQuestionRubricSuggestionRequest,
    RubricVersionApprovalRequest,
    RubricVersionCreateRequest,
    RubricVersionUpdateRequest,
)
from services.rubric_service import suggest_rubric
from services.auth_dependencies import require_instructor
from services.audit_service import record_audit_event
from services.rubric_version_service import (
    approve_rubric_version,
    create_rubric_version,
    get_effective_rubric,
    update_rubric_version,
)


router = APIRouter(prefix="/api", tags=["rubric-versions"])


class AssessmentGuideApprovalRequest(BaseModel):
    review_token: str = Field(pattern=r'^[a-f0-9]{64}$')
    confirm_reviewed: bool


def _guide_exam(db, exam_id, user):
    exam = db.query(Exam).filter(Exam.id == exam_id, Exam.institution_id == user.institution_id).first()
    if not exam:
        raise HTTPException(404, 'Assessment not found')
    return exam


@router.get('/exams/{exam_id}/marking-guide')
def review_assessment_guide(exam_id: str, db: Session = Depends(get_db), user: User = Depends(require_instructor)):
    from services.assessment_guide_service import review_guide
    try:
        return review_guide(db, _guide_exam(db, exam_id, user))
    except ValueError as error:
        raise HTTPException(409, str(error)) from error


@router.post('/exams/{exam_id}/marking-guide/approve')
def approve_assessment_guide(exam_id: str, payload: AssessmentGuideApprovalRequest,
    db: Session = Depends(get_db), user: User = Depends(require_instructor)):
    from services.assessment_guide_service import approve_guide
    if not payload.confirm_reviewed:
        raise HTTPException(422, 'Confirm that you reviewed the whole guide before approval.')
    exam = _guide_exam(db, exam_id, user)
    try:
        changed = approve_guide(db, exam, user, payload.review_token)
        record_audit_event(db, institution_id=user.institution_id, actor_id=user.id,
            action='assessment_guide_approved', entity_type='exam', entity_id=exam.id,
            details={'review_token':payload.review_token, 'approved_version_ids':changed})
        db.commit()
        return {'exam_id':exam.id, 'approved_version_ids':changed,
            'message':'Assessment guide approved. Existing grades and historical snapshots are unchanged.'}
    except ValueError as error:
        db.rollback()
        raise HTTPException(409, str(error)) from error
    except Exception:
        db.rollback()
        raise


def _owned_question(db: Session, question_id: str, user: User) -> Question:
    question = (
        db.query(Question)
        .filter(
            Question.id == question_id,
            Question.institution_id == user.institution_id,
        )
        .first()
    )
    if not question:
        raise HTTPException(status_code=404, detail="Question not found")
    return question


def _owned_rubric_version(
    db: Session,
    version_id: str,
    user: User,
) -> RubricVersion:
    version = (
        db.query(RubricVersion)
        .join(Question, Question.id == RubricVersion.question_id)
        .filter(
            RubricVersion.id == version_id,
            Question.institution_id == user.institution_id,
        )
        .first()
    )
    if not version:
        raise HTTPException(status_code=404, detail="Rubric version not found")
    return version


@router.post("/questions/{question_id}/suggest-rubric-version")
def suggest_existing_question_rubric_version(
    question_id: str,
    payload: ExistingQuestionRubricSuggestionRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_instructor),
):
    question = _owned_question(db, question_id, user)
    if not question.question_text or not question.question_text.strip():
        raise HTTPException(
            status_code=422,
            detail="Question text is required before AI can suggest a rubric",
        )

    exam = (
        db.query(Exam)
        .filter(
            Exam.id == question.exam_id,
            Exam.institution_id == user.institution_id,
        )
        .first()
    )
    if not exam:
        raise HTTPException(status_code=404, detail="Question exam not found")
    if payload.grading_approach == "custom" and payload.policy is None:
        raise HTTPException(
            status_code=422,
            detail="A custom grading approach requires an explicit policy",
        )

    draft = db.query(RubricVersion).filter(RubricVersion.question_id == question_id,
        RubricVersion.status == 'draft').order_by(RubricVersion.version_number.desc()).first()
    if draft:
        current_rubric = draft.rubric_json
    else:
        try:
            current_rubric, _ = get_effective_rubric(question, db)
        except ValueError:
            current_rubric = {}
    try:
        from services.assessment_guide_service import review_guide
        from services.material_retrieval_service import retrieve_for_question, provider_sources
        from models import QuestionMaterialScopeVersion, AssessmentMaterialScopeVersion
        guide = review_guide(db, exam)
        guide_row = next(row for row in guide['questions'] if row['question_id'] == question.id)
        scope_data = guide_row['sources']
        context = None
        if scope_data and scope_data['mode'] != 'disabled':
            model = QuestionMaterialScopeVersion if guide_row['source_exception'] and guide_row['source_exception']['mode'] != 'inherit' else AssessmentMaterialScopeVersion
            context = provider_sources(retrieve_for_question(db, question, current_rubric,
                proposal_scope=db.get(model, scope_data['id'])))[0]
        rubric = suggest_rubric(
            question_text=question.question_text,
            subject=exam.title,
            max_score=float(question.max_score),
            language=question.language,
            answer_key=payload.answer_key or guide_row['answer_key']['reference_text'],
            course_level=payload.course_level,
            expected_method=payload.expected_method,
            instructor_notes=payload.instructor_notes,
            grading_approach=payload.grading_approach,
            policy=payload.policy,
            current_rubric=current_rubric,
            course_sources=context,
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
def get_active_rubric(
    question_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_instructor),
):
    question = _owned_question(db, question_id, user)

    try:
        rubric, version_id = get_effective_rubric(question, db)
    except ValueError as error:
        raise HTTPException(409, str(error)) from error
    return {
        "question_id": question.id,
        "rubric_version_id": version_id,
        "is_legacy_fallback": version_id is None,
        "rubric": rubric,
    }


@router.get("/questions/{question_id}/rubric-versions")
def list_rubric_versions(
    question_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_instructor),
):
    question = _owned_question(db, question_id, user)

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
    user: User = Depends(require_instructor),
):
    question = _owned_question(db, question_id, user)

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
    user: User = Depends(require_instructor),
):
    version = _owned_rubric_version(db, version_id, user)
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
    user: User = Depends(require_instructor),
):
    version = _owned_rubric_version(db, version_id, user)

    try:
        approved, regrade_required = approve_rubric_version(
            version=version,
            approved_by=user.id,
            db=db,
        )
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error

    record_audit_event(
        db,
        institution_id=user.institution_id,
        actor_id=user.id,
        action="rubric_approved",
        entity_type="rubric_version",
        entity_id=approved.id,
        details={
            "question_id": approved.question_id,
            "version_number": approved.version_number,
            "regrade_required": regrade_required,
        },
    )
    db.commit()

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
