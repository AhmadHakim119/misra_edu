from database import Base
from sqlalchemy import CHAR, DateTime, ForeignKey, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column
from datetime import datetime
import uuid

class CourseEnrollment(Base):
    __tablename__ = "course_enrollments"

    id: Mapped[str] = mapped_column(CHAR(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    course_id: Mapped[str] = mapped_column(CHAR(36), ForeignKey("courses.id"), nullable=False)
    student_id: Mapped[str] = mapped_column(CHAR(36), ForeignKey("students.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("course_id", "student_id", name="uq_enrollment"),
    )