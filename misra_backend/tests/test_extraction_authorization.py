import asyncio
import os
import unittest

from fastapi import FastAPI, HTTPException, Response
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


os.environ.setdefault("GEMINI_API_KEY", "test-key-not-used")

from database import Base, get_db  # noqa: E402
import models  # noqa: E402,F401
from models import Batch, Course, Exam, Institution, Submission, User  # noqa: E402
from routers.batches import get_batch_status  # noqa: E402
from routers.exams import promote_unmatched_segments  # noqa: E402
from routers.identity_routes import list_unresolved_identities  # noqa: E402
from routers.ocr import router as ocr_router  # noqa: E402
from routers.questions import list_exam_questions  # noqa: E402
from routers.results import get_extraction_review, get_results, get_submission_page  # noqa: E402


class ExtractionAuthorizationTests(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(engine)
        self.db = sessionmaker(bind=engine)()
        institution_a = Institution(id="institution-a", name="Institution A")
        institution_b = Institution(id="institution-b", name="Institution B")
        self.teacher_a = User(
            id="teacher-a",
            institution_id=institution_a.id,
            email="a@example.edu",
            hashed_password="unused",
            role="teacher",
        )
        teacher_b = User(
            id="teacher-b",
            institution_id=institution_b.id,
            email="b@example.edu",
            hashed_password="unused",
            role="teacher",
        )
        course_b = Course(
            id="course-b",
            institution_id=institution_b.id,
            teacher_id=teacher_b.id,
            course_code="SEC200",
            title="Private Course",
        )
        exam_b = Exam(
            id="exam-b",
            institution_id=institution_b.id,
            course_id=course_b.id,
            title="Private Exam",
            language="en",
        )
        batch_b = Batch(
            id="batch-b",
            institution_id=institution_b.id,
            exam_id=exam_b.id,
            total_count=1,
            status="queued",
        )
        submission_b = Submission(
            id="submission-b",
            institution_id=institution_b.id,
            exam_id=exam_b.id,
            batch_id=batch_b.id,
            original_file_path="private.pdf",
            status="uploaded",
        )
        self.db.add_all(
            [
                institution_a,
                institution_b,
                self.teacher_a,
                teacher_b,
                course_b,
                exam_b,
                batch_b,
                submission_b,
            ]
        )
        self.db.commit()

    def tearDown(self):
        self.db.close()

    def _assert_not_found(self, callable_):
        with self.assertRaises(HTTPException) as context:
            callable_()
        self.assertEqual(context.exception.status_code, 404)

    def test_other_institution_cannot_read_submission_results(self):
        self._assert_not_found(
            lambda: asyncio.run(get_results("submission-b", self.db, self.teacher_a))
        )
        self._assert_not_found(
            lambda: get_extraction_review(
                "submission-b",
                Response(),
                self.db,
                self.teacher_a,
            )
        )
        self._assert_not_found(
            lambda: get_submission_page("submission-b", 0, self.db, self.teacher_a)
        )

    def test_other_institution_cannot_read_batch(self):
        self._assert_not_found(
            lambda: asyncio.run(get_batch_status("batch-b", self.db, self.teacher_a))
        )

    def test_other_institution_cannot_list_exam_questions_or_identities(self):
        self._assert_not_found(
            lambda: list_exam_questions("exam-b", self.db, self.teacher_a)
        )
        self._assert_not_found(
            lambda: list_unresolved_identities("exam-b", self.db, self.teacher_a)
        )

    def test_other_institution_cannot_promote_unmatched_segments(self):
        self._assert_not_found(
            lambda: promote_unmatched_segments("submission-b", self.db, self.teacher_a)
        )

    def test_raw_ocr_endpoint_requires_authentication_even_when_mounted_alone(self):
        def override_db():
            yield self.db

        app = FastAPI()
        app.include_router(ocr_router)
        app.dependency_overrides[get_db] = override_db
        response = TestClient(app).post(
            "/api/ocr",
            files={"file": ("page.png", b"not-used-before-auth", "image/png")},
        )

        self.assertEqual(response.status_code, 401)


if __name__ == "__main__":
    unittest.main()
