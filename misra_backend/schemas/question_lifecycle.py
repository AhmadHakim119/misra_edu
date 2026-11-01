from typing import Literal
from pydantic import BaseModel, ConfigDict, Field


class QuestionLifecycleRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    action: Literal['remove', 'restore']
    review_token: str = Field(pattern=r'^[a-f0-9]{64}$')
    confirm_reviewed: bool = Field(strict=True)
