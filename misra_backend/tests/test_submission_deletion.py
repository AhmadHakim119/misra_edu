import os
from pathlib import Path
import tempfile
import unittest

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


os.environ.setdefault("GEMINI_API_KEY", "test-key-not-used")
os.environ.setdefault("DB_URL", "sqlite://")

from database import Base  # noqa: E402
from models import (  # noqa: E402
    Answer,
    AnswerSource,
    Course,
    Exam,
    Institution,
    ProcessingJob,
    Question,
    Submission,
    User,
)
from routers.results import delete_submission  # noqa: E402


class SubmissionDeletionTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)
        self.db = self.Session()
        self.paper = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
        self.paper.write(b"test paper")
        self.paper.close()

        self.institution = Institution(id="institution-delete", name="Deletion University")
        self.user = User(
            id="teacher-delete",
            institution_id=self.institution.id,
            email="delete@example.edu",
            hashed_password="unused",
            role="teacher",
        )
        self.course = Course(
            id="course-delete",
            institution_id=self.institution.id,
            teacher_id=self.user.id,
            course_code="CSDEL",
            title="Deletion",
        )
        self.exam = Exam(
            id="exam-delete",
            institution_id=self.institution.id,
            course_id=self.course.id,
            title="Deletion Test",
            language="en",
        )
        self.submission = Submission(
            id="submission-delete",
            institution_id=self.institution.id,
            exam_id=self.exam.id,
            original_file_path=self.paper.name,
            page_count=1,
            status="extracted",
        )
        self.question = Question(
            id="question-delete",
            institution_id=self.institution.id,
            exam_id=self.exam.id,
            question_number="1",
            question_text="Delete safely",
            max_score=1,
            rubric_json={"criteria": []},
            order_index=1,
        )
        self.answer = Answer(
            id="answer-delete",
            institution_id=self.institution.id,
            submission_id=self.submission.id,
            question_id=self.question.id,
            raw_ocr_text="answer",
        )
        self.source = AnswerSource(
            id="source-delete",
            answer_id=self.answer.id,
            page_index=0,
            segment_index=0,
            extracted_text="answer",
            has_math=False,
            ocr_segment={"text": "answer"},
        )
        self.db.add_all(
            [
                self.institution,
                self.user,
                self.course,
                self.exam,
                self.submission,
                self.question,
                self.answer,
                self.source,
            ]
        )
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()
        Path(self.paper.name).unlink(missing_ok=True)

    def test_delete_removes_submission_children_job_and_file(self):
        self.db.add(
            ProcessingJob(
                id="job-delete",
                institution_id=self.institution.id,
                requested_by=self.user.id,
                submission_id=self.submission.id,
                job_type="ocr_submission",
                status="failed",
                progress_total=1,
                max_attempts=1,
                payload={},
            )
        )
        self.db.commit()

        result = delete_submission(self.submission.id, self.db, self.user)

        self.assertTrue(result["deleted"])
        self.assertTrue(result["file_removed"])
        self.assertEqual(self.db.query(Submission).count(), 0)
        self.assertEqual(self.db.query(Answer).count(), 0)
        self.assertEqual(self.db.query(AnswerSource).count(), 0)
        self.assertEqual(self.db.query(ProcessingJob).count(), 0)
        self.assertFalse(Path(self.paper.name).exists())

    def test_active_processing_job_blocks_deletion(self):
        self.db.add(
            ProcessingJob(
                id="job-active",
                institution_id=self.institution.id,
                requested_by=self.user.id,
                submission_id=self.submission.id,
                job_type="ocr_submission",
                status="processing",
                progress_total=1,
                max_attempts=1,
                payload={},
            )
        )
        self.db.commit()

        with self.assertRaises(HTTPException) as context:
            delete_submission(self.submission.id, self.db, self.user)

        self.assertEqual(context.exception.status_code, 409)
        self.assertEqual(self.db.query(Submission).count(), 1)
        self.assertTrue(Path(self.paper.name).exists())


if __name__ == "__main__":
    unittest.main()
