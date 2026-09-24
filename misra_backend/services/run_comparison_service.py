from sqlalchemy.orm import Session

from models import Answer, GradingRun, QuestionGradingPolicy
from services.confidence_config import ACTIVE_CONFIG
from services.review_state_service import resolved_review_status

DEFAULT_ABSOLUTE_THRESHOLD = 0.5
DEFAULT_RELATIVE_THRESHOLD = 0.20
DISAGREEMENT_CONFIDENCE_CAP = 40.0


def _comparison_context(run: GradingRun) -> dict | None:
    package = (run.response_json or {}).get("grading_package")
    if not package:
        return None
    # Page-image availability and selected mode are the intentional differences
    # in a mode audit. All actual definitions and source evidence must match.
    fields = ("schema_version", "institution_id", "assessment_id", "submission_id",
              "answer_id", "question", "rubric_version_id", "rubric",
              "policy_version_id", "policy", "answer_key", "student_document_sha256")
    context = {field: package.get(field) for field in fields}
    context["student_evidence"] = [item for item in package.get("student_evidence", [])
                                   if item.get("kind") != "student_image"]
    # A mode audit intentionally has different selection reasons and audit flags.
    # Compare only the policy configuration that must stay stable across runs.
    routing = package.get("routing", {})
    context["routing"] = {key: routing.get(key) for key in (
        "policy_mode", "policy_enabled", "audit_rate", "material_absolute_points",
        "material_relative_ratio", "min_validated_samples",
    ) if key in routing}
    return context


def _paired_runs(
    answer_id: str,
    comparison_pair_id: str,
    db: Session,
) -> dict[str, GradingRun]:
    runs = (
        db.query(GradingRun)
        .filter(GradingRun.answer_id == answer_id)
        .order_by(GradingRun.created_at.desc(), GradingRun.id.desc())
        .all()
    )

    paired = {}
    for run in runs:
        package = (run.response_json or {}).get("grading_package") or {}
        routing = package.get("routing") or {}
        if routing.get("comparison_pair_id") != comparison_pair_id:
            continue
        if run.mode in {"text_only", "image_text"} and run.mode not in paired:
            paired[run.mode] = run
    return paired


def _criterion_differences(text_run: GradingRun, image_run: GradingRun) -> list[dict]:
    text_scores = {
        item["criterion_id"]: float(item["points_earned"])
        for item in (text_run.criteria_scores or [])
    }
    image_scores = {
        item["criterion_id"]: float(item["points_earned"])
        for item in (image_run.criteria_scores or [])
    }

    differences = []
    for criterion_id in sorted(set(text_scores) | set(image_scores)):
        text_points = text_scores.get(criterion_id, 0.0)
        image_points = image_scores.get(criterion_id, 0.0)
        if abs(text_points - image_points) > 0.001:
            differences.append({
                "criterion_id": criterion_id,
                "text_only_points": text_points,
                "image_text_points": image_points,
            })
    return differences


def apply_material_disagreement_gate(
    answer: Answer,
    db: Session,
    *,
    comparison_pair_id: str | None = None,
) -> bool:
    """Flag only a text/image pair created by the same audit operation."""
    if not comparison_pair_id:
        return False
    paired = _paired_runs(answer.id, comparison_pair_id, db)
    text_run = paired.get("text_only")
    image_run = paired.get("image_text")

    if not text_run or not image_run:
        return False

    if _comparison_context(text_run) != _comparison_context(image_run):
        human_review_status = resolved_review_status(answer)
        answer.needs_review = not bool(human_review_status)
        answer.review_status = human_review_status or "pending"
        answer.final_confidence = min(
            float(answer.final_confidence if answer.final_confidence is not None else 100),
            DISAGREEMENT_CONFIDENCE_CAP,
        )
        answer.review_reasons = {
            "code": "grading_context_changed",
            "comparison_pair_id": comparison_pair_id,
            "text_only_run_id": text_run.id,
            "image_text_run_id": image_run.id,
            "message": "Approved definitions or student evidence changed between runs; mode comparison is unavailable.",
        }
        return True

    max_score = max(float(text_run.max_score), float(image_run.max_score))
    score_difference = abs(float(text_run.score) - float(image_run.score))
    policy = (
        db.query(QuestionGradingPolicy)
        .filter(
            QuestionGradingPolicy.question_id == answer.question_id,
            QuestionGradingPolicy.enabled.is_(True),
        )
        .first()
    )
    absolute_threshold = float(policy.material_absolute_points) if policy else DEFAULT_ABSOLUTE_THRESHOLD
    relative_threshold = float(policy.material_relative_ratio) if policy else DEFAULT_RELATIVE_THRESHOLD
    threshold = max(absolute_threshold, max_score * relative_threshold)
    criterion_differences = _criterion_differences(text_run, image_run)
    human_review_status = resolved_review_status(answer)

    if score_difference < threshold and not criterion_differences:
        # A fresh agreeing pair supersedes an older disagreement. Restore the
        # confidence of the grading mode currently displayed on the answer.
        existing_reason = answer.review_reasons or {}
        if existing_reason.get("code") in {"material_mode_disagreement", "grading_context_changed"}:
            displayed_mode = (answer.grading_raw_response or {}).get("mode")
            displayed_run = image_run if displayed_mode == "image_text" else text_run
            answer.final_confidence = float(displayed_run.final_confidence)
            if human_review_status:
                answer.needs_review = False
                answer.review_status = human_review_status
            else:
                answer.needs_review = (
                    answer.final_confidence < ACTIVE_CONFIG.needs_review_threshold
                )
                answer.review_status = "pending" if answer.needs_review else "none"
            answer.review_reasons = None
        return False

    if human_review_status:
        answer.needs_review = False
        answer.review_status = human_review_status
    else:
        answer.needs_review = True
        answer.review_status = "pending"
    answer.final_confidence = min(
        float(answer.final_confidence or 100),
        DISAGREEMENT_CONFIDENCE_CAP,
    )
    answer.review_reasons = {
        "code": "material_mode_disagreement",
        "comparison_pair_id": comparison_pair_id,
        "text_only_run_id": text_run.id,
        "image_text_run_id": image_run.id,
        "text_only_score": float(text_run.score),
        "image_text_score": float(image_run.score),
        "score_difference": score_difference,
        "material_threshold": threshold,
        "policy_mode": policy.mode if policy else "default",
        "criterion_differences": criterion_differences,
    }
    return True
