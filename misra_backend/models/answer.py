from database import Base
from typing import Optional
from sqlalchemy import CHAR, Text, DateTime, Enum, ForeignKey, Numeric, Boolean, func, JSON
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import UniqueConstraint
from datetime import datetime
import uuid

class Answer(Base):
    __tablename__ = "answers"

    id: Mapped[str] = mapped_column(CHAR(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    institution_id: Mapped[str] = mapped_column(CHAR(36), ForeignKey("institutions.id"), nullable=False)
    submission_id: Mapped[str] = mapped_column(CHAR(36), ForeignKey("submissions.id"), nullable=False)
    question_id: Mapped[str] = mapped_column(CHAR(36), ForeignKey("questions.id"), nullable=False)

    raw_ocr_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    ocr_legibility: Mapped[Optional[str]] = mapped_column(
        Enum("clear", "partial", "illegible"), nullable=True
    )
    ocr_raw_response: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    score: Mapped[Optional[float]] = mapped_column(Numeric(6, 2), nullable=True)
    max_score: Mapped[Optional[float]] = mapped_column(Numeric(6, 2), nullable=True)
    grade_letter: Mapped[Optional[str]] = mapped_column(CHAR(5), nullable=True)
    feedback: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    reasoning: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    criteria_scores: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    llm_confidence: Mapped[Optional[float]] = mapped_column(Numeric(5, 2), nullable=True)
    final_confidence: Mapped[Optional[float]] = mapped_column(Numeric(5, 2), nullable=True)
    grading_raw_response: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    needs_review: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    review_status: Mapped[str] = mapped_column(
        Enum("none", "pending", "approved", "overridden"),
        nullable=False,
        default="none"
    )
    teacher_override_score: Mapped[Optional[float]] = mapped_column(Numeric(6, 2), nullable=True)
    teacher_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    review_reasons: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    reviewed_by: Mapped[Optional[str]] = mapped_column(CHAR(36), ForeignKey("users.id"), nullable=True)
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("submission_id", "question_id", name="uq_submission_question"),
    )
