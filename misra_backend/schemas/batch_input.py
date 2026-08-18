from pydantic import BaseModel
from typing import Optional

class BatchUploadResponse(BaseModel):
    batch_id: str
    total_submissions: int
    status: str