from fastapi import File, UploadFile, APIRouter
from services.ocr_service import extract_page
router = APIRouter(prefix="/api", tags=["ocr"])

@router.post("/ocr")
async def ocr_endpoint(file: UploadFile = File(...)):
    contents = await file.read()
    extracted = extract_page(contents)
    return extracted