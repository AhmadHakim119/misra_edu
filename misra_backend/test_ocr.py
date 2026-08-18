from services.ocr_service import extract_page

with open("test_linalg.png", "rb") as f:
    image_bytes = f.read()

result = extract_page(image_bytes)
print(result.model_dump_json(indent=2))