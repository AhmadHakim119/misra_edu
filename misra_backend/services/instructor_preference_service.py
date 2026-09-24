"""Versioned, instructor-approved preference proposals.

Preference profiles are intentionally non-binding. They may be copied into an
editable assessment policy by a later, explicit instructor action, but this
service never mutates questions, rubrics, policies, answers, or grading runs.
"""

from copy import deepcopy
from datetime import datetime, timezone

from sqlalchemy import func

from models import Answer, InstructorPreferenceVersion, ReviewLabel, Submission, User
from schemas.instructor_preferences import InstructorPreferenceDraftRequest


DERIVATION_VERSION = "v1"
REVIEW_DERIVATION_VERSION = "review-v1"
MINIMUM_SUGGESTION_LABELS = 3
REVIEW_REASON_PROPOSALS = {
    "valid_alternative": {"alternative_methods_allowed": True},
    "minor_notation": {"notation_policy": "equivalent_allowed"},
    "method_credit": {"method_credit": "partial"},
    "carried_forward_error": {"error_carried_forward": "single_penalty"},
    "language_tolerance": {"language_quality_policy": "ignore_unless_assessed"},
}


def derive_proposal(
    scenario_answers: list[dict], explicit_preferences: dict | None = None
) -> tuple[dict, dict]:
    proposal: dict = {}
    provenance: dict = {}

    def proposed(field: str, value, scenario_id: str, selected_option: str):
        proposal[field] = value
        provenance[field] = {
            "source": "scenario",
            "scenario_id": scenario_id,
            "selected_option": selected_option,
            "derivation_version": DERIVATION_VERSION,
        }

    for answer in scenario_answers:
        scenario_id = answer["scenario_id"]
        option = answer["selected_option"]
        if scenario_id == "valid_alternative_method":
            method = {
                "full_credit": "full_if_valid",
                "partial_credit": "partial",
                "reject": "none",
            }[option]
            proposed("method_credit", method, scenario_id, option)
            proposed("alternative_methods_allowed", option != "reject", scenario_id, option)
        elif scenario_id == "minor_handwritten_syntax":
            syntax = {
                "full_credit": "accept_unambiguous",
                "minor_deduction": "criterion_specific",
                "reject": "require_correct",
            }[option]
            proposed("handwritten_syntax_policy", syntax, scenario_id, option)
        elif scenario_id == "equivalent_notation":
            notation = {
                "full_credit": "equivalent_allowed",
                "minor_deduction": "standard_required",
                "reject": "standard_required",
            }[option]
            proposed("notation_policy", notation, scenario_id, option)
        elif scenario_id == "carried_forward_error":
            proposed("error_carried_forward", option, scenario_id, option)
        elif scenario_id == "language_quality_outside_criterion":
            language = {
                "ignore": "ignore_unless_assessed",
                "minor_deduction": "criterion_specific",
                "assess": "assess",
            }[option]
            proposed("language_quality_policy", language, scenario_id, option)
    # Directly stated preferences take precedence over scenario-derived
    # suggestions. The translation is still only a proposal; no assessment is
    # changed by creating or approving this record.
    explicit_preferences = explicit_preferences or {}
    for field in (
        "method_credit",
        "handwritten_syntax_policy",
        "notation_policy",
        "error_carried_forward",
        "language_quality_policy",
    ):
        if field in explicit_preferences:
            proposal[field] = explicit_preferences[field]
            provenance[field] = {
                "source": "explicit_preference",
                "preference_field": field,
                "derivation_version": DERIVATION_VERSION,
            }
    alternative = explicit_preferences.get("alternative_valid_methods")
    if alternative in {"allow", "disallow"}:
        proposal["alternative_methods_allowed"] = alternative == "allow"
        provenance["alternative_methods_allowed"] = {
            "source": "explicit_preference",
            "preference_field": "alternative_valid_methods",
            "derivation_version": DERIVATION_VERSION,
        }
    elif alternative == "criterion_specific":
        proposal.pop("alternative_methods_allowed", None)
        provenance.pop("alternative_methods_allowed", None)
    return proposal, provenance


def public_version(version: InstructorPreferenceVersion) -> dict:
    result = {
        field: deepcopy(getattr(version, field))
        for field in (
            "id",
            "institution_id",
            "user_id",
            "version_number",
            "status",
            "explicit_preferences",
            "scenario_answers",
            "derived_proposal",
            "proposal_provenance",
            "change_summary",
            "created_by",
            "approved_by",
            "created_at",
            "approved_at",
        )
    }
    result["applies_automatically"] = False
    return result


def _lock_owner(db, user):
    return (
        db.query(User)
        .filter(User.id == user.id, User.institution_id == user.institution_id)
        .with_for_update()
        .one()
    )


def save_draft(
    payload: InstructorPreferenceDraftRequest,
    db,
    user,
    version: InstructorPreferenceVersion | None = None,
) -> InstructorPreferenceVersion:
    _lock_owner(db, user)
    if version is not None:
        db.refresh(version)
        if (
            version.user_id != user.id
            or version.institution_id != user.institution_id
            or version.status != "draft"
        ):
            raise ValueError(
                "Approved preference profiles are immutable. Create a new draft version."
            )

    explicit = payload.explicit_preferences.model_dump(exclude_none=True)
    scenarios = [answer.model_dump() for answer in payload.scenario_answers]
    proposal, provenance = derive_proposal(scenarios, explicit)

    if version is None:
        latest = (
            db.query(func.max(InstructorPreferenceVersion.version_number))
            .filter(
                InstructorPreferenceVersion.user_id == user.id,
                InstructorPreferenceVersion.institution_id == user.institution_id,
            )
            .scalar()
            or 0
        )
        version = InstructorPreferenceVersion(
            institution_id=user.institution_id,
            user_id=user.id,
            version_number=latest + 1,
            status="draft",
            created_by=user.id,
        )
        db.add(version)

    version.explicit_preferences = deepcopy(explicit)
    version.scenario_answers = deepcopy(scenarios)
    version.derived_proposal = proposal
    version.proposal_provenance = provenance
    version.change_summary = payload.change_summary
    db.flush()
    return version


def approve_draft(version: InstructorPreferenceVersion, db, user) -> InstructorPreferenceVersion:
    _lock_owner(db, user)
    db.refresh(version)
    if (
        version.user_id != user.id
        or version.institution_id != user.institution_id
        or version.status != "draft"
    ):
        raise ValueError("Only your own draft preference profile can be approved.")

    # Revalidate the persisted record and recompute deterministic proposal data
    # at the approval boundary.
    request = InstructorPreferenceDraftRequest(
        explicit_preferences=version.explicit_preferences,
        scenario_answers=version.scenario_answers,
        change_summary=version.change_summary,
    )
    scenarios = [answer.model_dump() for answer in request.scenario_answers]
    explicit = request.explicit_preferences.model_dump(exclude_none=True)
    proposal, provenance = derive_proposal(scenarios, explicit)
    version.explicit_preferences = explicit
    version.scenario_answers = scenarios
    version.derived_proposal = proposal
    version.proposal_provenance = provenance

    active = db.query(InstructorPreferenceVersion).filter(
        InstructorPreferenceVersion.user_id == user.id,
        InstructorPreferenceVersion.institution_id == user.institution_id,
        InstructorPreferenceVersion.status == "approved",
    )
    for previous in active.all():
        previous.status = "superseded"

    version.status = "approved"
    version.approved_by = user.id
    version.approved_at = datetime.now(timezone.utc).replace(tzinfo=None)
    db.flush()
    return version


def repeated_decision_suggestions(db, user) -> dict:
    """Return non-binding proposals supported by repeated, scoped decisions.

    Counting happens once per distinct review-label ID for each reason. Rubric,
    OCR/mapping, and free-form reasons are never preference evidence.
    """
    labels = (
        db.query(ReviewLabel)
        .join(Answer, Answer.id == ReviewLabel.answer_id)
        .join(Submission, Submission.id == Answer.submission_id)
        .filter(
            ReviewLabel.labeled_by == user.id,
            Submission.institution_id == user.institution_id,
            Answer.institution_id == user.institution_id,
        )
        .order_by(ReviewLabel.created_at.desc(), ReviewLabel.id.desc())
        .all()
    )
    source_ids: dict[str, set[str]] = {
        code: set() for code in REVIEW_REASON_PROPOSALS
    }
    superseded_label_ids = {
        label.supersedes_label_id
        for label in labels
        if label.supersedes_label_id
    }
    latest_keys: set[tuple[str, str | None]] = set()
    for label in labels:
        if label.id in superseded_label_ids:
            continue
        label_key = (label.answer_id, label.grading_run_id)
        if label_key in latest_keys:
            continue
        latest_keys.add(label_key)
        # Tolerance/credit preferences are supported only when the instructor
        # retained or increased the AI mark. A downward correction is not
        # evidence that the instructor wants a more permissive policy.
        if float(label.human_score) + 0.001 < float(label.ai_score_snapshot):
            continue
        # A malformed or legacy row cannot inflate a count by repeating a code.
        reasons = set(label.review_reason_codes or [])
        for code in reasons.intersection(REVIEW_REASON_PROPOSALS):
            source_ids[code].add(label.id)

    suggestions = []
    for code, proposed_policy in REVIEW_REASON_PROPOSALS.items():
        label_ids = sorted(source_ids[code])
        if len(label_ids) < MINIMUM_SUGGESTION_LABELS:
            continue
        suggestions.append(
            {
                "review_reason_code": code,
                "distinct_label_count": len(label_ids),
                "source_label_ids": label_ids,
                "proposed_policy": deepcopy(proposed_policy),
                "provenance": {
                    "source": "review_labels",
                    "review_reason_code": code,
                    "distinct_label_count": len(label_ids),
                    "minimum_distinct_labels": MINIMUM_SUGGESTION_LABELS,
                    "derivation_version": REVIEW_DERIVATION_VERSION,
                },
                "applies_automatically": False,
            }
        )
    return {
        "minimum_distinct_labels": MINIMUM_SUGGESTION_LABELS,
        "suggestions": suggestions,
        "excluded_reason_codes": [
            "rubric_issue",
            "ocr_or_mapping_error",
            "other",
        ],
        "applies_automatically": False,
    }
