from datetime import datetime
import uuid

from sqlalchemy import (
    Boolean,
    CHAR,
    DateTime,
    ForeignKey,
    JSON,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from database import Base


class ReviewLabel(Base):
    __tablename__ = "review_labels"

    id: Mapped[str] = mapped_column(
        CHAR(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )

    # An answer may be labelled once for each grading run/rubric version.
    answer_id: Mapped[str] = mapped_column(
        CHAR(36),
        ForeignKey("answers.id"),
        nullable=False,
        index=True,
    )
    grading_run_id: Mapped[str | None] = mapped_column(
        CHAR(36),
        ForeignKey("grading_runs.id"),
        nullable=True,
        index=True,
    )
    rubric_version_id: Mapped[str | None] = mapped_column(
        CHAR(36),
        ForeignKey("rubric_versions.id"),
        nullable=True,
        index=True,
    )

    # Snapshot preserves evaluation evidence even if AI is later re-run.
    ai_score_snapshot: Mapped[float] = mapped_column(
        Numeric(6, 2),
        nullable=False,
    )
    human_score: Mapped[float] = mapped_column(
        Numeric(6, 2),
        nullable=False,
    )

    # Preserve the AI state that the reviewer actually saw. These values make
    # review-flag precision/recall possible even after the Answer is re-graded.
    ai_final_confidence_snapshot: Mapped[float | None] = mapped_column(
        Numeric(5, 2), nullable=True
    )
    ai_needs_review_snapshot: Mapped[bool | None] = mapped_column(
        Boolean, nullable=True
    )
    ai_criteria_scores_snapshot: Mapped[list[dict] | None] = mapped_column(
        JSON, nullable=True
    )

    was_review_warranted: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
    )

    # Optional now; needed later for real criterion-level agreement.
    human_criteria_scores: Mapped[list[dict] | None] = mapped_column(
        JSON,
        nullable=True,
    )
    reviewer_notes: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    label_source: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="instructor_review",
    )
    labeled_by: Mapped[str | None] = mapped_column(
        CHAR(36),
        ForeignKey("users.id"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now(),
    )

    __table_args__ = (
        UniqueConstraint(
            "grading_run_id",
            name="uq_review_labels_grading_run_id",
        ),
    )
