from sqlalchemy import Boolean, CHAR, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from database import Base


class QuestionGradingPolicy(Base):
    __tablename__ = "question_grading_policies"

    question_id: Mapped[str] = mapped_column(
        CHAR(36), ForeignKey("questions.id"), primary_key=True
    )
    mode: Mapped[str] = mapped_column(String(30), nullable=False, default="adaptive")
    audit_rate: Mapped[float] = mapped_column(Numeric(5, 4), nullable=False, default=0.1)
    min_validated_samples: Mapped[int] = mapped_column(Integer, nullable=False, default=10)
    material_absolute_points: Mapped[float] = mapped_column(
        Numeric(6, 2), nullable=False, default=0.5
    )
    material_relative_ratio: Mapped[float] = mapped_column(
        Numeric(5, 4), nullable=False, default=0.2
    )
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
