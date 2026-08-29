from pydantic import BaseModel, Field, model_validator


class NormalizedBoundingBox(BaseModel):
    """A page-relative rectangle where every value is between zero and one."""

    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)
    width: float = Field(gt=0, le=1)
    height: float = Field(gt=0, le=1)

    @model_validator(mode="after")
    def stays_inside_page(self):
        if self.x + self.width > 1.001 or self.y + self.height > 1.001:
            raise ValueError("bounding box must stay inside the page")
        return self
