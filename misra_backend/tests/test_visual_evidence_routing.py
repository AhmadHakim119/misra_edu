import os
import unittest
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


os.environ.setdefault("GEMINI_API_KEY", "test-key-not-used")

from database import Base  # noqa: E402
import models  # noqa: E402,F401
from models import Answer, Exam, GradingRun, Question, QuestionGradingPolicy  # noqa: E402
from schemas.grading_policy_input import QuestionGradingPolicyRequest  # noqa: E402
from services.grading_service import (  # noqa: E402
    _apply_visual_evidence_guard,
    _contains_visual_evidence_terms,
    process_grading_with_policy,
)


class VisualEvidenceRoutingTests(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(engine)
        self.db = sessionmaker(bind=engine)()
        self.exam = Exam(
            id="exam-routing",
            institution_id="institution-1",
            course_id="course-1",
            title="Database Systems",
            language="en",
        )
        self.question = Question(
            id="question-routing",
            institution_id="institution-1",
            exam_id=self.exam.id,
            question_number="1",
            question_text="Draw an EER diagram for the case study.",
            max_score=2,
            rubric_json={
                "max_score": 2,
                "criteria": [{
                    "id": "diagram",
                    "description": "Diagram uses correct cardinality notation.",
                    "points": 2,
                    "partial_credit_allowed": True,
                }],
            },
            order_index=1,
            language="en",
        )
        self.answer = Answer(
            id="answer-routing",
            institution_id="institution-1",
            submission_id="submission-1",
            question_id=self.question.id,
            raw_ocr_text="Entities and relationships",
            ocr_legibility="clear",
            final_confidence=95,
            needs_review=False,
            review_status="none",
        )
        self.db.add_all([self.exam, self.question, self.answer])
        self.db.commit()

    def tearDown(self):
        self.db.close()

    def test_public_policy_modes_are_valid(self):
        for mode in ("adaptive", "image_text_required", "text_only"):
            self.assertEqual(QuestionGradingPolicyRequest(mode=mode).mode, mode)

    def test_visual_terms_do_not_match_paragraph(self):
        self.assertFalse(_contains_visual_evidence_terms(
            "Write one paragraph.",
            {"criteria": [{"description": "Clear paragraph", "points": 1}]},
        ))
        self.assertTrue(_contains_visual_evidence_terms(
            self.question.question_text,
            self.question.rubric_json,
        ))

    def test_adaptive_routes_diagram_to_image_and_text(self):
        with patch("services.grading_service.process_grading", return_value=self.answer) as grade:
            process_grading_with_policy(self.answer.id, self.db)
        grade.assert_called_once_with(self.answer.id, self.db, mode="image_text")

    def test_text_only_policy_is_respected(self):
        self.db.add(QuestionGradingPolicy(
            question_id=self.question.id,
            mode="text_only",
            enabled=True,
        ))
        self.db.commit()
        with patch("services.grading_service.process_grading", return_value=self.answer) as grade:
            process_grading_with_policy(self.answer.id, self.db)
        grade.assert_called_once_with(self.answer.id, self.db, mode="text_only")

    def test_required_visual_policy_routes_to_image_and_text(self):
        self.db.add(QuestionGradingPolicy(
            question_id=self.question.id,
            mode="image_text_required",
            enabled=True,
        ))
        self.db.commit()
        with patch("services.grading_service.process_grading", return_value=self.answer) as grade:
            process_grading_with_policy(self.answer.id, self.db)
        grade.assert_called_once_with(self.answer.id, self.db, mode="image_text")

    def test_text_only_run_is_capped_when_visuals_are_required(self):
        self.db.add(QuestionGradingPolicy(
            question_id=self.question.id,
            mode="image_text_required",
            enabled=True,
        ))
        self.db.commit()
        run = GradingRun(
            id="run-routing",
            answer_id=self.answer.id,
            mode="text_only",
            model_name="test-model",
            prompt_version="test-prompt",
            ocr_text_snapshot="Entities and relationships",
            rubric_snapshot=self.question.rubric_json,
            score=2,
            max_score=2,
            feedback="Looks correct.",
            reasoning="Text appears correct.",
            criteria_scores=[],
            llm_confidence=95,
            final_confidence=95,
            needs_review=False,
            response_json={},
        )
        applied = _apply_visual_evidence_guard(
            self.answer,
            run,
            "text_only",
            self.db,
        )
        self.assertTrue(applied)
        self.assertEqual(self.answer.final_confidence, 40)
        self.assertTrue(self.answer.needs_review)
        self.assertEqual(self.answer.review_status, "pending")
        self.assertEqual(
            self.answer.review_reasons["code"],
            "visual_evidence_not_seen",
        )
        self.assertEqual(run.final_confidence, 40)
        self.assertTrue(run.needs_review)


if __name__ == "__main__":
    unittest.main()
