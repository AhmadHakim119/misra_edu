import os
import unittest

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


os.environ.setdefault("GEMINI_API_KEY", "test-key-not-used")

from database import Base  # noqa: E402
import models  # noqa: E402,F401
from models import Course, Institution, User  # noqa: E402
from routers.exams import create_course  # noqa: E402
from schemas.course_input import CourseCreateRequest  # noqa: E402


class CourseCreationTests(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(engine)
        self.db = sessionmaker(bind=engine)()
        self.institution = Institution(id="institution-1", name="Effat University")
        self.teacher = User(
            id="teacher-1",
            institution_id=self.institution.id,
            email="teacher@example.edu",
            hashed_password="not-used",
            full_name="Test Teacher",
            role="teacher",
        )
        self.owner = Course(
            id="owner-course",
            institution_id=self.institution.id,
            teacher_id=self.teacher.id,
            course_code="MATH203",
            title="Discrete Mathematics",
            term="Fall 2024",
        )
        self.db.add_all([self.institution, self.teacher, self.owner])
        self.db.commit()

    def tearDown(self):
        self.db.close()

    def payload(self):
        return CourseCreateRequest(
            owner_course_id=self.owner.id,
            course_code="CS2071",
            title="Database Systems",
            term="Spring 2022",
            instructor_name="Zain Balfagih",
        )

    def test_course_inherits_persisted_ownership(self):
        course = create_course(self.payload(), self.db)

        self.assertEqual(course.institution_id, self.institution.id)
        self.assertEqual(course.teacher_id, self.teacher.id)
        self.assertEqual(course.course_code, "CS2071")
        self.assertEqual(course.term, "Spring 2022")
        self.assertEqual(course.instructor_name, "Zain Balfagih")

    def test_duplicate_course_is_rejected(self):
        create_course(self.payload(), self.db)

        with self.assertRaises(HTTPException) as raised:
            create_course(self.payload(), self.db)

        self.assertEqual(raised.exception.status_code, 409)


if __name__ == "__main__":
    unittest.main()
