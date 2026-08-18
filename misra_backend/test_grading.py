from database import SessionLocal
from models import Institution, User, Course, Exam, Question, Answer
from services.grading_service import grade_answer


db = SessionLocal()

institution = Institution(
    name="Test University",
    country="Saudi Arabia"
)
db.add(institution)
db.commit()
db.refresh(institution)

teacher = User(
    institution_id=institution.id,
    email="test.teacher@example.com",
    hashed_password="not_a_real_hash_for_testing",
    full_name="Test Teacher",
    role="teacher"
)
db.add(teacher)
db.commit()
db.refresh(teacher)

course = Course(
    institution_id=institution.id,
    teacher_id=teacher.id,
    course_code="PHYS101",
    title="Physics I",
    term="Spring 2026"
)
db.add(course)
db.commit()
db.refresh(course)

exam = Exam(
    institution_id=institution.id,
    course_id=course.id,
    title="Class Assignment #1",
    language="en"
)
db.add(exam)
db.commit()
db.refresh(exam)

question = Question(
    institution_id=institution.id,
    exam_id=exam.id,
    question_number="3a",
    question_text="Calculate the work you do on the pumpkin as you lift it from the ground.",
    max_score=1.0,
    rubric_json={
        "max_score": 1.0,
        "criteria": [
            {
                "id": "correct_formula",
                "description": "Uses the correct work formula (W = m·g·h)",
                "points": 0.5,
                "partial_credit_allowed": True
            },
            {
                "id": "correct_final_answer",
                "description": "Final numeric answer matches expected value (37.6 J)",
                "points": 0.5,
                "partial_credit_allowed": False
            }
        ],
        "acceptable_answers": ["37.6 J", "37.6"],
        "notes": None
    },
    order_index=1,
    language="en"
)
db.add(question)
db.commit()
db.refresh(question)

answer = Answer(
    institution_id=institution.id,
    submission_id=None,  # we don't have a real Submission yet, but this FK is required — see note below
    question_id=question.id,
    raw_ocr_text="3.2 kg • 9.80 m/s^2 • 1.2 m • 1 = 37.6 J"
)

from models import Submission

submission = Submission(
    institution_id=institution.id,
    exam_id=exam.id,
    original_file_path="test_image.jpg",
    status="extracted"
)
db.add(submission)
db.commit()
db.refresh(submission)

answer = Answer(
    institution_id=institution.id,
    submission_id=submission.id,
    question_id=question.id,
    raw_ocr_text="3.2 kg • 9.80 m/s^2 • 1.2 m • 1 = 37.6 J"
)
db.add(answer)
db.commit()
db.refresh(answer)

result, _, _, _, _, _ = grade_answer(answer.id, db)
print(result.model_dump_json(indent=2))

db.delete(answer)
db.commit()

db.delete(submission)
db.commit()

db.delete(question)
db.commit()

db.delete(exam)
db.commit()

db.delete(course)
db.commit()

db.delete(teacher)
db.commit()

db.delete(institution)
db.commit()

db.close()
