"""Account controls, kept separate from immutable preference profiles."""
from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, CHAR, DateTime, ForeignKey, text
from sqlalchemy.orm import Mapped, mapped_column

from database import Base


class InstructorAccountSettings(Base):
    __tablename__ = "instructor_account_settings"

    user_id: Mapped[str] = mapped_column(CHAR(36), ForeignKey("users.id"), primary_key=True)
    institution_id: Mapped[str] = mapped_column(CHAR(36), ForeignKey("institutions.id"), nullable=False)
    use_marking_preferences: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("1"))
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
