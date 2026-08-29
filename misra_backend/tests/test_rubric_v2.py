import os
import unittest
from unittest.mock import patch

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


os.environ.setdefault("GEMINI_API_KEY", "test-key-not-used")

from database import Base  # noqa: E402
import models  # noqa: E402,F401
from models import (  # noqa: E402
    Answer,
    Exam,
    GradingRun,
    Question,
    ReviewLabel,
    Submission,
    User,
)
from routers.rubric_versions import (  # noqa: E402
    suggest_existing_question_rubric_version,
)
from routers.review_resolution import resolve_review  # noqa: E402
from schemas.review_input import ReviewResolutionRequest  # noqa: E402
from schemas.rubric_input import (  # noqa: E402
    ExistingQuestionRubricSuggestionRequest,
)
from schemas.rubric_v2 import RubricPolicy, RubricV2  # noqa: E402
from services.rubric_service import build_rubric  # noqa: E402
from services.grading_service import (  # noqa: E402
    CriterionScore,
    GradingResult,
    _validate_grading_against_rubric,
)
from services.rubric_version_service import (  # noqa: E402
    approve_rubric_version,
    create_rubric_version,
    get_effective_rubric,
    update_rubric_version,
)
from services.review_state_service import resolved_review_status  # noqa: E402


class RubricV2Tests(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(engine)
        self.db = sessionmaker(bind=engine)()

    def tearDown(self):
        self.db.close()

    def make_rubric(self, approach="balanced"):
        return build_rubric(
            max_score=2,
            grading_approach=approach,
            criteria=[
                {
                    "title": "Method",
                    "description": "Uses a valid method",
                    "points": 1,
                    "partial_credit_allowed": True,
                },
                {
                    "title": "Conclusion",
                    "description": "Obtains the correct conclusion",
                    "points": 1,
                    "partial_credit_allowed": False,
                },
            ],
        )

    def test_preset_is_explicit_and_ids_are_stable(self):
        rubric = self.make_rubric("lenient")
        self.assertEqual(rubric.schema_version, 2)
        self.assertEqual(rubric.policy.grading_approach, "lenient")
        self.assertEqual(rubric.policy.method_credit, "full_if_valid")
        self.assertNotEqual(rubric.criteria[0].id, rubric.criteria[1].id)
        self.assertEqual(rubric.criteria[1].scoring_type, "binary")

    def test_points_must_sum_to_max_score(self):
        data = self.make_rubric().model_dump()
        data["max_score"] = 3
        with self.assertRaises(ValueError):
            RubricV2(**data)

    def test_custom_policy_requires_instructions(self):
        with self.assertRaises(ValueError):
            RubricPolicy(grading_approach="custom")

    def test_draft_edit_and_approval_lifecycle(self):
        legacy = {
            "max_score": 2,
            "criteria": [
                {
                    "id": "legacy",
                    "description": "Legacy criterion",
                    "points": 2,
                    "partial_credit_allowed": True,
                }
            ],
        }
        question = Question(
            id="question-1",
            institution_id="institution-1",
            exam_id="exam-1",
            question_number="1",
            question_text="Test question",
            max_score=2,
            rubric_json=legacy,
            order_index=1,
            language="en",
        )
        self.db.add(question)
        self.db.commit()

        rubric = self.make_rubric()
        draft = create_rubric_version(
            question=question,
            rubric_json=rubric.model_dump(),
            source="manual",
            change_summary="Initial draft",
            db=self.db,
        )
        self.assertEqual(draft.status, "draft")

        edited = rubric.model_copy(deep=True)
        edited.notes = "Instructor verified."
        update_rubric_version(
            version=draft,
            rubric_json=edited.model_dump(),
            change_summary="Added instructor note",
            db=self.db,
        )
        approved, regrade_required = approve_rubric_version(
            version=draft,
            db=self.db,
        )

        self.assertEqual(approved.status, "approved")
        self.assertFalse(regrade_required)
        self.assertEqual(question.active_rubric_version_id, approved.id)
        effective, version_id = get_effective_rubric(question, self.db)
        self.assertEqual(version_id, approved.id)
        self.assertEqual(effective["notes"], "Instructor verified.")

    def test_grading_response_must_match_every_criterion(self):
        rubric = self.make_rubric()
        valid = GradingResult(
            score=2,
            max_score=2,
            feedback="Good work.",
            reasoning="Both criteria were satisfied.",
            criteria_scores=[
                CriterionScore(
                    criterion_id=rubric.criteria[0].id,
                    max_points=1,
                    points_earned=1,
                    feedback="Valid method.",
                ),
                CriterionScore(
                    criterion_id=rubric.criteria[1].id,
                    max_points=1,
                    points_earned=1,
                    feedback="Correct conclusion.",
                ),
            ],
            llm_confidence=90,
        )
        _validate_grading_against_rubric(valid, rubric.model_dump())

        invalid = valid.model_copy(deep=True)
        invalid.criteria_scores.pop()
        with self.assertRaises(ValueError):
            _validate_grading_against_rubric(invalid, rubric.model_dump())

    def test_ai_suggestion_for_existing_question_creates_inactive_draft(self):
        exam = Exam(
            id="exam-ai-draft",
            institution_id="institution-1",
            course_id="course-1",
            title="Discrete Mathematics Final",
            language="en",
        )
        question = Question(
            id="question-ai-draft",
            institution_id="institution-1",
            exam_id=exam.id,
            question_number="5d",
            question_text="Determine whether the two graphs are isomorphic.",
            max_score=2,
            rubric_json={
                "max_score": 2,
                "criteria": [
                    {
                        "id": "q_5d_complete",
                        "description": "Complete answer",
                        "points": 2,
                        "partial_credit_allowed": True,
                    }
                ],
            },
            order_index=1,
            language="en",
        )
        self.db.add_all([exam, question])
        self.db.commit()

        suggested = self.make_rubric()
        with patch(
            "routers.rubric_versions.suggest_rubric",
            return_value=suggested,
        ) as mocked_suggestion:
            response = suggest_existing_question_rubric_version(
                question.id,
                ExistingQuestionRubricSuggestionRequest(
                    answer_key="The adjacency matrices match under relabeling.",
                    grading_approach="balanced",
                ),
                self.db,
            )

        version = response["rubric_version"]
        self.assertEqual(version.question_id, question.id)
        self.assertEqual(version.version_number, 1)
        self.assertEqual(version.source, "ai")
        self.assertEqual(version.status, "draft")
        self.assertIsNone(question.active_rubric_version_id)
        self.assertEqual(
            mocked_suggestion.call_args.kwargs["current_rubric"],
            question.rubric_json,
        )

    def test_human_override_survives_ai_regrade_state_recovery(self):
        class PreviouslyReviewedAnswer:
            teacher_override_score = 3
            review_status = "none"
            reviewed_at = object()

        self.assertEqual(
            resolved_review_status(PreviouslyReviewedAnswer()),
            "overridden",
        )

    def test_one_answer_can_retain_labels_for_separate_runs(self):
        submission = Submission(
            id="submission-1",
            institution_id="institution-1",
            exam_id="exam-1",
            original_file_path="test.pdf",
            page_count=1,
            status="graded",
            identity_status="unmatched_blank",
        )
        user = User(
            id="teacher-1",
            institution_id="institution-1",
            email="teacher@example.edu",
            hashed_password="unused",
            full_name="Test Teacher",
            role="teacher",
        )
        answer = Answer(
            id="answer-1",
            institution_id="institution-1",
            submission_id="submission-1",
            question_id="question-1",
            score=3,
            max_score=3,
            raw_ocr_text="Correct answer",
            criteria_scores=[],
            final_confidence=100,
            needs_review=False,
        )
        run = GradingRun(
            id="run-v2",
            answer_id=answer.id,
            mode="image_text",
            model_name="test-model",
            prompt_version="v2-rubric-policy",
            ocr_text_snapshot="Correct answer",
            rubric_snapshot={"schema_version": 2, "max_score": 3, "criteria": []},
            score=3,
            max_score=3,
            feedback="Correct.",
            reasoning="All criteria met.",
            criteria_scores=[],
            llm_confidence=100,
            final_confidence=100,
            needs_review=False,
            response_json={},
        )
        legacy_label = ReviewLabel(
            id="legacy-label",
            answer_id=answer.id,
            ai_score_snapshot=0.75,
            human_score=3,
            was_review_warranted=True,
        )
        self.db.add_all([submission, user, answer, run, legacy_label])
        self.db.commit()

        resolve_review(
            answer.id,
            ReviewResolutionRequest(
                action="approve",
                grading_run_id=run.id,
                was_review_warranted=False,
                reviewer_notes="V2 result agrees with the instructor.",
            ),
            self.db,
            user,
        )

        labels = (
            self.db.query(ReviewLabel)
            .filter(ReviewLabel.answer_id == answer.id)
            .all()
        )
        self.assertEqual(len(labels), 2)
        self.assertEqual(
            next(label for label in labels if label.grading_run_id == run.id).human_score,
            3,
        )
        self.assertEqual(
            next(label for label in labels if label.grading_run_id == run.id).labeled_by,
            user.id,
        )

        resolve_review(
            answer.id,
            ReviewResolutionRequest(
                action="override",
                grading_run_id=run.id,
                human_score=2.5,
                was_review_warranted=True,
                reviewer_notes="Instructor adjusted the recorded grade.",
                label_source="grade_page",
            ),
            self.db,
            user,
        )
        self.db.refresh(answer)
        self.assertEqual(float(answer.teacher_override_score), 2.5)
        self.assertEqual(answer.review_status, "overridden")

        other_user = User(
            id="teacher-2",
            institution_id="institution-2",
            email="other@example.edu",
            hashed_password="unused",
            full_name="Other Teacher",
            role="teacher",
        )
        with self.assertRaises(HTTPException) as context:
            resolve_review(
                answer.id,
                ReviewResolutionRequest(
                    action="approve",
                    grading_run_id=run.id,
                    was_review_warranted=False,
                ),
                self.db,
                other_user,
            )
        self.assertEqual(context.exception.status_code, 404)


if __name__ == "__main__":
    unittest.main()
