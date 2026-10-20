from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, StrictBool
from schemas.ocr_evidence import NormalizedBoundingBox


class AreaPreviewRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    bounding_box: NormalizedBoundingBox
    expected_text: str = Field(max_length=50000)


class AreaConfirmRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    text: str = Field(min_length=1, max_length=50000)
    expected_preview_text: str = Field(max_length=50000)
    expected_revision_id: str | None = Field(default=None, max_length=36)
    complete_answer: StrictBool


class AreaRegradeRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    expected_run_id: str | None = Field(default=None, max_length=36)
    revision_ids: list[str] = Field(min_length=1, max_length=100)
    request_id: UUID
