from services.ocr_service import _split_pdf

with open("Quiz5_stu_copy.pdf", "rb") as f:
    pdf_bytes = f.read()

pages = _split_pdf(pdf_bytes)
print(f"Total pages extracted: {len(pages)}")

# Save the first 4 pages as images so you can visually confirm
# they're actually pages 1, 2, 3, 4 in that order.
for i in range(4):
    with open(f"check_order_{i+1}.png", "wb") as out:
        out.write(pages[i])

print("Saved check_order_1.png through check_order_4.png")