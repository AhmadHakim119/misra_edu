from database import Base
from sqlalchemy import CHAR, DateTime, Enum, ForeignKey, Integer, func
from sqlalchemy.orm import Mapped, mapped_column
from datetime import datetime
import uuid

class Batch(Base):
    __tablename__ = "batches"

    id: Mapped[str] = mapped_column(CHAR(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    institution_id: Mapped[str] = mapped_column(CHAR(36), ForeignKey("institutions.id"), nullable=False)
    exam_id: Mapped[str] = mapped_column(CHAR(36), ForeignKey("exams.id"), nullable=False)
    total_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    completed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(
        Enum("queued", "processing", "completed", "completed_with_errors"),
        nullable=False,
        default="queued"
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())