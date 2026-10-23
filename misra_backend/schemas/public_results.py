"""Explicit instructor-facing records; internal storage paths never cross the API."""
from datetime import datetime
from typing import Any
from pydantic import BaseModel, ConfigDict, computed_field, field_serializer


def public_snapshot(value):
    hidden = {'path','original_file_path','storage_path','file_path','hashed_password','api_key','preview_signature_secret'}
    if isinstance(value,dict):
        return {key:public_snapshot(item) for key,item in value.items() if key not in hidden}
    if isinstance(value,list):
        return [public_snapshot(item) for item in value]
    return value


class SubmissionRecord(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    exam_id: str
    batch_id: str | None = None
    student_id: str | None = None
    extracted_student_name: str | None = None
    extracted_student_number: str | None = None
    identity_status: str
    page_count: int
    status: str
    error_message: str | None = None
    uploaded_at: datetime | None = None


class AnswerRecord(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    submission_id: str
    question_id: str
    raw_ocr_text: str | None = None
    ocr_legibility: str | None = None
    score: float | None = None
    max_score: float | None = None
    grade_letter: str | None = None
    feedback: str | None = None
    reasoning: str | None = None
    criteria_scores: Any = None
    llm_confidence: float | None = None
    final_confidence: float | None = None
    grading_raw_response: dict | None = None
    needs_review: bool
    review_status: str
    teacher_override_score: float | None = None
    teacher_notes: str | None = None
    reviewed_at: datetime | None = None
    @computed_field
    @property
    def review_token(self) -> str:
        from services.review_state_service import review_token
        return review_token(self)
    @computed_field
    @property
    def review_explanation(self) -> dict:
        from services.review_explanation_service import explain_review
        return explain_review(self.grading_raw_response, self.criteria_scores,
            needs_review=self.needs_review, review_status=self.review_status)
    @field_serializer('grading_raw_response')
    def safe_snapshot(self,value): return public_snapshot(value)


class ReviewRecord(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    answer_id: str
    grading_run_id: str | None = None
    supersedes_label_id: str | None = None
    human_score: float
    human_criteria_scores: Any = None
    reviewer_notes: str | None = None
    ai_score_snapshot: float
    was_review_warranted: bool
    rubric_version_id: str | None = None
    review_reason_codes: list[str] | None = None
    review_reason_note: str | None = None
    created_at: datetime | None = None


class ResultRecord(BaseModel):
    submission: SubmissionRecord
    answers: list[AnswerRecord]
    latest_review_labels: list[ReviewRecord]
    grading_scope: dict
    external_answers: list[AnswerRecord]


class ReviewResolutionRecord(BaseModel):
    answer: AnswerRecord
    review_label: ReviewRecord


class GradingRunRecord(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    answer_id: str
    rubric_version_id: str | None = None
    processing_job_id: str | None = None
    model_name: str
    mode: str
    prompt_version: str | None = None
    score: float
    max_score: float
    grade_letter: str | None = None
    feedback: str | None = None
    reasoning: str | None = None
    criteria_scores: Any = None
    llm_confidence: float | None = None
    final_confidence: float | None = None
    needs_review: bool
    response_json: dict | None = None
    rubric_snapshot: dict | None = None
    ocr_text_snapshot: str | None = None
    source_page_indices: list[int] | None = None
    created_at: datetime | None = None
    latency_ms: int | None = None
    @field_serializer('response_json','rubric_snapshot')
    def safe_snapshot(self,value): return public_snapshot(value)
