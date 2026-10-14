import os
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from pydantic import ValidationError

os.environ.setdefault("GEMINI_API_KEY", "test-key-not-used")

from database import Base
import models  # noqa: F401
from models import Answer, AnswerSource, Question, Submission
from services.ocr_service import (
    OCRPageResult, OCRSegment, _is_cover_mark, _question_for_segment,
    _normalize_question_number, _visual_mapping_second_pass,
    assert_reprocessing_allowed, process_submission,
)
from services.whole_paper_mapping_service import reconcile_paper
from services.extraction_review_service import build_extraction_review


class OcrEvidenceTests(unittest.TestCase):
    def test_whole_paper_reconciliation_corrects_strong_topic_conflict(self):
        questions = [
            Question(id="q1", question_number="1", question_text="Use NLTK stemmers and stopwords in Python"),
            Question(id="q2", question_number="2", question_text="Explain sound amplitude and spectral frequency"),
        ]
        def segment(label, value):
            return OCRSegment(question_number=label, text=value, language="en",
                              legibility="clear", has_math=False)
        pages = [OCRPageResult(page_language="en", identity_legibility="not_found", segments=[
            segment("2a", "sound amplitude and spectral frequency"),
            segment("3e", "from NLTK.stem import PorterStemmer; apply stemmers"),
            segment(None, "NLTK stopwords corpus"),
        ])]
        decisions = reconcile_paper(pages, questions, _normalize_question_number,
                                    _question_for_segment, _is_cover_mark)
        self.assertEqual(decisions[(0, 0)].question_id, "q2")
        self.assertEqual(decisions[(0, 1)].question_id, "q1")
        self.assertEqual(decisions[(0, 1)].method, "semantic_correction")
        self.assertEqual(decisions[(0, 2)].question_id, "q1")

    def test_unlabelled_continuation_requires_unanimous_page(self):
        questions = [Question(id=f"q{i}", question_number=str(i), question_text=f"Task {i}") for i in (1, 2)]
        def segment(label, value):
            return OCRSegment(question_number=label, text=value, language="en",
                              legibility="clear", has_math=False)
        page = OCRPageResult(page_language="en", identity_legibility="not_found", segments=[
            segment("1", "alpha result"), segment("2", "beta result"),
            segment(None, "more handwritten work"),
        ])
        decisions = reconcile_paper([page], questions, _normalize_question_number,
                                    _question_for_segment, _is_cover_mark)
        self.assertIsNone(decisions[(0, 2)].question_id)
        self.assertEqual(decisions[(0, 2)].candidates, ("1", "2"))

    def test_visual_mapping_quota_failure_is_non_destructive(self):
        page = OCRPageResult(page_language="en", identity_legibility="not_found", segments=[
            OCRSegment(question_number=None, text="unplaced answer", language="en",
                       legibility="clear", has_math=False),
        ])
        questions = [Question(id="q1", question_number="1", question_text="Explain the answer")]
        decisions = reconcile_paper([page], questions, _normalize_question_number,
                                    _question_for_segment, _is_cover_mark)
        with patch.dict(os.environ, {"OCR_MAPPING_SECOND_PASS_ENABLED": "true"}), \
             patch("services.ocr_service.Image.open") as image_open, \
             patch("services.ocr_service.generate", side_effect=RuntimeError("429 quota")):
            updated, failed = _visual_mapping_second_pass(decisions, [page], [b"image"], questions)
        self.assertTrue(failed)
        self.assertIsNone(updated[(0, 0)].question_id)
        image_open.assert_called_once()

    def test_visual_mapping_accepts_only_requested_configured_indices(self):
        page = OCRPageResult(page_language="en", identity_legibility="not_found", segments=[
            OCRSegment(question_number=None, text="unplaced answer", language="en",
                       legibility="clear", has_math=False),
        ])
        questions = [Question(id="q1", question_number="1", question_text="Explain the answer")]
        decisions = reconcile_paper([page], questions, _normalize_question_number,
                                    _question_for_segment, _is_cover_mark)
        response = '{"assignments":[{"page_index":0,"segment_index":0,"question_number":"1"},{"page_index":4,"segment_index":0,"question_number":"1"},{"page_index":0,"segment_index":1,"question_number":"9"}]}'
        with patch.dict(os.environ, {"OCR_MAPPING_SECOND_PASS_ENABLED": "true"}), \
             patch("services.ocr_service.Image.open"), \
             patch("services.ocr_service.generate", return_value=response):
            updated, failed = _visual_mapping_second_pass(decisions, [page], [b"image"], questions)
        self.assertFalse(failed)
        self.assertEqual(updated[(0, 0)].question_id, "q1")
        self.assertEqual(updated[(0, 0)].method, "visual_check")
        self.assertEqual(len(updated), 1)

    def test_quota_exhausted_after_primary_ocr_keeps_extraction_and_small_issue(self):
        engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(engine)
        db = sessionmaker(bind=engine)()
        with tempfile.TemporaryDirectory() as directory:
            paper = Path(directory) / "paper.pdf"
            paper.write_bytes(b"synthetic fixture")
            submission = Submission(id="quota-paper", institution_id="institution",
                                    exam_id="exam", original_file_path=str(paper),
                                    status="uploaded", page_count=1)
            question = Question(id="q1", institution_id="institution", exam_id="exam",
                                question_number="1", question_text="Explain the process",
                                max_score=2, rubric_json={"criteria": []}, order_index=1)
            db.add_all([submission, question])
            db.commit()
            page = OCRPageResult(page_language="en", identity_legibility="not_found",
                                 segments=[OCRSegment(question_number=None, text="unclear work",
                                                      language="en", legibility="partial",
                                                      has_math=False,
                                                      bounding_box={"x": .1, "y": .2, "width": .6, "height": .2})])
            with patch.dict(os.environ, {"OCR_MAPPING_SECOND_PASS_ENABLED": "true"}), \
                 patch("services.ocr_service._split_pdf", return_value=[b"image"]), \
                 patch("services.ocr_service.extract_page", return_value=page), \
                 patch("services.ocr_service.Image.open"), \
                 patch("services.ocr_service.generate", side_effect=RuntimeError("quota exceeded")):
                process_submission(submission.id, db)
            report = build_extraction_review(submission.id, db)
            self.assertEqual(report["submission"]["status"], "extracted")
            self.assertEqual(report["readiness"]["unmatched_segment_count"], 1)
            self.assertEqual(report["mapping_issues"][0]["page_number"], 1)
            self.assertEqual(report["mapping_issues"][0]["bounding_box"]["x"], .1)
            self.assertIn("Visual check unavailable", report["mapping_issues"][0]["reason"])
        db.close()

    def test_segment_accepts_normalized_evidence_box(self):
        segment = OCRSegment(
            question_number="2",
            text="SELECT * FROM COURSES",
            language="en",
            legibility="clear",
            has_math=False,
            bounding_box={"x": 0.1, "y": 0.2, "width": 0.8, "height": 0.3},
        )
        self.assertEqual(segment.bounding_box.x, 0.1)

    def test_segment_rejects_box_outside_page(self):
        with self.assertRaises(ValidationError):
            OCRSegment(
                question_number="2",
                text="answer",
                language="en",
                legibility="clear",
                has_math=False,
                bounding_box={"x": 0.8, "y": 0.2, "width": 0.3, "height": 0.3},
            )

    def test_subparts_map_to_configured_parent_without_mapping_other_questions(self):
        lookup = {"1": "q1", "2": "q2", "3": "q3"}
        self.assertEqual(_question_for_segment("3e", lookup), ("3", "q3"))
        self.assertEqual(_question_for_segment("2c", lookup), ("2", "q2"))
        self.assertEqual(_question_for_segment("4a", lookup), (None, None))

    def test_score_only_identity_page_fallback_does_not_drop_numeric_quiz_page(self):
        marks = [
            OCRSegment(question_number=str(index), text=str(score), language="en",
                       legibility="clear", has_math=False)
            for index, score in enumerate((7, 3, 9, 19), start=1)
        ]
        cover = OCRPageResult(page_language="en", segments=marks,
                              student_name="Example Student", student_id="S123",
                              identity_legibility="clear")
        self.assertTrue(_is_cover_mark(marks[0], cover, 4, 0))
        self.assertFalse(_is_cover_mark(marks[0], cover, 1, 0))
        self.assertFalse(_is_cover_mark(marks[0], cover, 4, 1))
        cover.segments.append(OCRSegment(question_number="1", text="working shown",
                                         language="en", legibility="clear", has_math=False))
        self.assertFalse(_is_cover_mark(marks[0], cover, 4, 0))

    def test_cover_marks_are_excluded_and_subparts_reach_correct_parent(self):
        engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(engine)
        db = sessionmaker(bind=engine)()
        with tempfile.TemporaryDirectory() as directory:
            paper = Path(directory) / "synthetic.pdf"
            paper.write_bytes(b"synthetic test fixture")
            submission = Submission(
                id="ocr-paper", institution_id="institution", exam_id="exam",
                original_file_path=str(paper), status="uploaded",
                identity_status="unmatched_blank", page_count=2,
            )
            questions = [
                Question(id=f"q{number}", institution_id="institution", exam_id="exam",
                         question_number=str(number), question_text=f"Question {number}",
                         max_score=10, rubric_json={"criteria": []}, order_index=number)
                for number in (1, 2, 3)
            ]
            db.add_all([submission, *questions])
            db.commit()

            def segment(number, value, role="answer"):
                return OCRSegment(question_number=number, text=value, language="en",
                                  legibility="clear", has_math=False, content_role=role)

            cover = OCRPageResult(page_language="en", student_name="Example Student",
                                  student_id="S123", identity_legibility="clear", page_role="cover",
                                  segments=[segment("2", "7"), segment(None, "19")])
            answers = OCRPageResult(page_language="en", student_name=None, student_id=None,
                                    identity_legibility="not_found", page_role="answers",
                                    segments=[segment("1a", "NLTK corpus"),
                                              segment("2b", "spectral features"),
                                              segment("3e", "sentiment model"),
                                              segment("3", "9/10", "marking")])
            with patch("services.ocr_service._split_pdf", return_value=[b"first", b"second"]), \
                 patch("services.ocr_service.extract_page", side_effect=[cover, answers]):
                process_submission(submission.id, db)
            report = build_extraction_review(submission.id, db)
            rows = {row["question"]["question_number"]: row for row in report["questions"]}
            self.assertEqual(rows["1"]["answer"]["raw_ocr_text"], "NLTK corpus")
            self.assertEqual(rows["2"]["answer"]["raw_ocr_text"], "spectral features")
            self.assertEqual(rows["3"]["answer"]["raw_ocr_text"], "sentiment model")
            self.assertEqual(report["readiness"]["unmatched_segment_count"], 0)
            self.assertEqual(len(report["excluded_segments"]), 3)
            self.assertTrue(report["readiness"]["bulk_grading_allowed"])
        db.close()

    def test_reprocess_preserves_old_mapping_if_provider_fails_then_replaces_once(self):
        engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(engine)
        db = sessionmaker(bind=engine)()
        with tempfile.TemporaryDirectory() as directory:
            paper = Path(directory) / "synthetic.pdf"
            paper.write_bytes(b"synthetic test fixture")
            submission = Submission(
                id="redo-paper", institution_id="institution", exam_id="exam",
                original_file_path=str(paper), status="extracted", page_count=2,
                identity_status="unmatched_blank",
            )
            question = Question(id="redo-q", institution_id="institution", exam_id="exam",
                                question_number="1", question_text="Explain", max_score=2,
                                rubric_json={"criteria": []}, order_index=1)
            answer = Answer(id="old-answer", institution_id="institution",
                            submission_id=submission.id, question_id=question.id,
                            raw_ocr_text="old OCR", ocr_legibility="clear")
            source = AnswerSource(id="old-source", answer_id=answer.id, page_index=1,
                                  segment_index=0, question_number="1",
                                  extracted_text="old OCR", has_math=False,
                                  ocr_segment={"question_number": "1"})
            db.add_all([submission, question, answer, source])
            db.commit()
            page = OCRPageResult(
                page_language="en", student_name=None, student_id=None,
                identity_legibility="not_found", segments=[OCRSegment(
                    question_number="1", text="new OCR", language="en",
                    legibility="clear", has_math=False,
                )],
            )
            with patch("services.ocr_service._split_pdf", return_value=[b"first", b"second"]), \
                 patch("services.ocr_service.extract_page", side_effect=[page, RuntimeError("quota")]):
                with self.assertRaisesRegex(RuntimeError, "quota"):
                    process_submission(submission.id, db, reprocess=True)
            self.assertEqual(db.query(Answer).filter_by(submission_id=submission.id).one().raw_ocr_text, "old OCR")
            self.assertEqual(db.query(AnswerSource).filter_by(answer_id="old-answer").count(), 1)
            self.assertEqual(db.get(Submission, submission.id).status, "extracted")

            with patch("services.ocr_service._split_pdf", return_value=[b"first", b"second"]), \
                 patch("services.ocr_service.extract_page", side_effect=[page, OCRPageResult(
                     page_language="en", student_name=None, student_id=None,
                     identity_legibility="not_found", segments=[],
                 )]):
                process_submission(submission.id, db, reprocess=True)
            self.assertEqual(db.query(Answer).filter_by(submission_id=submission.id).one().raw_ocr_text, "new OCR")
            self.assertEqual(db.query(AnswerSource).filter_by(answer_id="old-answer").count(), 0)
            self.assertEqual(db.query(AnswerSource).count(), 1)
            self.assertEqual(db.get(Submission, submission.id).status, "extracted")
            submission.student_id = "verified-student"
            submission.identity_status = "matched"
            submission.extracted_student_name = "Verified Name"
            submission.extracted_student_number = "S999"
            db.commit()
            ocr_with_different_name = OCRPageResult(
                page_language="en", student_name="Unverified OCR", student_id="S000",
                identity_legibility="clear", segments=[OCRSegment(
                    question_number="1", text="new OCR", language="en",
                    legibility="clear", has_math=False,
                )],
            )
            with patch("services.ocr_service._split_pdf", return_value=[b"first", b"second"]), \
                 patch("services.ocr_service.extract_page", side_effect=[
                     ocr_with_different_name, OCRPageResult(
                         page_language="en", student_name=None, student_id=None,
                         identity_legibility="not_found", segments=[],
                     ),
                 ]):
                process_submission(submission.id, db, reprocess=True)
            self.assertEqual(submission.extracted_student_name, "Verified Name")
            self.assertEqual(submission.extracted_student_number, "S999")
            self.assertEqual(db.query(AnswerSource).count(), 1)
            saved_answer = db.query(Answer).filter_by(submission_id=submission.id).one()
            saved_answer.score = 1
            db.commit()
            with self.assertRaisesRegex(ValueError, "recorded grades"):
                assert_reprocessing_allowed(submission, db)
        db.close()


if __name__ == "__main__":
    unittest.main()
