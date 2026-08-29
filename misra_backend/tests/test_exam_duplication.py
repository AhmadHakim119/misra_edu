import unittest

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database import Base
import models  # noqa: F401
from models import (
    Course,
    Exam,
    Institution,
    Question,
    QuestionGradingPolicy,
    RubricVersion,
    Submission,
    User,
)
from routers.exams import duplicate_exam
from schemas.exam_input import ExamDuplicateRequest


class ExamDuplicationTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine)()
        self.user = User(
            id="teacher-a",
            institution_id="institution-a",
            email="teacher@example.edu",
            hashed_password="unused",
            full_name="Test Teacher",
            role="teacher",
        )
        other_user = User(
            id="teacher-b",
            institution_id="institution-b",
            email="other@example.edu",
            hashed_password="unused",
            full_name="Other Teacher",
            role="teacher",
        )
        self.db.add_all([
            Institution(id="institution-a", name="University A"),
            Institution(id="institution-b", name="University B"),
            self.user,
            other_user,
        ])
        self.db.flush()
        course = Course(
            id="course-a",
            institution_id="institution-a",
            teacher_id=self.user.id,
            course_code="CS2071",
            title="Database Systems",
        )
        exam = Exam(
            id="exam-a",
            institution_id="institution-a",
            course_id=course.id,
            title="Midterm",
            language="en",
        )
        self.db.add_all([course, exam])
        self.db.flush()
        rubric = {
            "schema_version": 2,
            "max_score": 4,
            "criteria": [{"id": "correct", "title": "Correct", "description": "Correct answer", "points": 4}],
            "policy": {"grading_approach": "lenient"},
        }
        question = Question(
            id="question-a",
            institution_id="institution-a",
            exam_id=exam.id,
            question_number="1",
            question_text="Write the query.",
            max_score=4,
            rubric_json=rubric,
            order_index=1,
            language="en",
        )
        self.db.add(question)
        self.db.flush()
        version = RubricVersion(
            id="rubric-a",
            question_id=question.id,
            version_number=1,
            schema_version=2,
            rubric_json=rubric,
            grading_approach="lenient",
            source="manual",
            status="approved",
            created_by=self.user.id,
            approved_by=self.user.id,
        )
        self.db.add(version)
        self.db.flush()
        question.active_rubric_version_id = version.id
        self.db.add(QuestionGradingPolicy(
            question_id=question.id,
            mode="image_text_required",
            audit_rate=0.25,
            min_validated_samples=5,
            material_absolute_points=0.5,
            material_relative_ratio=0.2,
            enabled=True,
        ))
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_duplicates_structure_without_student_records(self):
        result = duplicate_exam(
            "exam-a",
            ExamDuplicateRequest(title="Midterm — Fall 2026"),
            self.db,
            self.user,
        )

        duplicate = result["exam"]
        self.assertEqual(result["question_count"], 1)
        self.assertEqual(result["rubric_count"], 1)
        self.assertEqual(result["policy_count"], 1)
        self.assertEqual(duplicate.course_id, "course-a")
        self.assertEqual(self.db.query(Submission).filter(Submission.exam_id == duplicate.id).count(), 0)

        question = self.db.query(Question).filter(Question.exam_id == duplicate.id).one()
        self.assertNotEqual(question.id, "question-a")
        self.assertIsNotNone(question.active_rubric_version_id)
        version = self.db.query(RubricVersion).filter(RubricVersion.question_id == question.id).one()
        self.assertEqual(version.source, "imported")
        self.assertEqual(version.status, "approved")
        policy = self.db.query(QuestionGradingPolicy).filter(QuestionGradingPolicy.question_id == question.id).one()
        self.assertEqual(policy.mode, "image_text_required")

    def test_other_institution_cannot_duplicate_assessment(self):
        other_user = self.db.query(User).filter(User.id == "teacher-b").one()
        with self.assertRaises(HTTPException) as context:
            duplicate_exam(
                "exam-a",
                ExamDuplicateRequest(title="Unauthorized copy"),
                self.db,
                other_user,
            )
        self.assertEqual(context.exception.status_code, 404)


if __name__ == "__main__":
    unittest.main()
