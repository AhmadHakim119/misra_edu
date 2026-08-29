from typing import Literal

from pydantic import BaseModel, Field


class ExamCreateRequest(BaseModel):
    course_id: str = Field(min_length=1)
    title: str = Field(min_length=1, max_length=255)
    language: Literal["ar", "en", "mixed"] = "en"


class ExamDuplicateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    include_rubrics: bool = True
    include_grading_policies: bool = True
