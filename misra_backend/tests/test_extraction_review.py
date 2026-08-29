import os
import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


os.environ.setdefault("GEMINI_API_KEY", "test-key-not-used")

from database import Base  # noqa: E402
import models  # noqa: E402,F401
from models import Answer, AnswerSource, Question, Submission  # noqa: E402
from services.extraction_review_service import (  # noqa: E402
    _has_noncontiguous_pages,
    bulk_resolve_segments,
    build_extraction_review,
    move_answer_source,
)
from services.ocr_service import _resolve_subpart_continuation  # noqa: E402
from schemas.page_recovery_input import RecoverySegmentInput  # noqa: E402
from services.page_recovery_service import (  # noqa: E402
    _sign_preview,
    confirm_page_recovery,
)


class ExtractionReviewTests(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(engine)
        self.db = sessionmaker(bind=engine)()

    def tearDown(self):
        self.db.close()

    def test_three_consecutive_pages_are_not_flagged_as_distant(self):
        self.assertFalse(_has_noncontiguous_pages([3, 4, 5]))
        self.assertTrue(_has_noncontiguous_pages([2, 6]))

    def test_sequential_subpart_repairs_valid_but_wrong_base(self):
        known = ["2c", "2d", "2e", "5d", "5e"]
        self.assertEqual(
            _resolve_subpart_continuation("5d", "2c", known),
            "2d",
        )
        self.assertEqual(
            _resolve_subpart_continuation("5e", "2d", known),
            "2e",
        )
        self.assertEqual(
            _resolve_subpart_continuation("5d", "4", known),
            "5d",
        )

    def test_review_flags_missing_and_noncontiguous_mapping_then_move_repairs_it(self):
        submission = Submission(
            id="submission-1",
            institution_id="institution-1",
            exam_id="exam-1",
            original_file_path="not-needed.pdf",
            page_count=9,
            status="extracted",
            identity_status="unmatched_blank",
        )
        question_2d = Question(
            id="question-2d",
            institution_id="institution-1",
            exam_id="exam-1",
            question_number="2d",
            question_text="Prove the relation property.",
            max_score=2,
            rubric_json={"max_score": 2, "criteria": []},
            order_index=1,
            language="en",
        )
        question_5d = Question(
            id="question-5d",
            institution_id="institution-1",
            exam_id="exam-1",
            question_number="5d",
            question_text="Determine whether the graphs are isomorphic.",
            max_score=2,
            rubric_json={"max_score": 2, "criteria": []},
            order_index=2,
            language="en",
        )
        answer_5d = Answer(
            id="answer-5d",
            institution_id="institution-1",
            submission_id=submission.id,
            question_id=question_5d.id,
            raw_ocr_text="proof work\ngraph work",
            ocr_legibility="clear",
            needs_review=False,
            review_status="none",
        )
        wrong_source = AnswerSource(
            id="source-wrong",
            answer_id=answer_5d.id,
            page_index=2,
            segment_index=0,
            question_number="5d",
            extracted_text="proof work",
            has_math=True,
            ocr_segment={"question_number": "5d", "legibility": "clear"},
        )
        correct_source = AnswerSource(
            id="source-correct",
            answer_id=answer_5d.id,
            page_index=6,
            segment_index=0,
            question_number="5d",
            extracted_text="graph work",
            has_math=False,
            ocr_segment={"question_number": "5d", "legibility": "clear"},
        )
        self.db.add_all(
            [submission, question_2d, question_5d, answer_5d, wrong_source, correct_source]
        )
        self.db.commit()

        before = build_extraction_review(submission.id, self.db)
        self.assertEqual(before["readiness"]["missing_question_numbers"], ["2d"])
        self.assertEqual(before["readiness"]["suspicious_mapping_count"], 1)
        self.assertFalse(before["readiness"]["bulk_grading_allowed"])

        after = move_answer_source(wrong_source.id, question_2d.id, self.db)
        self.assertEqual(after["readiness"]["missing_question_numbers"], [])
        self.assertEqual(after["readiness"]["suspicious_mapping_count"], 0)
        self.assertTrue(after["readiness"]["bulk_grading_allowed"])
        moved_row = next(
            row
            for row in after["questions"]
            if row["question"]["question_number"] == "2d"
        )
        self.assertEqual(moved_row["answer"]["raw_ocr_text"], "proof work")

    def test_bulk_segment_resolution_moves_mapped_and_unmatched_fragments(self):
        submission = Submission(
            id="bulk-submission",
            institution_id="institution-1",
            exam_id="bulk-exam",
            original_file_path="not-needed.pdf",
            page_count=3,
            status="extracted",
            identity_status="unmatched_blank",
            unmatched_segments=[
                {"text": "page footer", "page_index": 2, "has_math": False},
                {"text": "second SQL statement", "page_index": 2, "has_math": False},
            ],
        )
        question_1 = Question(
            id="bulk-question-1",
            institution_id="institution-1",
            exam_id="bulk-exam",
            question_number="1",
            question_text="First task",
            max_score=1,
            rubric_json={"criteria": []},
            order_index=1,
        )
        question_2 = Question(
            id="bulk-question-2",
            institution_id="institution-1",
            exam_id="bulk-exam",
            question_number="2",
            question_text="SQL tasks",
            max_score=2,
            rubric_json={"criteria": []},
            order_index=2,
        )
        answer_1 = Answer(
            id="bulk-answer-1",
            institution_id="institution-1",
            submission_id=submission.id,
            question_id=question_1.id,
            raw_ocr_text="first answer\nfirst SQL statement",
            ocr_legibility="clear",
        )
        retained = AnswerSource(
            id="bulk-source-retained",
            answer_id=answer_1.id,
            page_index=0,
            segment_index=0,
            question_number="1",
            extracted_text="first answer",
            has_math=False,
            ocr_segment={"legibility": "clear"},
        )
        moved = AnswerSource(
            id="bulk-source-moved",
            answer_id=answer_1.id,
            page_index=1,
            segment_index=0,
            question_number="1",
            extracted_text="first SQL statement",
            has_math=False,
            ocr_segment={"legibility": "clear"},
        )
        self.db.add_all(
            [submission, question_1, question_2, answer_1, retained, moved]
        )
        self.db.commit()

        assigned = bulk_resolve_segments(
            submission.id,
            "assign",
            question_2.id,
            [moved.id],
            [1],
            self.db,
        )
        question_2_row = next(
            row for row in assigned["questions"] if row["question"]["question_number"] == "2"
        )
        self.assertEqual(
            question_2_row["answer"]["raw_ocr_text"],
            "first SQL statement\nsecond SQL statement",
        )
        self.assertEqual(assigned["readiness"]["unmatched_segment_count"], 1)

        cleaned = bulk_resolve_segments(
            submission.id,
            "ignore",
            None,
            [],
            [0],
            self.db,
        )
        self.assertEqual(cleaned["readiness"]["unmatched_segment_count"], 0)
        question_1_row = next(
            row for row in cleaned["questions"] if row["question"]["question_number"] == "1"
        )
        self.assertEqual(question_1_row["answer"]["raw_ocr_text"], "first answer")

    def test_confirmed_page_recovery_is_signed_and_idempotent(self):
        submission = Submission(
            id="recovery-submission",
            institution_id="institution-1",
            exam_id="recovery-exam",
            original_file_path="not-needed.pdf",
            page_count=2,
            status="extracted",
            identity_status="unmatched_blank",
        )
        question = Question(
            id="recovery-question",
            institution_id="institution-1",
            exam_id="recovery-exam",
            question_number="1b",
            question_text="Choose the correct options.",
            max_score=1.5,
            rubric_json={"max_score": 1.5, "criteria": []},
            order_index=1,
            language="en",
        )
        self.db.add_all([submission, question])
        self.db.commit()
        segments = [
            RecoverySegmentInput(
                question_number="1b",
                text="1=d, 2=c, 3=b",
                language="en",
                legibility="clear",
                has_math=False,
            )
        ]
        segment_dicts = [segment.model_dump() for segment in segments]
        signature = _sign_preview(
            submission.id,
            1,
            ["1b"],
            segment_dicts,
        )

        first = confirm_page_recovery(
            submission.id,
            1,
            ["1b"],
            segments,
            signature,
            self.db,
        )
        second = confirm_page_recovery(
            submission.id,
            1,
            ["1b"],
            segments,
            signature,
            self.db,
        )

        self.assertEqual(first["recovery"]["created_source_count"], 1)
        self.assertEqual(second["recovery"]["created_source_count"], 0)
        self.assertEqual(self.db.query(AnswerSource).count(), 1)
        recovered = self.db.query(Answer).filter(Answer.question_id == question.id).one()
        self.assertEqual(recovered.raw_ocr_text, "1=d, 2=c, 3=b")

    def test_page_recovery_rejects_tampered_preview(self):
        submission = Submission(
            id="tamper-submission",
            institution_id="institution-1",
            exam_id="tamper-exam",
            original_file_path="not-needed.pdf",
            page_count=1,
            status="extracted",
            identity_status="unmatched_blank",
        )
        question = Question(
            id="tamper-question",
            institution_id="institution-1",
            exam_id="tamper-exam",
            question_number="1c",
            question_text="State the theorem.",
            max_score=1,
            rubric_json={"max_score": 1, "criteria": []},
            order_index=1,
            language="en",
        )
        self.db.add_all([submission, question])
        self.db.commit()
        segments = [RecoverySegmentInput(question_number="1c", text="Changed text")]
        with self.assertRaisesRegex(ValueError, "changed or expired"):
            confirm_page_recovery(
                submission.id,
                0,
                ["1c"],
                segments,
                "0" * 64,
                self.db,
            )


if __name__ == "__main__":
    unittest.main()
