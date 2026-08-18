import os
import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


os.environ.setdefault("GEMINI_API_KEY", "test-key-not-used")

from database import Base  # noqa: E402
import models  # noqa: E402,F401
from models import Answer, AnswerSource, Course, Exam, Institution, Question, Submission, User  # noqa: E402
from routers.results import update_submission_metadata  # noqa: E402
from schemas.submission_metadata_input import SubmissionMetadataUpdate  # noqa: E402
from services.extraction_review_service import (  # noqa: E402
    remove_manually_assigned_source,
    resolve_unmatched_segment,
)


class MetadataResolutionTests(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(engine)
        self.db = sessionmaker(bind=engine)()
        institution = Institution(id="institution-1", name="Effat University")
        teacher = User(
            id="teacher-1",
            institution_id=institution.id,
            email="owner@example.edu",
            hashed_password="unused",
            full_name="Workspace Owner",
            role="teacher",
        )
        course = Course(
            id="course-1",
            institution_id=institution.id,
            teacher_id=teacher.id,
            course_code="CS2071",
            title="Database Systems",
            term="Spring 2022",
        )
        exam = Exam(
            id="exam-1",
            institution_id=institution.id,
            course_id=course.id,
            title="Database Systems Midterm",
            language="en",
        )
        question = Question(
            id="question-3",
            institution_id=institution.id,
            exam_id=exam.id,
            question_number="3",
            question_text="Complete the SQL tasks.",
            max_score=10,
            rubric_json={"max_score": 10, "criteria": []},
            order_index=1,
            language="en",
        )
        submission = Submission(
            id="submission-1",
            institution_id=institution.id,
            exam_id=exam.id,
            original_file_path="unused.pdf",
            page_count=6,
            status="extracted",
            identity_status="unmatched_extracted",
            extracted_student_name="Zan Bataga",
            unmatched_segments=[{
                "question_number": "4",
                "text": "SELECT SectionNo FROM SECTION;",
                "legibility": "clear",
                "has_math": False,
            }],
        )
        self.db.add_all([institution, teacher, course, exam, question, submission])
        self.db.commit()

    def tearDown(self):
        self.db.close()

    def test_metadata_separates_student_and_instructor(self):
        report = update_submission_metadata(
            "submission-1",
            SubmissionMetadataUpdate(
                student_name="Leen Sharab",
                student_number="S21107195",
                instructor_name="Zain Balfagih",
            ),
            self.db,
        )

        self.assertEqual(report["submission"]["extracted_student_name"], "Leen Sharab")
        self.assertEqual(report["submission"]["instructor_name"], "Zain Balfagih")

    def test_unmatched_segment_can_be_assigned_with_source_page(self):
        report = resolve_unmatched_segment(
            submission_id="submission-1",
            unmatched_index=0,
            action="assign",
            question_id="question-3",
            page_index=5,
            db=self.db,
        )

        answer = self.db.query(Answer).filter(Answer.question_id == "question-3").one()
        source = self.db.query(AnswerSource).filter(AnswerSource.answer_id == answer.id).one()
        self.assertEqual(answer.raw_ocr_text, "SELECT SectionNo FROM SECTION;")
        self.assertEqual(source.page_index, 5)
        self.assertEqual(report["readiness"]["unmatched_segment_count"], 0)

    def test_manually_assigned_noise_can_be_removed(self):
        resolve_unmatched_segment(
            submission_id="submission-1",
            unmatched_index=0,
            action="assign",
            question_id="question-3",
            page_index=5,
            db=self.db,
        )
        source = self.db.query(AnswerSource).one()

        report = remove_manually_assigned_source(source.id, self.db)

        self.assertEqual(self.db.query(AnswerSource).count(), 0)
        self.assertEqual(self.db.query(Answer).count(), 0)
        self.assertEqual(report["readiness"]["mapped_answer_count"], 0)


if __name__ == "__main__":
    unittest.main()
