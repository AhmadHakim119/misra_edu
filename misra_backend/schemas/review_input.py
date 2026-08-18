from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator


class ReviewResolutionRequest(BaseModel):
    action: Literal["approve", "override"]
    grading_run_id: Optional[str] = None
    apply_as_current: bool = True
    was_review_warranted: bool
    human_score: Optional[float] = Field(default=None, ge=0)
    human_criteria_scores: Optional[list[dict]] = None
    reviewer_notes: Optional[str] = None
    label_source: str = "instructor_review"

    @model_validator(mode="after")
    def override_requires_human_score(self):
        if self.action == "override" and self.human_score is None:
            raise ValueError("human_score is required when action is 'override'")
        return self
