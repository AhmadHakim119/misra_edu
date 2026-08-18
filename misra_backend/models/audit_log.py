from database import Base
from typing import Optional
from sqlalchemy import CHAR, String, DateTime, ForeignKey, func, JSON
from sqlalchemy.orm import Mapped, mapped_column
from datetime import datetime
import uuid

class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[str] = mapped_column(CHAR(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    institution_id: Mapped[Optional[str]] = mapped_column(CHAR(36), ForeignKey("institutions.id"), nullable=True)
    actor_id: Mapped[Optional[str]] = mapped_column(CHAR(36), ForeignKey("users.id"), nullable=True)
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(50), nullable=False)
    entity_id: Mapped[Optional[str]] = mapped_column(CHAR(36), nullable=True)
    extra_data: Mapped[Optional[dict]] = mapped_column("metadata", JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())