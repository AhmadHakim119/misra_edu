"""New authoring draft creation preserves old clients and grading authority."""
import asyncio
import unittest

from fastapi import HTTPException
from models import RubricVersion
from routers.questions import create_question
from schemas.rubric_input import QuestionCreateRequest
from services.rubric_version_service import get_effective_rubric, approve_rubric_version
from tests import test_course_materials as fixtures


class QuestionDraftCreationTests(unittest.TestCase):
    setUp = fixtures.CourseMaterialTests.setUp
    tearDown = fixtures.CourseMaterialTests.tearDown

    def payload(self, **kwargs):
        return QuestionCreateRequest(
            question_number="2", question_text="Calculate the work.", max_score=2,
            criteria=[{"id": "formula", "title": "Work formula", "description": "Use W = Fd", "points": 2}],
            **kwargs,
        )

    def test_saved_draft_cannot_grade_until_approved(self):
        question = asyncio.run(create_question("e", self.payload(approve_initial_rubric=False), self.db, self.user))
        version = self.db.query(RubricVersion).filter_by(question_id=question.id).one()
        self.assertEqual(version.status, "draft")
        self.assertIsNone(question.active_rubric_version_id)
        self.assertIsNone(version.approved_at)
        self.assertEqual(version.created_by, self.user.id)
        with self.assertRaisesRegex(ValueError, "no approved rubric"):
            get_effective_rubric(question, self.db)
        approve_rubric_version(version=version, db=self.db, approved_by=self.user.id)
        self.assertEqual(get_effective_rubric(question, self.db)[1], version.id)

    def test_legacy_client_still_creates_approved_manual_rubric(self):
        question = asyncio.run(create_question("e", self.payload(), self.db, self.user))
        version = self.db.query(RubricVersion).filter_by(question_id=question.id).one()
        self.assertEqual(version.status, "approved")
        self.assertEqual(question.active_rubric_version_id, version.id)
        self.assertEqual(version.approved_by, self.user.id)

    def test_cross_institution_creation_still_forbidden(self):
        with self.assertRaises(HTTPException) as failure:
            asyncio.run(create_question("e", self.payload(approve_initial_rubric=False), self.db, self.other))
        self.assertEqual(failure.exception.status_code, 404)

    def test_existing_approved_question_unchanged(self):
        previous = self.q.active_rubric_version_id
        asyncio.run(create_question("e", self.payload(approve_initial_rubric=False), self.db, self.user))
        self.db.refresh(self.q)
        self.assertEqual(self.q.active_rubric_version_id, previous)
