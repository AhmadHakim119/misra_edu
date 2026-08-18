from pydantic import BaseModel, Field
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


class ExistingQuestionRubricSuggestionRequest(BaseModel):
    answer_key: Optional[str] = None
    course_level: Optional[str] = None
    expected_method: Optional[str] = None
    instructor_notes: Optional[str] = None
    grading_approach: GradingApproach = "balanced"
    policy: Optional[RubricPolicy] = None
    change_summary: Optional[str] = None

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


class RubricVersionUpdateRequest(BaseModel):
    rubric: dict
    change_summary: Optional[str] = None


class RubricVersionApprovalRequest(BaseModel):
    approved_by: Optional[str] = None
