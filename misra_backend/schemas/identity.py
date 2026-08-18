from pydantic import BaseModel
from typing import Optional
from typing import Literal

class IdentityResolutionRequest(BaseModel):
    action: Literal["match_existing", "create_new", "confirm_unidentified"]
    student_id: Optional[str] = None       # required if action == "match_existing"
    full_name: Optional[str] = None        # required if action == "create_new"
    student_number: Optional[str] = None   # optional even for create_new