from typing import Literal, Optional

from pydantic import BaseModel, Field


class SourceMappingRequest(BaseModel):
    question_id: str


class UnmatchedSegmentResolutionRequest(BaseModel):
    action: Literal["assign", "ignore"]
    question_id: Optional[str] = None
    page_index: Optional[int] = Field(default=None, ge=0)


class BulkSegmentResolutionRequest(BaseModel):
    action: Literal["assign", "ignore"]
    question_id: Optional[str] = None
    source_ids: list[str] = Field(default_factory=list, max_length=250)
    unmatched_indices: list[int] = Field(default_factory=list, max_length=250)
