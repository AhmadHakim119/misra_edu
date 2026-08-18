from datetime import datetime
import uuid

from sqlalchemy import Boolean, CHAR, DateTime, ForeignKey, Integer, JSON, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from database import Base


class AnswerSource(Base):
    __tablename__ = "answer_sources"

    id: Mapped[str] = mapped_column(
        CHAR(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    answer_id: Mapped[str] = mapped_column(
        CHAR(36), ForeignKey("answers.id"), nullable=False, index=True
    )

    # Zero-based index within the original submission.
    page_index: Mapped[int] = mapped_column(Integer, nullable=False)
    segment_index: Mapped[int] = mapped_column(Integer, nullable=False)

    question_number: Mapped[str | None] = mapped_column(Text, nullable=True)
    extracted_text: Mapped[str] = mapped_column(Text, nullable=False)
    has_math: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    ocr_segment: Mapped[dict] = mapped_column(JSON, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now()
    )