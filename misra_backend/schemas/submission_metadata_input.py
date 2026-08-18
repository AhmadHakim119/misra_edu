from typing import Optional

from pydantic import BaseModel, Field


class SubmissionMetadataUpdate(BaseModel):
    student_name: Optional[str] = Field(default=None, max_length=255)
    student_number: Optional[str] = Field(default=None, max_length=100)
    instructor_name: Optional[str] = Field(default=None, max_length=255)
