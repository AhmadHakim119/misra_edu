from pydantic import ValidationError
from sqlalchemy import func
from sqlalchemy.orm import Session

from models import Answer, GradingRun, Question, RubricVersion
from schemas.rubric_v2 import RubricV2
from services.assessment_readiness_service import definition_errors


def validate_rubric_v2(rubric_json: dict) -> RubricV2:
    try:
        if 'question_definition' in rubric_json:
            from services.question_definition_service import correction_document
            correction_document(rubric_json['question_definition'])
        return RubricV2(**rubric_json)
    except ValidationError as error:
        raise ValueError(f"Invalid Rubric V2 document: {error}") from error


def version_document(raw, rubric):
    value = rubric.model_dump()
    if 'question_definition' in raw:
        from services.question_definition_service import correction_document
        value['question_definition'] = correction_document(raw['question_definition'])
    return value


def grading_rubric(document):
    # Definition history is local provenance. The current approved question is
    # supplied separately in the grading package, never as rubric instructions.
    return {key:value for key,value in document.items() if key != 'question_definition'}


def require_guide_review(question, db, *, active_version_id=None, reason=None):
    """Invalidate current approval, never the mark, run or immutable human label."""
    for answer in db.query(Answer).filter(Answer.question_id == question.id,
            Answer.institution_id == question.institution_id, Answer.score.is_not(None)).with_for_update().all():
        raw = dict(answer.grading_raw_response or {})
        raw['guide_review_required'] = {'active_version_id':active_version_id,
            'reason':reason or 'The marking guide was reopened or replaced after this proposal. Compare its saved snapshot before finalizing again.'}
        answer.grading_raw_response = raw
        answer.needs_review = True
        answer.review_status = 'pending'


def get_effective_rubric(
    question: Question,
    db: Session,
) -> tuple[dict, str | None]:
    """Resolve the approved rubric, falling back to legacy question JSON."""
    from services.grading_scope_service import is_removed_question
    if is_removed_question(question):
        raise ValueError('This question was removed from the exam. Its saved results remain in history.')
    if question.active_rubric_version_id:
        version = (
            db.query(RubricVersion)
            .filter(
                RubricVersion.id == question.active_rubric_version_id,
                RubricVersion.question_id == question.id,
                RubricVersion.status == "approved",
            )
            .first()
        )
        if version:
            errors = definition_errors(question, version.rubric_json)
            if errors:
                raise ValueError('Assessment setup needs attention: ' + ' '.join(errors))
            return grading_rubric(version.rubric_json), version.id
    if db.query(RubricVersion).filter(RubricVersion.question_id == question.id).first():
        raise ValueError('This question has no approved rubric. Review and approve its draft first.')
    errors = definition_errors(question, question.rubric_json)
    if errors:
        raise ValueError('Assessment setup needs attention: ' + ' '.join(errors))
    return grading_rubric(question.rubric_json), None


def attach_initial_approved_rubric(
    *,
    question: Question,
    rubric: RubricV2,
    source: str,
    db: Session,
    change_summary: str | None = None,
    approved_by: str | None = None,
) -> RubricVersion:
    """Attach version 1 while the caller owns the surrounding transaction."""
    version = RubricVersion(
        question_id=question.id,
        version_number=1,
        schema_version=2,
        rubric_json=rubric.model_dump(),
        grading_approach=rubric.policy.grading_approach,
        source=source,
        status="approved",
        change_summary=change_summary,
        created_by=approved_by,
        approved_by=approved_by,
        approved_at=func.now(),
    )
    db.add(version)
    db.flush()
    question.active_rubric_version_id = version.id
    question.rubric_json = rubric.model_dump()
    return version


def create_rubric_version(
    *,
    question: Question,
    rubric_json: dict,
    source: str,
    change_summary: str | None,
    db: Session,
    created_by: str | None = None,
) -> RubricVersion:
    rubric = validate_rubric_v2(rubric_json)
    document = version_document(rubric_json, rubric)
    if 'question_definition' in document:
        from services.question_definition_service import current_definition
        definition = document['question_definition']
        current = current_definition(question)
        if all(definition[key] == value for key, value in current.items()):
            definition['previous'] = current
    latest_number = (
        db.query(func.max(RubricVersion.version_number))
        .filter(RubricVersion.question_id == question.id)
        .scalar()
        or 0
    )
    version = RubricVersion(
        question_id=question.id,
        version_number=latest_number + 1,
        schema_version=2,
        rubric_json=document,
        grading_approach=rubric.policy.grading_approach,
        source=source,
        status="draft",
        change_summary=change_summary,
        created_by=created_by,
    )
    db.add(version)
    db.commit()
    db.refresh(version)
    return version


def update_rubric_version(
    *,
    version: RubricVersion,
    rubric_json: dict,
    change_summary: str | None,
    db: Session,
) -> RubricVersion:
    if version.status != "draft":
        raise ValueError("Only draft rubric versions can be edited")

    rubric = validate_rubric_v2(rubric_json)
    version.rubric_json = version_document(rubric_json, rubric)
    version.grading_approach = rubric.policy.grading_approach
    version.change_summary = change_summary
    db.commit()
    db.refresh(version)
    return version


def approve_rubric_version(
    *,
    version: RubricVersion,
    db: Session,
    approved_by: str | None = None,
    commit: bool = True,
    definition_batch_validated: bool = False,
) -> tuple[RubricVersion, bool]:
    if version.status != "draft":
        raise ValueError("Only a draft rubric version can be approved")

    rubric = validate_rubric_v2(version.rubric_json)
    question = db.query(Question).filter(Question.id == version.question_id).first()
    if not question:
        raise ValueError(f"Question {version.question_id} not found")
    from services.grading_scope_service import is_removed_question
    if is_removed_question(question):
        raise ValueError('Restore the removed question from Extraction before approving a new marking version.')

    from services.question_definition_service import apply_definition, current_definition, proposed_definition
    if proposed_definition(question, version.rubric_json) != current_definition(question) and not definition_batch_validated:
        raise ValueError('Question number and wording corrections require whole-guide review and approval.')
    apply_definition(question, version.rubric_json, db, batch_validated=definition_batch_validated)

    previous_version_id = question.active_rubric_version_id
    if previous_version_id:
        previous = (
            db.query(RubricVersion)
            .filter(RubricVersion.id == previous_version_id)
            .first()
        )
        if previous and previous.id != version.id:
            previous.status = "superseded"

    version.status = "approved"
    version.approved_by = approved_by
    version.approved_at = func.now()

    # Keep the legacy column as a denormalized compatibility copy.
    question.active_rubric_version_id = version.id
    question.rubric_json = version_document(version.rubric_json, rubric)
    question.max_score = rubric.max_score
    if previous_version_id != version.id:
        require_guide_review(question, db, active_version_id=version.id)

    has_prior_runs = (
        db.query(GradingRun)
        .join(Answer, GradingRun.answer_id == Answer.id)
        .filter(Answer.question_id == question.id)
        .first()
        is not None
    )

    if commit:
        db.commit()
        db.refresh(version)
    else:
        db.flush()
    return version, has_prior_runs
