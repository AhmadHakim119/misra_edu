from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, model_validator


GradingApproach = Literal["lenient", "balanced", "strict", "custom"]
ScoringType = Literal["binary", "scaled"]


def new_criterion_id() -> str:
    """Generate an opaque identifier that survives description edits."""
    return f"criterion_{uuid.uuid4().hex[:12]}"


class PerformanceLevel(BaseModel):
    label: str = Field(min_length=1, max_length=100)
    description: str = Field(min_length=1)
    points_earned: float = Field(ge=0, allow_inf_nan=False)


class CommonError(BaseModel):
    description: str = Field(min_length=1)
    guidance: str = Field(
        min_length=1,
        description="How this error should affect this criterion's score.",
    )


class RubricCriterionV2(BaseModel):
    id: str = Field(default_factory=new_criterion_id, min_length=1, max_length=100)
    title: str = Field(min_length=1, max_length=160)
    description: str = Field(min_length=1)
    points: float = Field(gt=0, allow_inf_nan=False)
    scoring_type: ScoringType = "scaled"
    partial_credit_allowed: bool = True
    performance_levels: list[PerformanceLevel] = Field(default_factory=list)
    required_evidence: list[str] = Field(default_factory=list)
    common_errors: list[CommonError] = Field(default_factory=list)
    alternative_methods: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_scoring(self):
        if self.scoring_type == "binary" and self.partial_credit_allowed:
            raise ValueError(
                "binary criteria must set partial_credit_allowed to false"
            )

        seen_labels: set[str] = set()
        for level in self.performance_levels:
            key = level.label.strip().casefold()
            if key in seen_labels:
                raise ValueError(f"duplicate performance level '{level.label}'")
            seen_labels.add(key)
            if level.points_earned > self.points:
                raise ValueError(
                    f"performance level '{level.label}' awards more than "
                    f"the criterion maximum of {self.points}"
                )

        if self.scoring_type == "binary" and self.performance_levels:
            allowed = {0.0, float(self.points)}
            actual = {float(level.points_earned) for level in self.performance_levels}
            if not actual.issubset(allowed):
                raise ValueError(
                    "binary criterion performance levels may only award zero "
                    "or full points"
                )
        return self


class RubricPolicy(BaseModel):
    assessment_scope: Literal["paper", "external"] = "paper"
    language_quality_policy: Literal["criterion_specific", "ignore_unless_assessed", "assess"] = "criterion_specific"
    error_carried_forward: Literal["criterion_specific", "single_penalty", "penalize_each"] = "criterion_specific"
    handwritten_syntax_policy: Literal["criterion_specific", "accept_unambiguous", "require_correct"] = "criterion_specific"
    grading_approach: GradingApproach = "balanced"
    method_credit: Literal["none", "partial", "full_if_valid"] = "partial"
    arithmetic_error_policy: Literal[
        "single_penalty", "penalize_each", "criterion_specific"
    ] = "single_penalty"
    rounding_tolerance_percent: float | None = Field(default=None, ge=0, le=100)
    # No cap/cross-part exception is inferred from leniency or override history.
    numeric_penalty_cap_points: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    cross_part_follow_through: Literal["criterion_specific", "allow_prior_error"] = "criterion_specific"
    units_policy: Literal[
        "required", "required_when_applicable", "do_not_penalize"
    ] = "required_when_applicable"
    notation_policy: Literal[
        "standard_required", "equivalent_allowed", "do_not_penalize"
    ] = "equivalent_allowed"
    alternative_methods_allowed: bool = True
    evidence_requirement: Literal[
        "final_answer_only", "key_steps", "complete_reasoning", "custom"
    ] = "key_steps"
    illegible_response_policy: Literal[
        "manual_review", "grade_visible_only", "zero"
    ] = "manual_review"
    custom_instructions: str | None = None

    @model_validator(mode="after")
    def validate_custom_policy(self):
        if self.grading_approach == "custom" and not self.custom_instructions:
            raise ValueError(
                "custom grading approach requires custom_instructions"
            )
        return self


class RubricV2(BaseModel):
    schema_version: Literal[2] = 2
    scoring_contract: Literal["exact", "needs_exact_scoring"] | None = None
    max_score: float = Field(gt=0, allow_inf_nan=False)
    criteria: list[RubricCriterionV2] = Field(min_length=1)
    policy: RubricPolicy = Field(default_factory=RubricPolicy)
    acceptable_answers: list[str] | None = None
    notes: str | None = None
    reference_context: str | None = None

    @model_validator(mode="after")
    def validate_rubric(self):
        total = sum(criterion.points for criterion in self.criteria)
        if abs(total - self.max_score) > 0.01:
            raise ValueError(
                f"criteria points sum to {total}, but max_score is {self.max_score}"
            )

        criterion_ids = [criterion.id for criterion in self.criteria]
        if len(criterion_ids) != len(set(criterion_ids)):
            raise ValueError("criterion ids must be unique within a rubric")
        if self.scoring_contract == "exact":
            maximum = mark_hundredths(self.max_score)
            if self.max_score > 9999.99:
                raise ValueError("Question marks cannot exceed 9999.99")
            if sum(mark_hundredths(c.points) for c in self.criteria) != maximum:
                raise ValueError("Criterion marks must add up exactly to the question total")
            for criterion in self.criteria:
                validate_exact_criterion(criterion)
        return self


def mark_hundredths(value: float) -> int:
    hundredths = Decimal(str(value)) * 100
    if not hundredths.is_finite() or hundredths != hundredths.to_integral_value():
        raise ValueError("Use at most two decimal places for marks")
    return int(hundredths)


def validate_exact_criterion(criterion: RubricCriterionV2) -> None:
    if not criterion.title.strip() or not criterion.description.strip():
        raise ValueError("Each criterion needs a title and an observable credit description")
    if criterion.scoring_type == "binary":
        return
    if not criterion.partial_credit_allowed:
        raise ValueError("Choose Full or zero for a criterion without intermediate credit")
    marks = [mark_hundredths(level.points_earned) for level in criterion.performance_levels]
    if (len(marks) < 3 or len(set(marks)) != len(marks)
            or 0 not in marks or mark_hundredths(criterion.points) not in marks):
        raise ValueError("Defined credit levels must give distinct marks for zero, full and at least one intermediate level")
    if any(not level.label.strip() or not level.description.strip() for level in criterion.performance_levels):
        raise ValueError("Describe the observable work for every credit level")


def exact_credit_marks(criterion: dict) -> set[float]:
    if criterion["scoring_type"] == "binary":
        return {0.0, float(criterion["points"])}
    return {float(level["points_earned"]) for level in criterion["performance_levels"]}
