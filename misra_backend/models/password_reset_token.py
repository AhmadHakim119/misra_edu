from __future__ import annotations

from datetime import datetime
from typing import Optional
import uuid

from sqlalchemy import CHAR, DateTime, ForeignKey, Index, String, func
from sqlalchemy.orm import Mapped, mapped_column

from database import Base


class PasswordResetToken(Base):
    __tablename__ = "password_reset_tokens"

    id: Mapped[str] = mapped_column(CHAR(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[Optional[str]] = mapped_column(
        CHAR(36),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=True,
    )
    email_hash: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    request_ip_hash: Mapped[Optional[str]] = mapped_column(CHAR(64), nullable=True)
    token_hash: Mapped[str] = mapped_column(CHAR(64), nullable=False, unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    used_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())

    __table_args__ = (
        Index("ix_password_reset_email_created", "email_hash", "created_at"),
        Index("ix_password_reset_ip_created", "request_ip_hash", "created_at"),
        Index("ix_password_reset_user", "user_id"),
    )
