from fastapi import Depends, File, HTTPException, UploadFile, APIRouter
from models import User
from services.auth_dependencies import require_instructor
from services.ocr_service import extract_page
from services.upload_security_service import (
    UploadValidationError,
    remove_stored_uploads,
    store_validated_upload,
)
router = APIRouter(prefix="/api", tags=["ocr"])

@router.post("/ocr")
async def ocr_endpoint(
    file: UploadFile = File(...),
    _user: User = Depends(require_instructor),
):
    try:
        stored = await store_validated_upload(file, "storage/uploads")
    except UploadValidationError as error:
        raise HTTPException(status_code=error.status_code, detail=error.detail) from error

    try:
        if stored.extension == ".pdf":
            raise HTTPException(
                status_code=415,
                detail="The single-page OCR diagnostic accepts PNG, JPEG, or WebP images only",
            )
        return extract_page(stored.path.read_bytes())
    finally:
        remove_stored_uploads([stored])
