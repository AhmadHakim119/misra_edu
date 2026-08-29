from database import Base
from typing import Optional
from sqlalchemy import Boolean, CHAR, String, DateTime, Integer, func, ForeignKey, Enum, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column
from datetime import datetime
import uuid

class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(CHAR(36),primary_key=True, default=lambda: str(uuid.uuid4()))
    institution_id: Mapped[str] = mapped_column(CHAR(36), ForeignKey("institutions.id"), nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[Optional[str]] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(Enum('teacher', 'admin'), nullable=False, default='teacher')
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("1"))
    must_change_password: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("0"))
    session_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default=text("1"))
    password_changed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("institution_id", "email", name="uq_user_email_per_institution"),
    )
