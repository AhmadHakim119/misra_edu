from __future__ import annotations

import uuid
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
    points_earned: float = Field(ge=0)


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
    points: float = Field(gt=0)
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
    grading_approach: GradingApproach = "balanced"
    method_credit: Literal["none", "partial", "full_if_valid"] = "partial"
    arithmetic_error_policy: Literal[
        "single_penalty", "penalize_each", "criterion_specific"
    ] = "single_penalty"
    rounding_tolerance_percent: float | None = Field(default=None, ge=0, le=100)
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
    max_score: float = Field(gt=0)
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
        return self
