from database import Base
from typing import Optional
from sqlalchemy import CHAR, DateTime, Enum, ForeignKey, func, JSON
from sqlalchemy.orm import Mapped, mapped_column
from datetime import datetime
import uuid

class RubricSuggestion(Base):
    __tablename__ = "rubric_suggestions"

    id: Mapped[str] = mapped_column(CHAR(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    question_id: Mapped[Optional[str]] = mapped_column(CHAR(36), ForeignKey("questions.id"), nullable=True)
    suggested_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(
        Enum("pending", "accepted", "edited", "rejected"),
        nullable=False,
        default="pending"
    )
    final_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    generated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
