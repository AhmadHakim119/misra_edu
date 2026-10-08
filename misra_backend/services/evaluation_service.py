from collections import defaultdict
from typing import Any

from sqlalchemy.orm import Session

from models import Answer, GradingRun, Question, ReviewLabel, Submission
from schemas.review_input import PREFERENCE_REASON_VALUES
from services.grading_scope_service import is_external_question


EPSILON = 0.001
HIGH_CONFIDENCE_THRESHOLD = 80.0


def _rate(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 4) if denominator else None


def _criteria_by_id(items: list[dict] | None) -> dict[str, float]:
    return {
        item["criterion_id"]: float(item["points_earned"])
        for item in (items or [])
        if item.get("criterion_id") is not None and item.get("points_earned") is not None
    }


def _summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    count = len(rows)
    if not count:
        return {"label_count": 0, "mae": None, "exact_agreement": None, "plus_minus_one_agreement": None}

    errors = [row["absolute_error"] for row in rows]
    return {
        "label_count": count,
        "mae": round(sum(errors) / count, 4),
        "exact_agreement": _rate(sum(error < EPSILON for error in errors), count),
        "plus_minus_one_agreement": _rate(sum(error <= 1.0 + EPSILON for error in errors), count),
    }


def build_evaluation_report(
    db: Session,
    *,
    institution_id: str,
    exam_id: str | None = None,
) -> dict[str, Any]:
    query = (
        db.query(ReviewLabel, Answer, Question, GradingRun)
        .join(Answer, ReviewLabel.answer_id == Answer.id)
        .join(Question, Answer.question_id == Question.id)
        .join(Submission, Answer.submission_id == Submission.id)
        .outerjoin(GradingRun, ReviewLabel.grading_run_id == GradingRun.id)
        .filter(
            Submission.institution_id == institution_id,
            Answer.institution_id == institution_id,
            Question.institution_id == institution_id,
        )
        .order_by(ReviewLabel.created_at.desc(), ReviewLabel.id.desc())
    )
    if exam_id:
        query = query.filter(Submission.exam_id == exam_id)

    records: list[dict[str, Any]] = []
    excluded_external_labels = []
    criterion_records: list[dict[str, Any]] = []
    review_snapshot_records: list[dict[str, bool]] = []

    # A reviewer may revise a decision for the same grading run. Evaluation
    # represents the current instructor decision, while the database retains
    # every immutable revision for audit history. Follow the explicit
    # supersession chain first because database timestamps can share the same
    # precision and UUID ordering is not chronological.
    label_rows = query.all()
    superseded_label_ids = {
        label.supersedes_label_id
        for label, _answer, _question, _grading_run in label_rows
        if label.supersedes_label_id
    }
    latest_label_keys: set[tuple[str, str | None]] = set()
    for label, answer, question, grading_run in label_rows:
        if label.id in superseded_label_ids:
            continue
        label_key = (answer.id, label.grading_run_id)
        if label_key in latest_label_keys:
            continue
        latest_label_keys.add(label_key)
        if is_external_question(question):
            excluded_external_labels.append({"review_label_id": label.id, "grading_run_id": label.grading_run_id,
                "question_id": question.id, "question_number": question.question_number,
                "reason": "Currently approved as assessed outside MISRA; historical record retained."})
            continue
        ai_score = float(label.ai_score_snapshot)
        human_score = float(label.human_score)
        absolute_error = abs(ai_score - human_score)
        confidence = (
            float(label.ai_final_confidence_snapshot)
            if label.ai_final_confidence_snapshot is not None
            else (
                float(grading_run.final_confidence)
                if grading_run and grading_run.final_confidence is not None
                else None
            )
        )
        rubric_schema_version = (
            (grading_run.rubric_snapshot or {}).get("schema_version", 1)
            if grading_run
            else None
        )
        records.append({
            "review_label_id": label.id,
            "answer_id": answer.id,
            "grading_run_id": label.grading_run_id,
            "rubric_version_id": label.rubric_version_id,
            "rubric_schema_version": rubric_schema_version,
            "grading_mode": grading_run.mode if grading_run else None,
            "prompt_version": grading_run.prompt_version if grading_run else None,
            "question_id": question.id,
            "question_number": question.question_number,
            "ai_score": ai_score,
            "human_score": human_score,
            "absolute_error": absolute_error,
            "final_confidence": confidence,
            "was_review_warranted": bool(label.was_review_warranted),
            "review_reason_codes": list(label.review_reason_codes or []),
            "review_reason_note": label.review_reason_note,
            "preference_reason_codes": [
                code
                for code in (label.review_reason_codes or [])
                if code in PREFERENCE_REASON_VALUES
            ],
        })

        ai_criteria = _criteria_by_id(
            label.ai_criteria_scores_snapshot if label.ai_criteria_scores_snapshot is not None
            else grading_run.criteria_scores if grading_run else None
        )
        human_criteria = _criteria_by_id(label.human_criteria_scores)
        for criterion_id in sorted(set(ai_criteria) & set(human_criteria)):
            criterion_records.append({
                "criterion_id": criterion_id,
                "absolute_error": abs(ai_criteria[criterion_id] - human_criteria[criterion_id]),
            })

        if label.ai_needs_review_snapshot is not None:
            review_snapshot_records.append({
                "predicted_review": bool(label.ai_needs_review_snapshot),
                "warranted": bool(label.was_review_warranted),
            })

    overall = _summary(records)
    per_question_rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        per_question_rows[record["question_number"] if exam_id else record["question_id"]].append(record)

    criterion_rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in criterion_records:
        criterion_rows[record["criterion_id"]].append(record)

    rubric_schema_rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
    prompt_version_rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
    grading_mode_rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
    rubric_mode_rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        schema_key = (
            str(record["rubric_schema_version"])
            if record["rubric_schema_version"] is not None
            else "legacy_unversioned"
        )
        rubric_schema_rows[schema_key].append(record)
        prompt_key = record["prompt_version"] or "legacy_unversioned"
        prompt_version_rows[prompt_key].append(record)
        mode_key = record["grading_mode"] or "legacy_unversioned"
        grading_mode_rows[mode_key].append(record)
        rubric_mode_rows[f"schema_{schema_key}:{mode_key}"].append(record)

    review_warranted_count = sum(row["was_review_warranted"] for row in records)
    high_confidence_errors = [
        row for row in records
        if row["final_confidence"] is not None
        and row["final_confidence"] >= HIGH_CONFIDENCE_THRESHOLD
        and row["absolute_error"] > EPSILON
    ]

    review_metrics = None
    if review_snapshot_records:
        true_positive = sum(r["predicted_review"] and r["warranted"] for r in review_snapshot_records)
        false_positive = sum(r["predicted_review"] and not r["warranted"] for r in review_snapshot_records)
        false_negative = sum(not r["predicted_review"] and r["warranted"] for r in review_snapshot_records)
        review_metrics = {
            "snapshot_label_count": len(review_snapshot_records),
            "precision": _rate(true_positive, true_positive + false_positive),
            "recall": _rate(true_positive, true_positive + false_negative),
            "true_positive": true_positive,
            "false_positive": false_positive,
            "false_negative": false_negative,
        }

    latest_answers = {}
    for record in records:
        latest_answers.setdefault(record["answer_id"], record)
    return {
        "scope": {"exam_id": exam_id, "high_confidence_threshold": HIGH_CONFIDENCE_THRESHOLD,
                  "assessment_scope": "currently_approved_paper_questions"},
        "excluded_external_labels": excluded_external_labels,
        "latest_per_answer": _summary(list(latest_answers.values())),
        "unique_answer_count": len(latest_answers),
        "overall": overall,
        "review_warranted_rate": _rate(review_warranted_count, len(records)),
        "review_flag_metrics": review_metrics,
        "high_confidence_error_count": len(high_confidence_errors),
        "high_confidence_errors": high_confidence_errors,
        "per_question": {
            question_number: _summary(rows)
            for question_number, rows in sorted(per_question_rows.items())
        },
        "per_rubric_schema_version": {
            schema_version: _summary(rows)
            for schema_version, rows in sorted(rubric_schema_rows.items())
        },
        "per_prompt_version": {
            prompt_version: _summary(rows)
            for prompt_version, rows in sorted(prompt_version_rows.items())
        },
        "per_grading_mode": {
            grading_mode: _summary(rows)
            for grading_mode, rows in sorted(grading_mode_rows.items())
        },
        "per_rubric_schema_and_mode": {
            rubric_mode: _summary(rows)
            for rubric_mode, rows in sorted(rubric_mode_rows.items())
        },
        "criterion_level": {
            criterion_id: _summary(rows)
            for criterion_id, rows in sorted(criterion_rows.items())
        },
        "labels": records,
        "notes": [
            "Metrics are descriptive until the labelled sample is sufficiently large and representative.",
            "Review-flag precision/recall requires future labels with AI review snapshots; older labels may not contribute.",
            "Criterion-level metrics include only criteria with both AI and human criterion scores.",
            "Multiple labels for one answer represent separate grading-run/rubric-version observations.",
            "Historical confidence is never inferred from the answer's current mutable state.",
            "Externally assessed questions are excluded under the current approved scope; excluded label IDs remain listed for audit.",
            "Overall counts run observations, not independent answers. Latest-per-answer counts each answer once by its most recent instructor label.",
            "Historical criterion scores come only from label/run snapshots, never from mutable current answers.",
        ],
    }
