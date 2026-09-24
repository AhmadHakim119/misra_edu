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
    Question,
    ReviewLabel,
    RubricVersion,
    Submission,
    User,
)
from routers.evaluation import get_evaluation_report  # noqa: E402
from routers.rubric_versions import (  # noqa: E402
    approve_draft_rubric_version,
    create_draft_rubric_version,
    get_active_rubric,
    list_rubric_versions,
    suggest_existing_question_rubric_version,
    update_draft_rubric_version,
)
from schemas.rubric_input import (  # noqa: E402
    ExistingQuestionRubricSuggestionRequest,
    RubricVersionApprovalRequest,
    RubricVersionCreateRequest,
    RubricVersionUpdateRequest,
)
from services.rubric_service import build_rubric  # noqa: E402
from services.rubric_version_service import create_rubric_version  # noqa: E402


class TenantContractTests(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(engine)
        self.db = sessionmaker(bind=engine)()
        self.user_one = User(
            id="teacher-one",
            institution_id="institution-one",
            email="one@example.edu",
            hashed_password="unused",
            full_name="Teacher One",
            role="teacher",
        )
        self.user_two = User(
            id="teacher-two",
            institution_id="institution-two",
            email="two@example.edu",
            hashed_password="unused",
            full_name="Teacher Two",
            role="teacher",
        )
        self.exam_one = Exam(
            id="exam-one",
            institution_id="institution-one",
            course_id="course-one",
            title="Institution One Exam",
            language="en",
        )
        self.exam_two = Exam(
            id="exam-two",
            institution_id="institution-two",
            course_id="course-two",
            title="Institution Two Exam",
            language="en",
        )
        self.rubric = build_rubric(
            max_score=2,
            grading_approach="balanced",
            criteria=[{
                "title": "Complete response",
                "description": "Provides a complete response.",
                "points": 2,
                "partial_credit_allowed": True,
            }],
        ).model_dump()
        self.question_one = self._question(
            "question-one", "institution-one", "exam-one"
        )
        self.question_two = self._question(
            "question-two", "institution-two", "exam-two"
        )
        self.db.add_all([
            self.user_one,
            self.user_two,
            self.exam_one,
            self.exam_two,
            self.question_one,
            self.question_two,
        ])
        self.db.commit()

    def tearDown(self):
        self.db.close()

    def _question(self, question_id, institution_id, exam_id):
        return Question(
            id=question_id,
            institution_id=institution_id,
            exam_id=exam_id,
            question_number="1",
            question_text="Synthetic question",
            max_score=2,
            rubric_json=self.rubric,
            order_index=1,
            language="en",
        )

    def _add_evaluation_label(self, *, suffix, institution_id, exam_id, question):
        submission = Submission(
            id=f"submission-{suffix}",
            institution_id=institution_id,
            exam_id=exam_id,
            original_file_path=f"{suffix}.pdf",
            page_count=1,
            status="graded",
            identity_status="unmatched_blank",
        )
        answer = Answer(
            id=f"answer-{suffix}",
            institution_id=institution_id,
            submission_id=submission.id,
            question_id=question.id,
            raw_ocr_text="Synthetic answer",
            score=2,
            max_score=2,
            final_confidence=90,
            needs_review=False,
        )
        label = ReviewLabel(
            id=f"label-{suffix}",
            answer_id=answer.id,
            ai_score_snapshot=2,
            human_score=2,
            was_review_warranted=False,
            label_source="instructor_review",
        )
        self.db.add_all([submission, answer, label])
        self.db.commit()
        return label

    def test_evaluation_is_scoped_to_authenticated_institution(self):
        own_label = self._add_evaluation_label(
            suffix="one",
            institution_id="institution-one",
            exam_id=self.exam_one.id,
            question=self.question_one,
        )
        self._add_evaluation_label(
            suffix="two",
            institution_id="institution-two",
            exam_id=self.exam_two.id,
            question=self.question_two,
        )

        report = get_evaluation_report(None, self.db, self.user_one)

        self.assertEqual(report["overall"]["label_count"], 1)
        self.assertEqual(report["labels"][0]["review_label_id"], own_label.id)

    def test_evaluation_hides_cross_institution_exam_ids(self):
        with self.assertRaises(HTTPException) as context:
            get_evaluation_report(self.exam_two.id, self.db, self.user_one)

        self.assertEqual(context.exception.status_code, 404)
        self.assertEqual(context.exception.detail, "Exam not found")

    def test_every_rubric_version_endpoint_hides_cross_tenant_resources(self):
        other_draft = create_rubric_version(
            question=self.question_two,
            rubric_json=self.rubric,
            source="manual",
            change_summary="Other tenant draft",
            db=self.db,
        )
        create_request = RubricVersionCreateRequest(rubric=self.rubric)
        update_request = RubricVersionUpdateRequest(rubric=self.rubric)
        suggestion_request = ExistingQuestionRubricSuggestionRequest()
        approval_request = RubricVersionApprovalRequest()

        calls = [
            lambda: get_active_rubric(
                self.question_two.id, self.db, self.user_one
            ),
            lambda: list_rubric_versions(
                self.question_two.id, self.db, self.user_one
            ),
            lambda: create_draft_rubric_version(
                self.question_two.id, create_request, self.db, self.user_one
            ),
            lambda: update_draft_rubric_version(
                other_draft.id, update_request, self.db, self.user_one
            ),
            lambda: approve_draft_rubric_version(
                other_draft.id, approval_request, self.db, self.user_one
            ),
        ]
        with patch("routers.rubric_versions.suggest_rubric") as provider:
            calls.append(lambda: suggest_existing_question_rubric_version(
                self.question_two.id,
                suggestion_request,
                self.db,
                self.user_one,
            ))
            for call in calls:
                with self.subTest(call=call):
                    with self.assertRaises(HTTPException) as context:
                        call()
                    self.assertEqual(context.exception.status_code, 404)
            provider.assert_not_called()

    def test_owned_rubric_endpoints_remain_available(self):
        created = create_draft_rubric_version(
            self.question_one.id,
            RubricVersionCreateRequest(rubric=self.rubric),
            self.db,
            self.user_one,
        )

        versions = list_rubric_versions(
            self.question_one.id, self.db, self.user_one
        )

        self.assertEqual([version.id for version in versions], [created.id])


if __name__ == "__main__":
    unittest.main()
