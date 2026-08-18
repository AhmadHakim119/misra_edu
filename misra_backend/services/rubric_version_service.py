from pydantic import ValidationError
from sqlalchemy import func
from sqlalchemy.orm import Session

from models import Answer, GradingRun, Question, RubricVersion
from schemas.rubric_v2 import RubricV2


def validate_rubric_v2(rubric_json: dict) -> RubricV2:
    try:
        return RubricV2(**rubric_json)
    except ValidationError as error:
        raise ValueError(f"Invalid Rubric V2 document: {error}") from error


def get_effective_rubric(
    question: Question,
    db: Session,
) -> tuple[dict, str | None]:
    """Resolve the approved rubric, falling back to legacy question JSON."""
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
            return version.rubric_json, version.id
    return question.rubric_json, None


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
        rubric_json=rubric.model_dump(),
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
    version.rubric_json = rubric.model_dump()
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
) -> tuple[RubricVersion, bool]:
    if version.status != "draft":
        raise ValueError("Only a draft rubric version can be approved")

    rubric = validate_rubric_v2(version.rubric_json)
    question = db.query(Question).filter(Question.id == version.question_id).first()
    if not question:
        raise ValueError(f"Question {version.question_id} not found")

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
    question.rubric_json = rubric.model_dump()
    question.max_score = rubric.max_score

    has_prior_runs = (
        db.query(GradingRun)
        .join(Answer, GradingRun.answer_id == Answer.id)
        .filter(Answer.question_id == question.id)
        .first()
        is not None
    )

    db.commit()
    db.refresh(version)
    return version, has_prior_runs
