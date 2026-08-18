from database import Base
from typing import Optional
from sqlalchemy import CHAR, String, Text, DateTime, Enum, ForeignKey, Integer, func, JSON
from sqlalchemy.orm import Mapped, mapped_column
from datetime import datetime
import uuid

class Submission(Base):
    __tablename__ = "submissions"

    id: Mapped[str] = mapped_column(CHAR(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    institution_id: Mapped[str] = mapped_column(CHAR(36), ForeignKey("institutions.id"), nullable=False)
    exam_id: Mapped[str] = mapped_column(CHAR(36), ForeignKey("exams.id"), nullable=False)
    batch_id: Mapped[Optional[str]] = mapped_column(CHAR(36), ForeignKey("batches.id"), nullable=True)
    student_id: Mapped[Optional[str]] = mapped_column(CHAR(36), ForeignKey("students.id"), nullable=True)
    extracted_student_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    extracted_student_number: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    identity_status: Mapped[str] = mapped_column(
        Enum("matched", "unmatched_extracted", "unmatched_blank", "unmatched_illegible"),
        nullable=False,
        default="unmatched_blank"
    )
    original_file_path: Mapped[str] = mapped_column(Text, nullable=False)
    page_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status: Mapped[str] = mapped_column(
        Enum("uploaded", "extracting", "extracted", "grading", "graded", "needs_review", "reviewed", "error"),
        nullable=False,
        default="uploaded"
    )
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    unmatched_segments: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)