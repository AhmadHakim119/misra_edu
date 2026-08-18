import cv2
import numpy as np
from PIL import Image
import io
import json
from typing import Optional, Literal
from pydantic import BaseModel, ValidationError
from pdf2image import convert_from_bytes
from sqlalchemy.orm import Session
import logging
from services.gemini_client import generate
from models import Submission, Question, Answer, Batch, AnswerSource
import os
import uuid
import re

# ---------- Response schema (validated against Gemini's output) ----------

class OCRSegment(BaseModel):
    question_number: Optional[str] = None
    text: str
    language: Literal["ar", "en", "mixed"]
    legibility: Literal["clear", "partial", "illegible"]
    has_math: bool
    math_notation: Optional[str] = None


class OCRPageResult(BaseModel):
    page_language: Literal["ar", "en", "mixed"]
    segments: list[OCRSegment]
    student_name: Optional[str] = None
    student_id: Optional[str] = None
    identity_legibility: Literal["clear", "partial", "illegible", "not_found"]


# ---------- Prompt ----------

OCR_PROMPT = """
You are an OCR system extracting content from a single page of a student's handwritten exam.

Extract all content exactly as written, including:
- Arabic text (preserve original wording, do not translate or correct)
- English text
- Mathematical equations and expressions (represent using LaTeX notation)
- Question numbers as written on the page

Also look for a student name and/or student ID number, usually near the top of the page.
Only use text explicitly associated with a student name or student ID field.
Never treat an instructor name, course coordinator, printed signature, department
label, or repeated page footer as the student's identity.

Rules:
- Do NOT summarize, correct, paraphrase, or grade anything.
- If a segment is illegible, still include it with legibility set to "illegible" and your best-effort text.
- If no student name or ID is visible anywhere on the page, set student_name and student_id to null and identity_legibility to "not_found".
- If a name/ID area exists but cannot be read clearly, set identity_legibility to "illegible".

IMPORTANT — WHAT TO EXTRACT:
- Do NOT create a segment for the printed question prompt text itself (the question as originally written on the exam, e.g. "Q3. Early one October, you go to a pumpkin patch...").
- ONLY extract the student's own handwritten work: given values, calculations, equations, and final answers.
- If a question has multiple handwritten lines before any sub-part letter appears (e.g. given values like "m = 3.2 kg, h = 1.2 m"), include that as its own segment under the base question number (e.g. "3"), separate from sub-parts.

FORMATTING RULE FOR question_number:
- Use ONLY the number and, if present, a lowercase sub-part letter. Example: "3", "3a", "3b".
- Do NOT include the letter "Q", the word "Question", or any punctuation.
- If a segment does not belong to any specific numbered question (e.g. a page header, institution name, logo, page number, or printed question prompt text), set question_number to null.
- Give each distinct handwritten sub-part (a), (b), (c) its own separate segment with its own sub-part letter.
- Before returning JSON, verify that every visible printed sub-part containing
  handwritten work has a corresponding segment. Do not skip short answers.

FORMATTING RULE FOR question_number:
- Use ONLY the number and, if present, a lowercase sub-part letter. Example: "3", "3a", "3b".
- Do NOT include the letter "Q", the word "Question", or any punctuation.
- If a segment does not belong to any specific numbered question (e.g. a page header, institution name, logo, page number, or printed question prompt text), set question_number to null.
- Give each distinct handwritten sub-part (a), (b), (c) its own separate segment with its own sub-part letter.

Return ONLY valid JSON matching this exact structure, no markdown formatting, no extra commentary:

QUESTION-IDENTIFICATION RULE:
Use printed question headers and printed sub-part labels ONLY as context to assign
the student's handwritten work to the correct question_number. Do not extract the
printed question itself as a segment.

Never return only a base number when the printed page shows a sub-part:
- "Question 1" with "(a)" means "1a"
- "(b)" continuing Question 1 means "1b"
- "Question 2" with "(a)" means "2a"
- "(b)" continuing Question 2 means "2b"

Never return only "b" or "c". Return the fully qualified label, such as "1b",
"2b", or "2c".

When a page begins with a continuation label such as "(d)" and the previous
page ended at "2c", the continuation is "2d". Do not borrow a later question
number merely because that later label also exists in the assessment.

{
  "page_language": "ar | en | mixed",
  "segments": [
    {
      "question_number": "string like '3' or '3a', or null if not part of a question's handwritten answer",
      "text": "the extracted text for this segment",
      "language": "ar | en | mixed",
      "legibility": "clear | partial | illegible",
      "has_math": true or false,
      "math_notation": "LaTeX string if has_math is true, otherwise null"
    }
  ],
  "student_name": "string or null",
  "student_id": "string or null",
  "identity_legibility": "clear | partial | illegible | not_found"
}
"""


# ---------- Image preprocessing ----------

def _preprocess_image(image_bytes: bytes) -> bytes:
    """Applies grayscale + adaptive thresholding to improve OCR readability."""
    np_array = np.frombuffer(image_bytes, dtype=np.uint8)
    img = cv2.imdecode(np_array, cv2.IMREAD_COLOR)

    if img is None:
        # If decoding fails, return original bytes untouched rather than crashing.
        return image_bytes

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    processed = cv2.adaptiveThreshold(
        gray,
        255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY,
        blockSize=25,
        C=15
    )

    success, encoded = cv2.imencode(".png", processed)
    if not success:
        return image_bytes

    return encoded.tobytes()


# ---------- PDF splitting ----------
logger = logging.getLogger(__name__)

def _chunk_pdf_by_student(pdf_bytes: bytes, pages_per_student: int) -> list[list[bytes]]:
    """
    Splits a multi-student PDF into groups of pages, one group per student,
    based on a fixed page count per student.

    If the total page count doesn't divide evenly, the final (partial) group
    is still created, with a warning logged — a slightly-wrong extra submission
    a teacher can manually fix is preferable to silently dropping pages.
    """
    if pages_per_student <= 0:
        raise ValueError("pages_per_student must be a positive integer")

    all_pages = _split_pdf(pdf_bytes)
    total_pages = len(all_pages)

    groups = [
        all_pages[i:i + pages_per_student]
        for i in range(0, total_pages, pages_per_student)
    ]

    remainder = total_pages % pages_per_student
    if remainder != 0:
        logger.warning(
            f"PDF has {total_pages} pages, not evenly divisible by "
            f"pages_per_student={pages_per_student}. Final group has only "
            f"{remainder} page(s) instead of {pages_per_student} — likely incomplete "
            f"or misconfigured. Review the last submission from this batch manually."
        )

    return groups

def _split_pdf(pdf_bytes: bytes) -> list[bytes]:
    """Splits a PDF into a list of page images (PNG bytes)."""
    pil_pages = convert_from_bytes(pdf_bytes)
    page_bytes_list = []
    for page in pil_pages:
        buffer = io.BytesIO()
        page.save(buffer, format="PNG")
        page_bytes_list.append(buffer.getvalue())
    return page_bytes_list


# ---------- Core OCR call (pure function, no DB access) ----------

def extract_page(
    image_bytes: bytes,
    known_question_numbers: list[str] | None = None,
    previous_question_number: str | None = None,
) -> OCRPageResult:
    """Runs OCR on a single page image and returns a validated structured result."""
    processed_bytes = _preprocess_image(image_bytes)
    image = Image.open(io.BytesIO(processed_bytes))

    prompt = OCR_PROMPT

    if known_question_numbers:
        prompt += (
        "\n\nAVAILABLE QUESTION LABELS FOR THIS EXAM: "
        + ", ".join(known_question_numbers)
        )

    if previous_question_number:
        prompt += (
        "\n\nThe previous page's last identified question was "
        f"'{previous_question_number}'. Use this only to resolve a "
        "continuation sub-part such as '(b)' or '(c)'."
        )

    raw_response = generate(contents=[prompt, image], json_mode=True)

    try:
        parsed = json.loads(raw_response)
        return OCRPageResult(**parsed)
    except (json.JSONDecodeError, ValidationError):
        retry_prompt = prompt + "\n\nIMPORTANT: Your previous response contained invalid JSON (likely unescaped backslashes). Ensure every backslash in every field is properly escaped as \\\\ so the output is strictly valid JSON."
        raw_response = generate(contents=[retry_prompt, image], json_mode=True)
        try:
            parsed = json.loads(raw_response)
            return OCRPageResult(**parsed)
        except (json.JSONDecodeError, ValidationError) as e:
            raise ValueError(f"OCR response failed validation after retry: {e}\nRaw response: {raw_response}")


# ---------- Orchestration: one submission at a time ----------

def _normalize_question_number(
    raw_question_number: Optional[str],
    previous_base_number: Optional[str],
) -> tuple[Optional[str], Optional[str]]:
    if not raw_question_number:
        return None, previous_base_number

    normalized = raw_question_number.strip().lower()
    normalized = normalized.replace("question", "").replace("q", "")
    normalized = normalized.replace(".", "").replace("(", "").replace(")", "")
    normalized = normalized.strip()

    # A continuation page may show only "(b)" or "(c)".
    # Attach it to the most recently seen parent question number.
    if re.fullmatch(r"[a-z]", normalized):
        if previous_base_number:
            return f"{previous_base_number}{normalized}", previous_base_number
        return normalized, previous_base_number

    match = re.fullmatch(r"(\d+)([a-z]?)", normalized)
    if match:
        base_number = match.group(1)
        return normalized, base_number

    return normalized, previous_base_number


def _resolve_subpart_continuation(
    question_number: Optional[str],
    previous_question_number: Optional[str],
    known_question_numbers: list[str],
) -> Optional[str]:
    """Correct a valid-but-wrong base number on sequential sub-parts.

    Vision models sometimes read a standalone printed ``(d)`` correctly but
    attach it to a later base question (for example ``5d`` after ``2c``).  A
    label existing in the exam is not enough evidence to trust that base.  If
    the suffix continues alphabetically from the last resolved sub-part and
    that continuation exists, prefer the sequential label.
    """
    if not question_number or not previous_question_number:
        return question_number

    current = re.fullmatch(r"(\d+)([a-z])", question_number)
    previous = re.fullmatch(r"(\d+)([a-z])", previous_question_number)
    if not current or not previous:
        return question_number

    current_base, current_suffix = current.groups()
    previous_base, previous_suffix = previous.groups()
    is_next_suffix = ord(current_suffix) == ord(previous_suffix) + 1
    candidate = f"{previous_base}{current_suffix}"
    if (
        current_base != previous_base
        and is_next_suffix
        and candidate in known_question_numbers
    ):
        logger.warning(
            "Corrected OCR continuation label %s to %s after %s",
            question_number,
            candidate,
            previous_question_number,
        )
        return candidate

    return question_number

def process_submission(submission_id: str, db: Session) -> None:
    submission = db.query(Submission).filter(Submission.id == submission_id).first()
    if not submission:
        raise ValueError(f"Submission {submission_id} not found")

    submission.status = "extracting"
    db.commit()

    try:
        with open(submission.original_file_path, "rb") as f:
            file_bytes = f.read()

        if submission.original_file_path.lower().endswith(".pdf"):
            page_images = _split_pdf(file_bytes)
        else:
            page_images = [file_bytes]

        submission.page_count = len(page_images)
        db.commit()

        questions = db.query(Question).filter(Question.exam_id == submission.exam_id).all()
        question_lookup = {q.question_number: q.id for q in questions}
        known_question_numbers = list(question_lookup.keys())
        previous_resolved_question_number = None

        identity_found = False
        unmatched_segments = []
        previous_base_question_number = None
        for page_index, page_bytes in enumerate(page_images):
            page_result = extract_page(
                page_bytes,
                known_question_numbers=known_question_numbers,
                previous_question_number=previous_resolved_question_number,
            )

            # Student identity belongs on the submission's first page. Limiting
            # identity promotion prevents repeated instructor footers on later
            # pages from overwriting the actual student name.
            if page_index == 0 and (page_result.student_name or page_result.student_id):
                submission.extracted_student_name = page_result.student_name
                submission.extracted_student_number = page_result.student_id
                identity_found = True

            if page_result.identity_legibility == "illegible" and not identity_found:
                submission.identity_status = "unmatched_illegible"
            elif page_result.identity_legibility == "not_found" and not identity_found:
                submission.identity_status = "unmatched_blank"
            elif identity_found:
                submission.identity_status = "unmatched_extracted"

            for segment_index, segment in enumerate(page_result.segments):
                segment.question_number, previous_base_question_number = (
                    _normalize_question_number(
                    segment.question_number,
                    previous_base_question_number,
                    )
                )
                segment.question_number = _resolve_subpart_continuation(
                    segment.question_number,
                    previous_resolved_question_number,
                    known_question_numbers,
                )
                if segment.question_number:
                    resolved_match = re.fullmatch(
                        r"(\d+)([a-z]?)", segment.question_number
                    )
                    if resolved_match:
                        previous_base_question_number = resolved_match.group(1)
                # If OCR gives "1" but the exam has "1a" and no standalone "1",
                # this page is the first sub-part of Question 1.
                if (
                    segment.question_number
                    and segment.question_number not in question_lookup
                    and re.fullmatch(r"\d+", segment.question_number)
                ):
                    first_subpart = f"{segment.question_number}a"

                    if first_subpart in question_lookup:
                        segment.question_number = first_subpart

                question_id = question_lookup.get(segment.question_number)
                if question_id:
                    previous_resolved_question_number = segment.question_number

                if not question_id:
                    unmatched_segments.append(
                        {
                            **segment.model_dump(),
                            "page_index": page_index,
                            "page_number": page_index + 1,
                            "segment_index": segment_index,
                        }
                    )
                    continue

                existing = db.query(Answer).filter(
                    Answer.submission_id == submission.id,
                    Answer.question_id == question_id
                ).first()

                if existing:
                    answer = existing
                    answer.raw_ocr_text = f"{existing.raw_ocr_text}\n{segment.text}"
                    answer.ocr_legibility = segment.legibility
                    answer.ocr_raw_response = segment.model_dump()
                else:
                    answer = Answer(
                        institution_id=submission.institution_id,
                        submission_id=submission.id,
                        question_id=question_id,
                        raw_ocr_text=segment.text,
                        ocr_legibility=segment.legibility,
                        ocr_raw_response=segment.model_dump()
                    )
                    db.add(answer)
                    db.flush()

                source = AnswerSource(
                    answer_id=answer.id,
                    page_index=page_index,
                    segment_index=segment_index,
                    question_number=segment.question_number,
                    extracted_text=segment.text,
                    has_math=segment.has_math,
                    ocr_segment=segment.model_dump(),
                )
                db.add(source)

            db.commit()

        if unmatched_segments:
            submission.unmatched_segments = unmatched_segments

        submission.status = "extracted"
        db.commit()

    except Exception as e:
        db.rollback()
        submission.status = "error"
        submission.error_message = str(e)
        db.commit()
        raise


# ---------- Batch fan-out ----------

def process_batch(batch_id: str, db: Session) -> None:
    batch = db.query(Batch).filter(Batch.id == batch_id).first()
    if not batch:
        return

    batch.status = "processing"
    db.commit()

    submissions = db.query(Submission).filter(Submission.batch_id == batch_id).all()

    for submission in submissions:
        try:
            process_submission(submission.id, db)
            batch.completed_count += 1
        except Exception:
            batch.failed_count += 1
        db.commit()

    batch.status = "completed" if batch.failed_count == 0 else "completed_with_errors"
    db.commit()

def create_submissions_from_upload(
    exam_id: str,
    institution_id: str,
    batch_id: str,
    file_bytes: bytes,
    filename: str,
    upload_dir: str,
    pages_per_student: int | None,
    db: Session
) -> list[Submission]:
    """
    Given one uploaded file, returns a list of newly created Submission rows.
    - If it's a PDF and pages_per_student is given: splits into multiple submissions.
    - Otherwise: creates exactly one submission for the whole file.
    """
    is_pdf = filename.lower().endswith(".pdf")
    submissions = []

    if is_pdf and pages_per_student:
        page_groups = _chunk_pdf_by_student(file_bytes, pages_per_student)

        for group_index, page_group in enumerate(page_groups):
            # Re-combine this student's pages into a single PDF file on disk,
            # so original_file_path always points at one real file per submission.
            images = [Image.open(io.BytesIO(p)).convert("RGB") for p in page_group]
            buffer = io.BytesIO()
            images[0].save(buffer, format="PDF", save_all=True, append_images=images[1:])
            group_bytes = buffer.getvalue()

            unique_name = f"{uuid.uuid4()}.pdf"
            save_path = os.path.join(upload_dir, unique_name)
            with open(save_path, "wb") as f:
                f.write(group_bytes)

            submission = Submission(
                institution_id=institution_id,
                exam_id=exam_id,
                batch_id=batch_id,
                original_file_path=save_path,
                page_count=len(page_group),
                status="uploaded"
            )
            db.add(submission)
            submissions.append(submission)

    else:
        _, ext = os.path.splitext(filename)
        unique_name = f"{uuid.uuid4()}{ext}"
        save_path = os.path.join(upload_dir, unique_name)
        with open(save_path, "wb") as f:
            f.write(file_bytes)

        submission = Submission(
            institution_id=institution_id,
            exam_id=exam_id,
            batch_id=batch_id,
            original_file_path=save_path,
            page_count=1,
            status="uploaded"
        )
        db.add(submission)
        submissions.append(submission)

    db.commit()
    for s in submissions:
        db.refresh(s)

    return submissions
