from pydantic import BaseModel, Field, model_validator
from typing import Optional
from typing import Literal

from schemas.rubric_v2 import (
    CommonError,
    GradingApproach,
    PerformanceLevel,
    RubricPolicy,
)

class CriterionInput(BaseModel):
    id: Optional[str] = None
    title: Optional[str] = None
    description: str = Field(min_length=1)
    points: float = Field(gt=0)
    scoring_type: Optional[Literal["binary", "scaled"]] = None
    partial_credit_allowed: bool = True
    performance_levels: list[PerformanceLevel] = Field(default_factory=list)
    required_evidence: list[str] = Field(default_factory=list)
    common_errors: list[CommonError] = Field(default_factory=list)
    alternative_methods: list[str] = Field(default_factory=list)

class QuestionCreateRequest(BaseModel):
    # Legacy clients explicitly create an approved manual rubric. New authoring
    # clients can save a draft without making it grading authority.
    approve_initial_rubric: bool = True
    scoring_contract: Literal["exact"] | None = None
    question_number: str
    question_text: str
    max_score: float = Field(gt=0)
    language: Literal["ar", "en", "mixed"] = "en"
    criteria: list[CriterionInput] = Field(min_length=1)
    acceptable_answers: Optional[list[str]] = None
    notes: Optional[str] = None
    reference_context: Optional[str] = None
    grading_approach: GradingApproach = "balanced"
    policy: Optional[RubricPolicy] = None

class RubricSuggestionRequest(BaseModel):
    question_number: str
    question_text: str
    max_score: float = Field(gt=0)
    language: Literal["ar", "en", "mixed"] = "en"
    answer_key: Optional[str] = None
    course_level: Optional[str] = None
    expected_method: Optional[str] = None
    instructor_notes: Optional[str] = None
    grading_approach: GradingApproach = "balanced"
    policy: Optional[RubricPolicy] = None


class CriterionCue(BaseModel):
    id: str = Field(max_length=100)
    title: str = Field(max_length=160)
    description: str = Field(max_length=800)


class RubricPreviewQuestion(BaseModel):
    text: str = Field(min_length=1, max_length=20000)
    max_score: float = Field(gt=0, le=9999.99, allow_inf_nan=False)
    language: Literal["ar", "en", "mixed"]


class RubricPreviewAnswerKey(BaseModel):
    revision: str | None = Field(pattern=r'^[a-f0-9]{64}$')


class ExistingQuestionRubricSuggestionRequest(BaseModel):
    exact_scoring: bool = Field(default=False, strict=True)
    preview_only: bool = Field(default=False, strict=True)
    fill_pending_only: bool = Field(default=False, strict=True)
    answer_key: Optional[str] = Field(default=None, max_length=20000)
    course_level: Optional[str] = Field(default=None, max_length=200)
    expected_method: Optional[str] = Field(default=None, max_length=2000)
    instructor_notes: Optional[str] = Field(default=None, max_length=4000)
    criterion_cues: list[CriterionCue] = Field(default_factory=list, max_length=24)
    preview_question: RubricPreviewQuestion | None = None
    preview_answer_key: RubricPreviewAnswerKey | None = None
    grading_approach: GradingApproach = "balanced"
    policy: Optional[RubricPolicy] = None
    change_summary: Optional[str] = None

    @model_validator(mode="after")
    def exclusive_drafting_actions(self):
        if self.preview_only and self.fill_pending_only:
            raise ValueError("Choose either a preview or drafting a missing rubric.")
        return self

class RubricResolutionRequest(BaseModel):
    action: Literal["accept", "reject"]
    question_number: Optional[str] = None
    question_text: Optional[str] = None
    max_score: Optional[float] = Field(default=None, gt=0)
    language: Optional[Literal["ar", "en", "mixed"]] = None
    criteria: Optional[list[CriterionInput]] = None
    acceptable_answers: Optional[list[str]] = None
    notes: Optional[str] = None
    reference_context: Optional[str] = None
    grading_approach: GradingApproach = "balanced"
    policy: Optional[RubricPolicy] = None


class RubricVersionCreateRequest(BaseModel):
    rubric: dict
    source: Literal["manual", "ai", "imported"] = "manual"
    change_summary: Optional[str] = None
    apply_instructor_preferences: bool = Field(default=False, strict=True)


class RubricVersionUpdateRequest(BaseModel):
    rubric: dict
    change_summary: Optional[str] = None


class RubricVersionApprovalRequest(BaseModel):
    approved_by: Optional[str] = None
