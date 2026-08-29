from __future__ import annotations

from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from models import Answer, AnswerSource, Course, Exam, GradingRun, Question, ReviewLabel, Submission


def _number(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    return value


def _has_noncontiguous_pages(page_indices: list[int]) -> bool:
    return any(
        current - previous > 1
        for previous, current in zip(page_indices, page_indices[1:])
    )


def _serialize_source(source: AnswerSource) -> dict[str, Any]:
    ocr_segment = source.ocr_segment or {}
    return {
        "id": source.id,
        "answer_id": source.answer_id,
        "page_index": source.page_index,
        "page_number": source.page_index + 1,
        "segment_index": source.segment_index,
        "question_number": source.question_number,
        "extracted_text": source.extracted_text,
        "has_math": source.has_math,
        "ocr_segment": ocr_segment,
        "resolved_from_unmatched": bool(
            ocr_segment.get("resolved_from_unmatched")
        ),
        "created_at": source.created_at,
    }


def _serialize_answer(answer: Answer) -> dict[str, Any]:
    return {
        "id": answer.id,
        "question_id": answer.question_id,
        "raw_ocr_text": answer.raw_ocr_text,
        "ocr_legibility": answer.ocr_legibility,
        "score": _number(answer.score),
        "max_score": _number(answer.max_score),
        "feedback": answer.feedback,
        "llm_confidence": _number(answer.llm_confidence),
        "final_confidence": _number(answer.final_confidence),
        "needs_review": answer.needs_review,
        "review_status": answer.review_status,
        "created_at": answer.created_at,
    }


def build_extraction_review(submission_id: str, db: Session) -> dict[str, Any]:
    submission = (
        db.query(Submission).filter(Submission.id == submission_id).first()
    )
    if not submission:
        raise ValueError(f"Submission {submission_id} not found")

    exam = db.query(Exam).filter(Exam.id == submission.exam_id).first()
    course = db.query(Course).filter(Course.id == exam.course_id).first() if exam else None

    questions = (
        db.query(Question)
        .filter(Question.exam_id == submission.exam_id)
        .order_by(Question.order_index.asc(), Question.question_number.asc())
        .all()
    )
    answers = (
        db.query(Answer)
        .filter(Answer.submission_id == submission.id)
        .all()
    )
    answers_by_question = {answer.question_id: answer for answer in answers}
    answer_ids = [answer.id for answer in answers]
    sources = []
    if answer_ids:
        sources = (
            db.query(AnswerSource)
            .filter(AnswerSource.answer_id.in_(answer_ids))
            .order_by(AnswerSource.page_index.asc(), AnswerSource.segment_index.asc())
            .all()
        )

    sources_by_answer: dict[str, list[AnswerSource]] = {}
    for source in sources:
        sources_by_answer.setdefault(source.answer_id, []).append(source)

    rows = []
    suspicious_answers = []
    missing_question_numbers = []
    source_tracked_count = 0

    for question in questions:
        answer = answers_by_question.get(question.id)
        answer_sources = sources_by_answer.get(answer.id, []) if answer else []
        flags: list[dict[str, Any]] = []

        if not answer:
            missing_question_numbers.append(question.question_number)
        elif not answer_sources:
            flags.append(
                {
                    "code": "missing_source_tracking",
                    "message": "This answer has OCR text but no tracked source segment.",
                }
            )
        else:
            source_tracked_count += 1
            page_indices = sorted({source.page_index for source in answer_sources})
            if _has_noncontiguous_pages(page_indices):
                flags.append(
                    {
                        "code": "noncontiguous_source_pages",
                        "message": (
                            "Segments mapped to this answer come from distant pages: "
                            + ", ".join(str(index + 1) for index in page_indices)
                            + "."
                        ),
                    }
                )

            mismatched_labels = sorted(
                {
                    source.question_number
                    for source in answer_sources
                    if source.question_number
                    and source.question_number != question.question_number
                }
            )
            if mismatched_labels:
                flags.append(
                    {
                        "code": "source_label_mismatch",
                        "message": (
                            "Tracked OCR labels do not match this question: "
                            + ", ".join(mismatched_labels)
                            + "."
                        ),
                    }
                )

        row = {
            "question": {
                "id": question.id,
                "question_number": question.question_number,
                "question_text": question.question_text,
                "max_score": _number(question.max_score),
                "order_index": question.order_index,
            },
            "answer": _serialize_answer(answer) if answer else None,
            "sources": [_serialize_source(source) for source in answer_sources],
            "mapping_flags": flags,
        }
        rows.append(row)
        if flags:
            suspicious_answers.append(
                {
                    "answer_id": answer.id if answer else None,
                    "question_id": question.id,
                    "question_number": question.question_number,
                    "flags": flags,
                }
            )

    unmatched_count = len(submission.unmatched_segments or [])
    mapped_answer_count = len(questions) - len(missing_question_numbers)
    mapping_complete = bool(questions) and mapped_answer_count == len(questions)
    blocking_reasons = []
    if not questions:
        blocking_reasons.append("The assessment has no configured questions.")
    if missing_question_numbers:
        blocking_reasons.append(
            f"{len(missing_question_numbers)} expected question(s) have no mapped answer."
        )
    if suspicious_answers:
        blocking_reasons.append(
            f"{len(suspicious_answers)} answer mapping(s) require verification."
        )
    if unmatched_count:
        blocking_reasons.append(
            f"{unmatched_count} OCR segment(s) are still unmatched."
        )
    if submission.status not in {"extracted", "graded", "needs_review", "reviewed"}:
        blocking_reasons.append(
            f"Submission status is '{submission.status}', not ready for grading."
        )

    bulk_grading_allowed = not blocking_reasons

    return {
        "submission": {
            "id": submission.id,
            "exam_id": submission.exam_id,
            "batch_id": submission.batch_id,
            "student_id": submission.student_id,
            "extracted_student_name": submission.extracted_student_name,
            "extracted_student_number": submission.extracted_student_number,
            "instructor_name": course.instructor_name if course else None,
            "identity_status": submission.identity_status,
            "page_count": submission.page_count,
            "status": submission.status,
            "error_message": submission.error_message,
            "uploaded_at": submission.uploaded_at,
        },
        "readiness": {
            "expected_question_count": len(questions),
            "mapped_answer_count": mapped_answer_count,
            "source_tracked_answer_count": source_tracked_count,
            "missing_question_numbers": missing_question_numbers,
            "suspicious_mapping_count": len(suspicious_answers),
            "unmatched_segment_count": unmatched_count,
            "mapping_complete": mapping_complete,
            "bulk_grading_allowed": bulk_grading_allowed,
            "blocking_reasons": blocking_reasons,
        },
        "suspicious_answers": suspicious_answers,
        "questions": rows,
        "unmatched_segments": submission.unmatched_segments or [],
    }


def _assert_answer_is_ungraded(answer: Answer, db: Session) -> None:
    has_runs = (
        db.query(GradingRun).filter(GradingRun.answer_id == answer.id).first()
        is not None
    )
    has_labels = (
        db.query(ReviewLabel).filter(ReviewLabel.answer_id == answer.id).first()
        is not None
    )
    if (
        answer.score is not None
        or answer.teacher_override_score is not None
        or has_runs
        or has_labels
    ):
        raise ValueError(
            "Source mappings cannot be changed after grading or instructor review."
        )


def _rebuild_answer_from_sources(answer: Answer, db: Session) -> bool:
    sources = (
        db.query(AnswerSource)
        .filter(AnswerSource.answer_id == answer.id)
        .order_by(AnswerSource.page_index.asc(), AnswerSource.segment_index.asc())
        .all()
    )
    if not sources:
        db.delete(answer)
        return False

    answer.raw_ocr_text = "\n".join(source.extracted_text for source in sources)
    legibility_rank = {"clear": 0, "partial": 1, "illegible": 2}
    answer.ocr_legibility = max(
        (
            (source.ocr_segment or {}).get("legibility", "clear")
            for source in sources
        ),
        key=lambda value: legibility_rank.get(value, 0),
    )
    answer.ocr_raw_response = sources[-1].ocr_segment
    return True


def move_answer_source(
    source_id: str,
    target_question_id: str,
    db: Session,
) -> dict[str, Any]:
    source = db.query(AnswerSource).filter(AnswerSource.id == source_id).first()
    if not source:
        raise ValueError(f"Answer source {source_id} not found")

    origin = db.query(Answer).filter(Answer.id == source.answer_id).first()
    if not origin:
        raise ValueError("The source answer no longer exists")
    _assert_answer_is_ungraded(origin, db)

    submission = (
        db.query(Submission).filter(Submission.id == origin.submission_id).first()
    )
    target_question = (
        db.query(Question).filter(Question.id == target_question_id).first()
    )
    if not submission or not target_question:
        raise ValueError("Submission or target question not found")
    if target_question.exam_id != submission.exam_id:
        raise ValueError("The target question belongs to a different assessment")

    target = (
        db.query(Answer)
        .filter(
            Answer.submission_id == submission.id,
            Answer.question_id == target_question.id,
        )
        .first()
    )
    if target and target.id == origin.id:
        return build_extraction_review(submission.id, db)
    if target:
        _assert_answer_is_ungraded(target, db)
    else:
        target = Answer(
            institution_id=submission.institution_id,
            submission_id=submission.id,
            question_id=target_question.id,
            needs_review=False,
            review_status="none",
        )
        db.add(target)
        db.flush()

    source.answer_id = target.id
    source.question_number = target_question.question_number
    db.flush()
    _rebuild_answer_from_sources(target, db)
    _rebuild_answer_from_sources(origin, db)
    db.commit()

    return build_extraction_review(submission.id, db)


def remove_manually_assigned_source(
    source_id: str,
    db: Session,
) -> dict[str, Any]:
    source = db.query(AnswerSource).filter(AnswerSource.id == source_id).first()
    if not source:
        raise ValueError(f"Answer source {source_id} not found")
    if not (source.ocr_segment or {}).get("resolved_from_unmatched"):
        raise ValueError(
            "Only OCR fragments assigned during extraction review can be removed as noise"
        )

    answer = db.query(Answer).filter(Answer.id == source.answer_id).first()
    if not answer:
        raise ValueError("The source answer no longer exists")
    _assert_answer_is_ungraded(answer, db)
    submission_id = answer.submission_id

    db.delete(source)
    db.flush()
    _rebuild_answer_from_sources(answer, db)
    db.commit()
    return build_extraction_review(submission_id, db)


def resolve_unmatched_segment(
    submission_id: str,
    unmatched_index: int,
    action: str,
    question_id: str | None,
    page_index: int | None,
    db: Session,
) -> dict[str, Any]:
    submission = db.query(Submission).filter(Submission.id == submission_id).first()
    if not submission:
        raise ValueError("Submission not found")

    segments = list(submission.unmatched_segments or [])
    if unmatched_index < 0 or unmatched_index >= len(segments):
        raise ValueError("Unmatched segment not found")
    segment = segments[unmatched_index]

    if action == "assign":
        if not question_id:
            raise ValueError("A target question is required")
        if page_index is None or page_index < 0 or page_index >= submission.page_count:
            raise ValueError("A valid source page is required")

        question = db.query(Question).filter(Question.id == question_id).first()
        if not question or question.exam_id != submission.exam_id:
            raise ValueError("The target question belongs to a different assessment")

        answer = (
            db.query(Answer)
            .filter(
                Answer.submission_id == submission.id,
                Answer.question_id == question.id,
            )
            .first()
        )
        if answer:
            _assert_answer_is_ungraded(answer, db)
        else:
            answer = Answer(
                institution_id=submission.institution_id,
                submission_id=submission.id,
                question_id=question.id,
                needs_review=False,
                review_status="none",
            )
            db.add(answer)
            db.flush()

        original_segment = dict(segment)
        db.add(
            AnswerSource(
                answer_id=answer.id,
                page_index=page_index,
                segment_index=10000 + unmatched_index,
                question_number=question.question_number,
                extracted_text=str(segment.get("text") or "").strip(),
                has_math=bool(segment.get("has_math")),
                ocr_segment={**original_segment, "resolved_from_unmatched": True},
            )
        )
        db.flush()
        _rebuild_answer_from_sources(answer, db)
    elif action != "ignore":
        raise ValueError("Invalid unmatched-segment action")

    segments.pop(unmatched_index)
    submission.unmatched_segments = segments or None
    db.commit()
    return build_extraction_review(submission.id, db)


def bulk_resolve_segments(
    submission_id: str,
    action: str,
    question_id: str | None,
    source_ids: list[str],
    unmatched_indices: list[int],
    db: Session,
) -> dict[str, Any]:
    """Resolve several mapped and unmatched OCR fragments in one transaction."""
    submission = db.query(Submission).filter(Submission.id == submission_id).first()
    if not submission:
        raise ValueError("Submission not found")

    unique_source_ids = list(dict.fromkeys(source_ids))
    unique_unmatched_indices = sorted(set(unmatched_indices))
    if not unique_source_ids and not unique_unmatched_indices:
        raise ValueError("Select at least one OCR fragment")
    if any(index < 0 for index in unique_unmatched_indices):
        raise ValueError("Unmatched segment not found")

    segments = list(submission.unmatched_segments or [])
    if any(index >= len(segments) for index in unique_unmatched_indices):
        raise ValueError("Unmatched segment not found")

    selected_sources: list[AnswerSource] = []
    origins: dict[str, Answer] = {}
    if unique_source_ids:
        selected_sources = (
            db.query(AnswerSource)
            .filter(AnswerSource.id.in_(unique_source_ids))
            .all()
        )
        if len(selected_sources) != len(unique_source_ids):
            raise ValueError("One or more OCR fragments were not found")
        for source in selected_sources:
            origin = db.query(Answer).filter(Answer.id == source.answer_id).first()
            if not origin or origin.submission_id != submission.id:
                raise ValueError("An OCR fragment belongs to a different submission")
            _assert_answer_is_ungraded(origin, db)
            origins[origin.id] = origin

    if action == "ignore":
        if unique_source_ids:
            raise ValueError("Mapped fragments must be moved, not marked as noise")
        submission.unmatched_segments = [
            segment
            for index, segment in enumerate(segments)
            if index not in set(unique_unmatched_indices)
        ] or None
        db.commit()
        return build_extraction_review(submission.id, db)

    if action != "assign" or not question_id:
        raise ValueError("A target question is required")

    target_question = db.query(Question).filter(Question.id == question_id).first()
    if not target_question or target_question.exam_id != submission.exam_id:
        raise ValueError("The target question belongs to a different assessment")

    target = (
        db.query(Answer)
        .filter(
            Answer.submission_id == submission.id,
            Answer.question_id == target_question.id,
        )
        .first()
    )
    if target:
        _assert_answer_is_ungraded(target, db)
    else:
        target = Answer(
            institution_id=submission.institution_id,
            submission_id=submission.id,
            question_id=target_question.id,
            needs_review=False,
            review_status="none",
        )
        db.add(target)
        db.flush()

    for source in selected_sources:
        source.answer_id = target.id
        source.question_number = target_question.question_number

    for unmatched_index in unique_unmatched_indices:
        segment = segments[unmatched_index]
        page_index = segment.get("page_index")
        if not isinstance(page_index, int) or not 0 <= page_index < submission.page_count:
            raise ValueError("A selected fragment has no valid source page")
        db.add(
            AnswerSource(
                answer_id=target.id,
                page_index=page_index,
                segment_index=10000 + unmatched_index,
                question_number=target_question.question_number,
                extracted_text=str(segment.get("text") or "").strip(),
                has_math=bool(segment.get("has_math")),
                ocr_segment={**dict(segment), "resolved_from_unmatched": True},
            )
        )

    selected_unmatched = set(unique_unmatched_indices)
    submission.unmatched_segments = [
        segment
        for index, segment in enumerate(segments)
        if index not in selected_unmatched
    ] or None
    db.flush()

    _rebuild_answer_from_sources(target, db)
    for origin in origins.values():
        if origin.id != target.id:
            _rebuild_answer_from_sources(origin, db)

    db.commit()
    return build_extraction_review(submission.id, db)
