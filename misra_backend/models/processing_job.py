from datetime import datetime
import uuid

from sqlalchemy import CHAR, DateTime, Enum, ForeignKey, Index, Integer, JSON, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from database import Base


class ProcessingJob(Base):
    """Durable database record for work dispatched through Redis/RQ.

    Redis is the delivery mechanism. This row is the application-visible source
    of truth, so progress and failures remain inspectable even after an RQ result
    expires or Redis is restarted.
    """

    __tablename__ = "processing_jobs"

    id: Mapped[str] = mapped_column(
        CHAR(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    institution_id: Mapped[str] = mapped_column(
        CHAR(36), ForeignKey("institutions.id"), nullable=False
    )
    requested_by: Mapped[str | None] = mapped_column(
        CHAR(36), ForeignKey("users.id"), nullable=True
    )
    submission_id: Mapped[str | None] = mapped_column(
        CHAR(36), ForeignKey("submissions.id", ondelete="CASCADE"), nullable=True
    )
    batch_id: Mapped[str | None] = mapped_column(
        CHAR(36), ForeignKey("batches.id", ondelete="CASCADE"), nullable=True
    )
    job_type: Mapped[str] = mapped_column(
        Enum("ocr_submission", "ocr_batch", "grade_submission"), nullable=False
    )
    status: Mapped[str] = mapped_column(
        Enum("queued", "processing", "completed", "failed", "retrying"),
        nullable=False,
        default="queued",
    )
    rq_job_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    progress_current: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    progress_total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    progress_message: Mapped[str | None] = mapped_column(String(255), nullable=True)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        Index("ix_processing_jobs_institution_status", "institution_id", "status"),
        Index("ix_processing_jobs_submission_created", "submission_id", "created_at"),
        Index("ix_processing_jobs_batch_created", "batch_id", "created_at"),
        Index("ix_processing_jobs_rq_job_id", "rq_job_id"),
    )
