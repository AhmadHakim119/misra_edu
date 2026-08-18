from database import Base
from typing import Optional
from sqlalchemy import CHAR, String, DateTime, ForeignKey, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column
from datetime import datetime
import uuid

class Student(Base):
    __tablename__ = "students"

    id: Mapped[str] = mapped_column(CHAR(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    institution_id: Mapped[str] = mapped_column(CHAR(36), ForeignKey("institutions.id"), nullable=False)
    student_number: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("institution_id", "student_number", name="uq_student_number_per_institution"),
    )