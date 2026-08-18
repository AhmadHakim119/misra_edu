from database import Base
from sqlalchemy import CHAR, String, DateTime, Enum, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column
from datetime import datetime
import uuid

class Exam(Base):
    __tablename__ = "exams"

    id: Mapped[str] = mapped_column(CHAR(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    institution_id: Mapped[str] = mapped_column(CHAR(36), ForeignKey("institutions.id"), nullable=False)
    course_id: Mapped[str] = mapped_column(CHAR(36), ForeignKey("courses.id"), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    language: Mapped[str] = mapped_column(Enum("ar", "en", "mixed"), nullable=False, default="mixed")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())