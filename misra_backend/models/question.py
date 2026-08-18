from database import Base
from typing import Optional
from sqlalchemy import CHAR, String, Text, DateTime, Enum, ForeignKey, Numeric, Integer, func, JSON
from sqlalchemy.orm import Mapped, mapped_column
from datetime import datetime
import uuid

class Question(Base):
    __tablename__ = "questions"

    id: Mapped[str] = mapped_column(CHAR(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    institution_id: Mapped[str] = mapped_column(CHAR(36), ForeignKey("institutions.id"), nullable=False)
    exam_id: Mapped[str] = mapped_column(CHAR(36), ForeignKey("exams.id"), nullable=False)
    question_number: Mapped[str] = mapped_column(String(20), nullable=False)
    question_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    max_score: Mapped[float] = mapped_column(Numeric(6, 2), nullable=False)
    rubric_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    order_index: Mapped[int] = mapped_column(Integer, nullable=False)
    language: Mapped[str] = mapped_column(Enum("ar", "en", "mixed"), nullable=False, default="mixed")
    active_rubric_version_id: Mapped[Optional[str]] = mapped_column(
        CHAR(36), ForeignKey("rubric_versions.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
