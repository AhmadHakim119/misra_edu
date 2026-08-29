from datetime import datetime
import uuid

from sqlalchemy import (
    CHAR,
    DateTime,
    ForeignKey,
    Integer,
    JSON,
    Numeric,
    String,
    Text,
    Boolean,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from database import Base


class GradingRun(Base):
    __tablename__ = "grading_runs"

    id: Mapped[str] = mapped_column(
        CHAR(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    answer_id: Mapped[str] = mapped_column(
        CHAR(36),
        ForeignKey("answers.id"),
        nullable=False,
        index=True,
    )
    rubric_version_id: Mapped[str | None] = mapped_column(
        CHAR(36),
        ForeignKey("rubric_versions.id"),
        nullable=True,
        index=True,
    )
    processing_job_id: Mapped[str | None] = mapped_column(
        CHAR(36),
        ForeignKey("processing_jobs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    mode: Mapped[str] = mapped_column(String(20), nullable=False)
    model_name: Mapped[str] = mapped_column(String(100), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(50), nullable=False)

    source_page_indices: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    ocr_text_snapshot: Mapped[str] = mapped_column(Text, nullable=False)
    rubric_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)

    score: Mapped[float] = mapped_column(Numeric(6, 2), nullable=False)
    max_score: Mapped[float] = mapped_column(Numeric(6, 2), nullable=False)
    grade_letter: Mapped[str | None] = mapped_column(CHAR(5), nullable=True)
    feedback: Mapped[str] = mapped_column(Text, nullable=False)
    reasoning: Mapped[str] = mapped_column(Text, nullable=False)
    criteria_scores: Mapped[dict] = mapped_column(JSON, nullable=False)

    llm_confidence: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False)
    final_confidence: Mapped[float] = mapped_column(
        Numeric(5, 2),
        nullable=False,
    )
    needs_review: Mapped[bool] = mapped_column(Boolean, nullable=False)

    response_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now(),
    )
