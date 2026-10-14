import asyncio
import os
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

from fastapi import FastAPI, HTTPException, Response
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


os.environ.setdefault("GEMINI_API_KEY", "test-key-not-used")

from database import Base, get_db  # noqa: E402
import models  # noqa: E402,F401
from models import Answer, AnswerSource, Question, Batch, Course, Exam, Institution, ProcessingJob, Submission, User  # noqa: E402
from routers.batches import get_batch_status  # noqa: E402
from routers.exams import promote_unmatched_segments  # noqa: E402
from routers.identity_routes import list_unresolved_identities  # noqa: E402
from routers.ocr import router as ocr_router  # noqa: E402
from routers.questions import list_exam_questions  # noqa: E402
from routers.results import get_extraction_review, get_results, get_submission_page, get_source_locations, list_submissions, reprocess_extraction, router as results_router  # noqa: E402


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
        self._assert_not_found(
            lambda: get_source_locations("submission-b", Response(), 0, self.db, self.teacher_a)
        )

    def test_source_locations_require_login(self):
        app = FastAPI()
        app.include_router(results_router)
        app.dependency_overrides[get_db] = lambda: self.db
        with TestClient(app) as client:
            self.assertEqual(client.get('/api/submissions/submission-b/source-locations?page_index=0').status_code, 401)

    def test_locating_already_graded_source_is_read_only(self):
        submission = self.db.get(Submission, 'submission-b')
        submission.page_count = 1
        submission.status = 'graded'
        question = Question(id='q-location', institution_id='institution-b', exam_id='exam-b',
                            question_number='1', question_text='Calculate work', max_score=2,
                            rubric_json={}, language='en', order_index=0)
        answer = Answer(id='a-location', institution_id='institution-b', submission_id=submission.id,
                        question_id=question.id, raw_ocr_text='W = 400 J', score=2, max_score=2,
                        grading_raw_response={'historical_box': {'y': .6}}, review_status='approved')
        source = AnswerSource(id='s-location', answer_id=answer.id, page_index=0, segment_index=0,
                              extracted_text='W = 400 J', ocr_segment={'bounding_box': {'y': .6}})
        self.db.add_all([question, answer, source])
        self.db.commit()
        words = (600, 800, [(token, (60 + i * 20, 200, 75 + i * 20, 212))
                           for i, token in enumerate(['w', '=', '400', 'j'])])
        response = Response()
        with patch('services.source_location_service.read_page_words', return_value=words):
            result = get_source_locations(submission.id, response, 0, self.db, self.db.get(User, 'teacher-b'))
        self.assertEqual(result['sources'][source.id]['status'], 'located')
        self.assertEqual(response.headers['cache-control'], 'no-store, max-age=0')
        self.assertEqual(source.ocr_segment, {'bounding_box': {'y': .6}})
        self.assertEqual(answer.grading_raw_response, {'historical_box': {'y': .6}})
        self.assertEqual(float(answer.score), 2)
        self.assertEqual(answer.raw_ocr_text, 'W = 400 J')
        self.assertFalse(self.db.dirty)

    def test_other_institution_cannot_read_batch(self):
        self._assert_not_found(
            lambda: asyncio.run(get_batch_status("batch-b", self.db, self.teacher_a))
        )

    def test_paper_list_exposes_latest_ocr_and_grading_jobs_separately(self):
        owner = self.db.get(User, "teacher-b")
        now = datetime(2026, 9, 28, 12, 0)
        for id_, kind, status, offset in [
            ("ocr-complete", "ocr_submission", "completed", 0),
            ("old-grade", "grade_submission", "failed", 1),
            ("new-grade", "grade_submission", "queued", 2),
        ]:
            self.db.add(ProcessingJob(
                id=id_, institution_id=owner.institution_id,
                submission_id="submission-b", job_type=kind, status=status,
                created_at=now + timedelta(minutes=offset),
            ))
        # Even an inconsistent foreign-tenant job cannot leak into the response.
        self.db.add(ProcessingJob(
            id="foreign-job", institution_id=self.teacher_a.institution_id,
            submission_id="submission-b", job_type="grade_submission", status="failed",
            created_at=now + timedelta(minutes=3),
        ))
        self.db.commit()
        rows = list_submissions(None, self.db, owner)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["latest_ocr_job"]["id"], "ocr-complete")
        self.assertEqual(rows[0]["latest_grading_job"]["id"], "new-grade")
        self.assertEqual(rows[0]["latest_grading_job"]["status"], "queued")
        self.assertEqual(list_submissions(None, self.db, self.teacher_a), [])

    def test_legacy_paper_list_has_explicit_null_job_states(self):
        rows = list_submissions(None, self.db, self.db.get(User, "teacher-b"))
        self.assertIsNone(rows[0]["latest_ocr_job"])
        self.assertIsNone(rows[0]["latest_grading_job"])

    def test_ledger_summary_uses_overrides_and_excludes_external_practical(self):
        self.db.add_all([
            Question(id="paper-q",institution_id="institution-b",exam_id="exam-b",question_number="1",question_text="Work",max_score=2,order_index=0,rubric_json={}),
            Question(id="practical-q",institution_id="institution-b",exam_id="exam-b",question_number="2",question_text="External notebook",max_score=10,order_index=1,rubric_json={"policy":{"assessment_scope":"external"}}),
            Answer(id="paper-a",institution_id="institution-b",submission_id="submission-b",question_id="paper-q",score=1,max_score=2,teacher_override_score=1.5,needs_review=False),
            Answer(id="practical-a",institution_id="institution-b",submission_id="submission-b",question_id="practical-q",score=10,max_score=10,needs_review=True),
        ])
        self.db.commit()
        summary = list_submissions(None,self.db,self.db.get(User,"teacher-b"))[0]["grading_summary"]
        self.assertEqual(summary["recorded_score"],1.5)
        self.assertEqual(summary["max_score"],2)
        self.assertEqual(summary["review_count"],0)
        self.assertTrue(summary["complete"])
        self.assertEqual(summary["scope_kind"],"paper_only")

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

    def test_other_institution_cannot_reprocess_a_paper(self):
        self._assert_not_found(
            lambda: reprocess_extraction("submission-b", self.db, self.teacher_a)
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
