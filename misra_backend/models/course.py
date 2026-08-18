from database import Base
from typing import Optional
from sqlalchemy import CHAR, String, DateTime, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column
from datetime import datetime
import uuid

class Course(Base):
    __tablename__ = "courses"

    id: Mapped[str] = mapped_column(CHAR(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    institution_id: Mapped[str] = mapped_column(CHAR(36), ForeignKey("institutions.id"), nullable=False)
    teacher_id: Mapped[str] = mapped_column(CHAR(36), ForeignKey("users.id"), nullable=False)
    instructor_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    course_code: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    term: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
