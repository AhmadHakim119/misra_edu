from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from database import get_db
from models.submission import Submission
from models.student import Student
from schemas.identity import IdentityResolutionRequest

router = APIRouter(prefix="/api", tags=["identity"])

@router.get("/exams/{exam_id}/unresolved-identities")
def list_unresolved_identities(exam_id: str, db: Session = Depends(get_db)):
    submissions = (
        db.query(Submission)
        .filter(Submission.exam_id == exam_id)
        .filter(Submission.identity_status != "matched")
        .filter(Submission.status != "error")
        .all()
    )
    return submissions


@router.post("/submissions/{submission_id}/resolve-identity")
def resolve_identity(
    submission_id: str,
    request: IdentityResolutionRequest,
    db: Session = Depends(get_db),
):
    submission = (
        db.query(Submission)
        .filter(Submission.id == submission_id)
        .first()
    )

    if submission is None:
        raise HTTPException(status_code=404, detail="Submission not found")

    # -------------------------
    # Match an existing student
    # -------------------------
    if request.action == "match_existing":

        if not request.student_id:
            raise HTTPException(status_code=400, detail="student_id is required.")

        student = (
            db.query(Student)
            .filter(Student.id == request.student_id)
            .first()
        )

        if student is None:
            raise HTTPException(status_code=404, detail="Student not found.")

        # Tenant isolation: a submission can only match a student from the same institution
        if student.institution_id != submission.institution_id:
            raise HTTPException(
                status_code=400,
                detail="Student does not belong to this submission's institution."
            )

        submission.student_id = student.id
        submission.identity_status = "matched"

    # -------------------------
    # Create a new student
    # -------------------------
    elif request.action == "create_new":

        if not request.full_name:
            raise HTTPException(status_code=400, detail="full_name is required.")

        new_student = Student(
            institution_id=submission.institution_id,
            full_name=request.full_name,
            student_number=request.student_number,
        )

        db.add(new_student)
        db.flush()  # generates new_student.id

        submission.student_id = new_student.id
        submission.identity_status = "matched"

    # -------------------------
    # Leave unidentified
    # -------------------------
    elif request.action == "confirm_unidentified":
        pass  # identity_status already correctly reflects why it's unmatched

    else:
        raise HTTPException(status_code=400, detail="Invalid action.")

    db.commit()
    db.refresh(submission)

    return submission