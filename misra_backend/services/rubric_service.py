import json
from typing import Iterable

from pydantic import ValidationError

from schemas.rubric_v2 import (
    GradingApproach,
    RubricCriterionV2,
    RubricPolicy,
    RubricV2,
)
from services.gemini_client import generate


# Compatibility aliases for modules that previously imported these names.
RubricCriterion = RubricCriterionV2
Rubric = RubricV2


POLICY_PRESETS: dict[str, dict] = {
    "lenient": {
        "grading_approach": "lenient",
        "method_credit": "full_if_valid",
        "arithmetic_error_policy": "single_penalty",
        "rounding_tolerance_percent": 2.0,
        "units_policy": "do_not_penalize",
        "notation_policy": "do_not_penalize",
        "alternative_methods_allowed": True,
        "evidence_requirement": "key_steps",
        "illegible_response_policy": "manual_review",
    },
    "balanced": {
        "grading_approach": "balanced",
        "method_credit": "partial",
        "arithmetic_error_policy": "single_penalty",
        "rounding_tolerance_percent": 1.0,
        "units_policy": "required_when_applicable",
        "notation_policy": "equivalent_allowed",
        "alternative_methods_allowed": True,
        "evidence_requirement": "key_steps",
        "illegible_response_policy": "manual_review",
    },
    "strict": {
        "grading_approach": "strict",
        "method_credit": "partial",
        "arithmetic_error_policy": "penalize_each",
        "rounding_tolerance_percent": 0,
        "units_policy": "required",
        "notation_policy": "standard_required",
        "alternative_methods_allowed": True,
        "evidence_requirement": "complete_reasoning",
        "illegible_response_policy": "manual_review",
    },
}


def policy_for_approach(
    grading_approach: GradingApproach,
    policy: RubricPolicy | None = None,
) -> RubricPolicy:
    """Return transparent preset values or validate an instructor custom policy."""
    if policy is not None:
        return policy
    if grading_approach == "custom":
        raise ValueError("custom grading approach requires an explicit policy")
    return RubricPolicy(**POLICY_PRESETS[grading_approach])


def build_rubric(
    *,
    max_score: float,
    criteria: Iterable[dict],
    grading_approach: GradingApproach = "balanced",
    policy: RubricPolicy | None = None,
    acceptable_answers: list[str] | None = None,
    notes: str | None = None,
    reference_context: str | None = None,
) -> RubricV2:
    normalized_criteria = []
    for raw in criteria:
        item = dict(raw)
        item["title"] = item.get("title") or item["description"][:160]
        scoring_type = item.get("scoring_type")
        if scoring_type is None:
            scoring_type = "scaled" if item.get("partial_credit_allowed", True) else "binary"
        item["scoring_type"] = scoring_type
        item["partial_credit_allowed"] = scoring_type == "scaled"
        if not item.get("id"):
            item.pop("id", None)
        normalized_criteria.append(RubricCriterionV2(**item))

    return RubricV2(
        max_score=max_score,
        criteria=normalized_criteria,
        policy=policy_for_approach(grading_approach, policy),
        acceptable_answers=acceptable_answers,
        notes=notes,
        reference_context=reference_context,
    )


RUBRIC_SUGGESTION_PROMPT = """
You are an academic assessment-design assistant. Produce an instructor-editable,
criterion-level rubric. The rubric is a draft and must make its assumptions explicit.

ASSESSMENT CONTEXT
Subject: {subject}
Course level: {course_level}
Language: {language}
Maximum score: {max_score}
Grading approach: {grading_approach}

Question:
{question_text}

Instructor answer key or reference solution:
{answer_key}

Expected method, if specified:
{expected_method}

Instructor notes:
{instructor_notes}

CURRENT RUBRIC, IF THIS IS A VERSION UPGRADE
{current_rubric_json}

GRADING POLICY (authoritative JSON)
{policy_json}

INSTRUCTIONS
1. Create atomic criteria. Do not combine a proof, calculation, diagram, and final
   conclusion into one large criterion when they can be evaluated separately.
2. Use 2-7 criteria unless the question genuinely needs fewer or more.
3. Criterion points must sum exactly to {max_score}.
4. Give every criterion a stable short snake_case id and a concise title.
5. Use scoring_type "binary" only when no defensible partial credit exists. Binary
   criteria must set partial_credit_allowed to false.
6. For scaled criteria, provide clear performance levels including zero, full credit,
   and at least one partial-credit level when the point range permits it.
7. Describe required evidence, common mistakes and their grading effect, and valid
   alternative methods. Follow the grading policy exactly.
8. Apply error propagation fairly. Do not repeatedly penalize one arithmetic mistake
   unless the policy explicitly requires it.
9. If the answer key or question is ambiguous, record the ambiguity in notes instead
   of silently inventing facts.
10. Keep criterion descriptions observable: state what must appear in the student's
   work, not vague qualities such as "shows understanding."
11. Write learner-facing content in Arabic for Arabic questions; otherwise use English.
12. When a current rubric is provided, treat it as a starting point. Preserve useful
    criterion ids when their meaning is unchanged, but split coarse criteria and revise
    unclear scoring guidance when needed. Do not preserve a flaw merely for compatibility.

Return only valid JSON matching this structure:
{{
  "schema_version": 2,
  "max_score": {max_score},
  "criteria": [
    {{
      "id": "stable_snake_case_id",
      "title": "Concise criterion title",
      "description": "Observable evidence being assessed",
      "points": 1.0,
      "scoring_type": "scaled",
      "partial_credit_allowed": true,
      "performance_levels": [
        {{"label": "Full", "description": "...", "points_earned": 1.0}},
        {{"label": "Partial", "description": "...", "points_earned": 0.5}},
        {{"label": "None", "description": "...", "points_earned": 0.0}}
      ],
      "required_evidence": ["..."],
      "common_errors": [
        {{"description": "...", "guidance": "..."}}
      ],
      "alternative_methods": ["..."]
    }}
  ],
  "policy": {policy_json},
  "acceptable_answers": ["..."] or null,
  "notes": "..." or null,
  "reference_context": "..." or null
}}
"""


def suggest_rubric(
    question_text: str,
    subject: str,
    max_score: float,
    language: str,
    *,
    answer_key: str | None = None,
    course_level: str | None = None,
    expected_method: str | None = None,
    instructor_notes: str | None = None,
    grading_approach: GradingApproach = "balanced",
    policy: RubricPolicy | None = None,
    current_rubric: dict | None = None,
) -> RubricV2:
    resolved_policy = policy_for_approach(grading_approach, policy)
    prompt = RUBRIC_SUGGESTION_PROMPT.format(
        subject=subject,
        course_level=course_level or "Not specified",
        language=language,
        max_score=max_score,
        grading_approach=resolved_policy.grading_approach,
        question_text=question_text,
        answer_key=answer_key or "Not provided",
        expected_method=expected_method or "Not specified",
        instructor_notes=instructor_notes or "None",
        current_rubric_json=(
            json.dumps(current_rubric, ensure_ascii=False)
            if current_rubric
            else "Not provided; create a new rubric."
        ),
        policy_json=json.dumps(resolved_policy.model_dump(), ensure_ascii=False),
    )

    raw_response = generate(contents=prompt, json_mode=True)

    try:
        parsed = json.loads(raw_response)
        # The instructor-selected policy is authoritative. The model designs the
        # criteria but cannot silently change strictness or penalty rules.
        parsed["policy"] = resolved_policy.model_dump()
        parsed["schema_version"] = 2
        result = RubricV2(**parsed)
    except (json.JSONDecodeError, ValidationError, TypeError) as error:
        raise ValueError(
            "Rubric suggestion failed validation: "
            f"{error}\nRaw response: {raw_response}"
        ) from error

    return result
