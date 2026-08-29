from typing import Optional

from pydantic import BaseModel, Field


class CourseCreateRequest(BaseModel):
    course_code: str = Field(min_length=1, max_length=50)
    title: str = Field(min_length=1, max_length=255)
    term: Optional[str] = Field(default=None, max_length=50)
    instructor_name: Optional[str] = Field(default=None, max_length=255)
