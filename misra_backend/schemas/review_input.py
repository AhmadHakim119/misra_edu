from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator


class HumanCriterionScore(BaseModel):
    criterion_id: str = Field(min_length=1)
    points_earned: float = Field(ge=0)
    max_points: float = Field(gt=0)


class ReviewReasonCode(str, Enum):
    VALID_ALTERNATIVE = "valid_alternative"
    MINOR_NOTATION = "minor_notation"
    METHOD_CREDIT = "method_credit"
    CARRIED_FORWARD_ERROR = "carried_forward_error"
    LANGUAGE_TOLERANCE = "language_tolerance"
    RUBRIC_ISSUE = "rubric_issue"
    OCR_OR_MAPPING_ERROR = "ocr_or_mapping_error"
    OTHER = "other"


# Only these decisions are evidence about how the instructor awards marks.
# Extraction and rubric-quality problems must never train or propose a marking
# preference, even when they explain a score change.
PREFERENCE_REASON_CODES = frozenset({
    ReviewReasonCode.VALID_ALTERNATIVE,
    ReviewReasonCode.MINOR_NOTATION,
    ReviewReasonCode.METHOD_CREDIT,
    ReviewReasonCode.CARRIED_FORWARD_ERROR,
    ReviewReasonCode.LANGUAGE_TOLERANCE,
})
PREFERENCE_REASON_VALUES = frozenset(code.value for code in PREFERENCE_REASON_CODES)


class ReviewResolutionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal["approve", "override"]
    grading_run_id: Optional[str] = None
    apply_as_current: bool = True
    was_review_warranted: bool
    human_score: Optional[float] = Field(default=None, ge=0)
    human_criteria_scores: Optional[list[HumanCriterionScore]] = None
    reviewer_notes: Optional[str] = None
    review_reason_codes: list[ReviewReasonCode] = Field(default_factory=list, max_length=8)
    review_reason_note: Optional[str] = Field(default=None, max_length=1000)
    @model_validator(mode="after")
    def override_requires_human_score(self):
        if self.action == "override" and self.human_score is None:
            raise ValueError("human_score is required when action is 'override'")
        if self.action == "override" and not self.review_reason_codes:
            raise ValueError("at least one review reason is required when action is 'override'")
        if len(self.review_reason_codes) != len(set(self.review_reason_codes)):
            raise ValueError("review reason codes must be unique")
        if self.review_reason_note is not None:
            self.review_reason_note = self.review_reason_note.strip() or None
        if self.human_criteria_scores:
            criterion_ids = [item.criterion_id for item in self.human_criteria_scores]
            if len(criterion_ids) != len(set(criterion_ids)):
                raise ValueError("human criterion IDs must be unique")
            if any(item.points_earned > item.max_points for item in self.human_criteria_scores):
                raise ValueError("criterion points cannot exceed criterion maximum points")
            if (
                self.action == "override"
                and self.human_score is not None
                and abs(
                    sum(item.points_earned for item in self.human_criteria_scores)
                    - self.human_score
                ) > 0.01
            ):
                raise ValueError("criterion points must add up to human_score")
        return self
