"""Reviewed chapter boundaries and assessment-only course-material attachments."""
import uuid
from datetime import datetime
from sqlalchemy import CHAR, ForeignKey, JSON, Integer, DateTime, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column
from database import Base


class MaterialChapterIndex(Base):
    __tablename__ = 'material_chapter_indexes'
    id: Mapped[str] = mapped_column(CHAR(36), primary_key=True, default=lambda:str(uuid.uuid4()))
    version_id: Mapped[str] = mapped_column(CHAR(36), ForeignKey('material_versions.id'), nullable=False, index=True)
    revision_number: Mapped[int] = mapped_column(Integer, nullable=False)
    chapters: Mapped[list] = mapped_column(JSON, nullable=False)
    text_fingerprint: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    created_by: Mapped[str] = mapped_column(CHAR(36), ForeignKey('users.id'), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    __table_args__ = (UniqueConstraint('version_id','revision_number',name='uq_material_chapter_revision'),)


class AssessmentMaterialAttachment(Base):
    __tablename__ = 'assessment_material_attachments'
    id: Mapped[str] = mapped_column(CHAR(36), primary_key=True, default=lambda:str(uuid.uuid4()))
    material_id: Mapped[str] = mapped_column(CHAR(36), ForeignKey('course_materials.id'), nullable=False, unique=True)
    exam_id: Mapped[str] = mapped_column(CHAR(36), ForeignKey('exams.id'), nullable=False, index=True)
    __table_args__ = (UniqueConstraint('material_id','exam_id',name='uq_assessment_material_attachment'),)
