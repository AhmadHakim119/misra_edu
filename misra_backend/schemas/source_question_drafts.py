"""Bounded instructor requests and untrusted free-model question proposals."""
from typing import Literal
from decimal import Decimal
from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator
from schemas.course_materials import MaterialBinding


class SourceQuestionDraftRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    bindings: list[MaterialBinding] = Field(min_length=1, max_length=64)
    topic: str = Field(min_length=1, max_length=500)
    count: StrictInt = Field(default=3, ge=1, le=5)
    points_per_question: float = Field(default=2, gt=0, le=100, allow_inf_nan=False)
    language: Literal["en", "ar", "mixed"] = "en"
    difficulty: Literal["introductory", "intermediate", "advanced"] = "intermediate"

    @model_validator(mode="after")
    def coherent_request(self):
        self.topic = self.topic.strip()
        if not self.topic or any(binding.criterion_id is not None for binding in self.bindings):
            raise ValueError("Choose a topic and question-level source pages, not existing criterion links.")
        if len({binding.version_id for binding in self.bindings}) != len(self.bindings):
            raise ValueError("Combine page selections for the same reference version.")
        marks = Decimal(str(self.points_per_question))
        if marks != marks.quantize(Decimal("0.01")):
            raise ValueError("Marks per question must use at most two decimal places.")
        return self


class DraftCitation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_ref: str = Field(min_length=1, max_length=40)
    quote: str = Field(min_length=1, max_length=300)


class DraftCriterion(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=160)
    description: str = Field(min_length=1, max_length=2000)
    points: float = Field(gt=0, le=100, allow_inf_nan=False)
    partial_credit_allowed: bool = True
    citations: list[DraftCitation] = Field(min_length=1, max_length=4)


class SourceQuestionProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question_text: str = Field(min_length=1, max_length=6000)
    answer_mode: Literal["reference", "no_fixed_answer"] = "reference"
    answer_key: str = Field(default="", max_length=6000)
    criteria: list[DraftCriterion] = Field(min_length=1, max_length=6)
    citations: list[DraftCitation] = Field(min_length=1, max_length=4)

    @model_validator(mode="after")
    def meaningful_text(self):
        self.question_text, self.answer_key = self.question_text.strip(), self.answer_key.strip()
        if not self.question_text or any(not c.title.strip() or not c.description.strip() for c in self.criteria):
            raise ValueError("Question and criterion text cannot be blank.")
        if self.answer_mode == "reference" and not self.answer_key:
            raise ValueError("A reference-mode proposal needs a suggested solution.")
        if self.answer_mode == "no_fixed_answer" and self.answer_key:
            raise ValueError("No-fixed-answer proposals cannot contain a fixed solution.")
        return self


class SourceQuestionProposals(BaseModel):
    model_config = ConfigDict(extra="forbid")
    questions: list[SourceQuestionProposal] = Field(min_length=1, max_length=5)
    warnings: list[str] = Field(default_factory=list, max_length=10)
