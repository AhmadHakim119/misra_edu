from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator


class HumanCriterionScore(BaseModel):
    criterion_id: str = Field(min_length=1)
    points_earned: float = Field(ge=0)
    max_points: float = Field(gt=0)


class ReviewResolutionRequest(BaseModel):
    action: Literal["approve", "override"]
    grading_run_id: Optional[str] = None
    apply_as_current: bool = True
    was_review_warranted: bool
    human_score: Optional[float] = Field(default=None, ge=0)
    human_criteria_scores: Optional[list[HumanCriterionScore]] = None
    reviewer_notes: Optional[str] = None
    label_source: str = "instructor_review"

    @model_validator(mode="after")
    def override_requires_human_score(self):
        if self.action == "override" and self.human_score is None:
            raise ValueError("human_score is required when action is 'override'")
        if self.human_criteria_scores:
            criterion_ids = [item.criterion_id for item in self.human_criteria_scores]
            if len(criterion_ids) != len(set(criterion_ids)):
                raise ValueError("human criterion IDs must be unique")
            if any(item.points_earned > item.max_points for item in self.human_criteria_scores):
                raise ValueError("criterion points cannot exceed criterion maximum points")
            if (
                self.action == "override"
                and self.human_score is not None
                and abs(
                    sum(item.points_earned for item in self.human_criteria_scores)
                    - self.human_score
                ) > 0.01
            ):
                raise ValueError("criterion points must add up to human_score")
        return self
