from typing import Literal
from pydantic import BaseModel


class GradeRequest(BaseModel):
    mode: Literal["text_only", "image_text", "auto"] = "text_only"
