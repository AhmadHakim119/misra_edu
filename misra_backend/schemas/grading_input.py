from typing import Literal
from pydantic import BaseModel, Field


class GradeRequest(BaseModel):
    mode: Literal["text_only", "image_text", "auto"] = "text_only"


class ContinueGradeRequest(BaseModel):
    from_job_id: str = Field(min_length=1, max_length=36)
