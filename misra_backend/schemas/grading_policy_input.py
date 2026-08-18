from typing import Literal, Optional

from pydantic import BaseModel, Field


class QuestionGradingPolicyRequest(BaseModel):
    mode: Literal[
        "adaptive",
        "image_text_required",
        "text_only",
        "pilot",
        "image_text",
        "dual_mode_review",
        "text_only_with_random_audit",
    ] = "adaptive"
    audit_rate: float = Field(default=0.10, ge=0, le=1)
    min_validated_samples: int = Field(default=10, ge=1)
    material_absolute_points: float = Field(default=0.5, gt=0)
    material_relative_ratio: float = Field(default=0.20, gt=0, le=1)
    enabled: bool = True
    notes: Optional[str] = None
