from datetime import datetime
import uuid

from sqlalchemy import (
    CHAR,
    DateTime,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from database import Base


class RubricVersion(Base):
    __tablename__ = "rubric_versions"

    id: Mapped[str] = mapped_column(
        CHAR(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    question_id: Mapped[str] = mapped_column(
        CHAR(36), ForeignKey("questions.id"), nullable=False, index=True
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False, default=2)
    rubric_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    grading_approach: Mapped[str] = mapped_column(
        String(20), nullable=False, default="balanced"
    )
    source: Mapped[str] = mapped_column(
        String(20), nullable=False, default="manual"
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="draft", index=True
    )
    change_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str | None] = mapped_column(
        CHAR(36), ForeignKey("users.id"), nullable=True
    )
    approved_by: Mapped[str | None] = mapped_column(
        CHAR(36), ForeignKey("users.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "question_id",
            "version_number",
            name="uq_rubric_version_question_number",
        ),
    )
