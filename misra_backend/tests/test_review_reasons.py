import unittest

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database import Base
from models import Answer, GradingRun, Question, ReviewLabel, Submission, User
from routers.review_resolution import resolve_review
from schemas.review_input import ReviewResolutionRequest
from services.evaluation_service import build_evaluation_report


class ReviewReasonTests(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(engine)
        self.db = sessionmaker(bind=engine)()
        self.user = User(
            id="teacher-1",
            institution_id="institution-1",
            email="teacher@example.edu",
            hashed_password="unused",
            full_name="Test Teacher",
            role="teacher",
        )
        self.question = Question(
            id="question-1",
            institution_id="institution-1",
            exam_id="exam-1",
            question_number="1",
            question_text="Synthetic question",
            max_score=3,
            rubric_json={},
            order_index=1,
            language="en",
        )
        self.submission = Submission(
            id="submission-1",
            institution_id="institution-1",
            exam_id="exam-1",
            original_file_path="synthetic.pdf",
            page_count=1,
            status="graded",
            identity_status="unmatched_blank",
        )
        self.answer = Answer(
            id="answer-1",
            institution_id="institution-1",
            submission_id=self.submission.id,
            question_id=self.question.id,
            raw_ocr_text="Synthetic answer",
            score=2,
            max_score=3,
            criteria_scores=[],
            final_confidence=70,
            needs_review=True,
            review_status="pending",
        )
        self.run = GradingRun(
            id="run-1",
            answer_id=self.answer.id,
            mode="image_text",
            model_name="test-model",
            prompt_version="test-prompt",
            ocr_text_snapshot="Synthetic answer",
            rubric_snapshot={"schema_version": 2},
            score=2,
            max_score=3,
            feedback="Synthetic feedback",
            reasoning="Synthetic reasoning",
            criteria_scores=[],
            llm_confidence=70,
            final_confidence=70,
            needs_review=True,
            response_json={},
        )
        self.db.add_all([
            self.user,
            self.question,
            self.submission,
            self.answer,
            self.run,
        ])
        self.db.commit()

    def tearDown(self):
        self.db.close()

    def test_override_requires_at_least_one_unique_valid_reason(self):
        with self.assertRaises(ValidationError):
            ReviewResolutionRequest(
                action="override",
                human_score=2.5,
                was_review_warranted=True,
            )
        with self.assertRaises(ValidationError):
            ReviewResolutionRequest(
                action="override",
                human_score=2.5,
                was_review_warranted=True,
                review_reason_codes=["minor_notation", "minor_notation"],
            )
        with self.assertRaises(ValidationError):
            ReviewResolutionRequest(
                action="approve",
                was_review_warranted=False,
                review_reason_codes=["not_a_reason"],
            )

    def test_approve_allows_no_reason(self):
        request = ReviewResolutionRequest(
            action="approve",
            was_review_warranted=False,
        )
        self.assertEqual(request.review_reason_codes, [])

    def test_client_cannot_choose_a_review_label_source(self):
        with self.assertRaises(ValidationError):
            ReviewResolutionRequest(
                action="approve",
                was_review_warranted=False,
                label_source="grade_page",
            )

    def test_approve_criterion_points_must_equal_effective_human_score(self):
        self.answer.criteria_scores = [{
            "criterion_id": "complete",
            "points_earned": 2,
            "max_points": 3,
            "feedback": "Synthetic feedback",
        }]
        self.run.criteria_scores = list(self.answer.criteria_scores)
        self.db.commit()

        with self.assertRaises(HTTPException) as context:
            resolve_review(
                self.answer.id,
                ReviewResolutionRequest(
                    action="approve",
                    grading_run_id=self.run.id,
                    was_review_warranted=False,
                    human_criteria_scores=[{
                        "criterion_id": "complete",
                        "points_earned": 1.5,
                        "max_points": 3,
                    }],
                ),
                self.db,
                self.user,
            )

        self.assertEqual(context.exception.status_code, 422)
        self.assertIn("add up", context.exception.detail)

    def test_reasons_persist_and_ocr_reason_is_not_preference_evidence(self):
        response = resolve_review(
            self.answer.id,
            ReviewResolutionRequest(
                action="override",
                grading_run_id=self.run.id,
                human_score=2.5,
                was_review_warranted=True,
                review_reason_codes=["minor_notation", "ocr_or_mapping_error"],
                review_reason_note="  OCR dropped a handwritten symbol.  ",
            ),
            self.db,
            self.user,
        )
        label = response["review_label"]
        self.assertEqual(label.review_reason_codes, ["minor_notation", "ocr_or_mapping_error"])
        self.assertEqual(label.review_reason_note, "OCR dropped a handwritten symbol.")
        self.assertEqual(label.label_source, "instructor_review")

        report = build_evaluation_report(
            self.db,
            institution_id="institution-1",
            exam_id="exam-1",
        )
        record = report["labels"][0]
        self.assertEqual(record["review_reason_codes"], ["minor_notation", "ocr_or_mapping_error"])
        self.assertEqual(record["preference_reason_codes"], ["minor_notation"])
        self.assertNotIn("ocr_or_mapping_error", record["preference_reason_codes"])

        saved = self.db.query(ReviewLabel).filter_by(grading_run_id=self.run.id).one()
        self.assertEqual(saved.review_reason_note, "OCR dropped a handwritten symbol.")

    def test_resolution_defaults_to_operational_run_and_preserves_revisions(self):
        text_run = GradingRun(
            id="run-text-primary",
            answer_id=self.answer.id,
            mode="text_only",
            model_name="test-model",
            prompt_version="test-prompt",
            ocr_text_snapshot="Synthetic answer",
            rubric_snapshot={"schema_version": 2},
            score=2.5,
            max_score=3,
            feedback="Primary feedback",
            reasoning="Primary reasoning",
            criteria_scores=[],
            llm_confidence=90,
            final_confidence=40,
            needs_review=True,
            response_json={},
        )
        self.db.add(text_run)
        self.answer.score = 2.5
        self.answer.grading_raw_response = {
            "mode": "text_only",
            "grading_run_id": text_run.id,
        }
        self.db.commit()

        first = resolve_review(
            self.answer.id,
            ReviewResolutionRequest(
                action="approve",
                was_review_warranted=True,
            ),
            self.db,
            self.user,
        )["review_label"]
        self.assertEqual(first.grading_run_id, text_run.id)
        self.assertEqual(float(first.ai_score_snapshot), 2.5)

        second = resolve_review(
            self.answer.id,
            ReviewResolutionRequest(
                action="override",
                human_score=3,
                was_review_warranted=True,
                review_reason_codes=["valid_alternative"],
            ),
            self.db,
            self.user,
        )["review_label"]
        self.assertNotEqual(second.id, first.id)
        self.assertEqual(second.supersedes_label_id, first.id)
        self.assertEqual(float(first.human_score), 2.5)
        self.assertEqual(float(second.human_score), 3)
        self.assertEqual(
            self.db.query(ReviewLabel)
            .filter(ReviewLabel.grading_run_id == text_run.id)
            .count(),
            2,
        )

        report = build_evaluation_report(
            self.db,
            institution_id="institution-1",
            exam_id="exam-1",
        )
        matching = [
            item for item in report["labels"]
            if item["grading_run_id"] == text_run.id
        ]
        self.assertEqual(len(matching), 1)
        self.assertEqual(matching[0]["human_score"], 3)


if __name__ == "__main__":
    unittest.main()
