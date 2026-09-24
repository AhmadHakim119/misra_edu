"""Question-scoped answer references, independent of scoring rubrics."""
from datetime import datetime
import uuid

from sqlalchemy import CHAR, DateTime, ForeignKey, Integer, JSON, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column
from database import Base


class AnswerKeyVersion(Base):
    __tablename__ = 'answer_key_versions'
    id: Mapped[str] = mapped_column(CHAR(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    question_id: Mapped[str] = mapped_column(CHAR(36), ForeignKey('questions.id', ondelete='CASCADE'), nullable=False)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default='draft')
    mode: Mapped[str] = mapped_column(String(30), nullable=False)
    reference_text: Mapped[str] = mapped_column(Text, nullable=False, default='')
    acceptable_answers: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    document_refs: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    change_summary: Mapped[str] = mapped_column(Text, nullable=False, default='')
    created_by: Mapped[str | None] = mapped_column(CHAR(36), ForeignKey('users.id'), nullable=True)
    approved_by: Mapped[str | None] = mapped_column(CHAR(36), ForeignKey('users.id'), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    approved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    __table_args__ = (UniqueConstraint('question_id', 'version_number', name='uq_answer_key_question_version'),)
