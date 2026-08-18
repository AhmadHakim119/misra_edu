from typing import Literal

from pydantic import BaseModel, Field


class PageRecoveryPreviewRequest(BaseModel):
    question_numbers: list[str] = Field(min_length=1, max_length=30)


class RecoverySegmentInput(BaseModel):
    question_number: str = Field(min_length=1, max_length=20)
    text: str = Field(min_length=1)
    language: Literal["ar", "en", "mixed"] = "mixed"
    legibility: Literal["clear", "partial", "illegible"] = "clear"
    has_math: bool = False
    math_notation: str | None = None


class PageRecoveryConfirmRequest(BaseModel):
    question_numbers: list[str] = Field(min_length=1, max_length=30)
    segments: list[RecoverySegmentInput] = Field(min_length=1, max_length=100)
    preview_signature: str = Field(min_length=64, max_length=64)
