"""Course-owned reference documents; approved content is versioned, never edited."""
from datetime import datetime
import uuid

from sqlalchemy import CHAR, DateTime, ForeignKey, Integer, JSON, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column
from database import Base
from sqlalchemy.dialects.mysql import LONGTEXT


class CourseMaterial(Base):
    __tablename__ = "course_materials"
    id: Mapped[str] = mapped_column(CHAR(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    institution_id: Mapped[str] = mapped_column(CHAR(36), ForeignKey("institutions.id"), nullable=False, index=True)
    course_id: Mapped[str] = mapped_column(CHAR(36), ForeignKey("courses.id"), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    created_by: Mapped[str | None] = mapped_column(CHAR(36), ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class MaterialVersion(Base):
    __tablename__ = "material_versions"
    id: Mapped[str] = mapped_column(CHAR(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    material_id: Mapped[str] = mapped_column(CHAR(36), ForeignKey("course_materials.id"), nullable=False, index=True)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    ingestion_status: Mapped[str] = mapped_column(String(30), nullable=False, default="queued")
    original_file_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    media_type: Mapped[str] = mapped_column(String(80), nullable=False)
    document_sha256: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    content_sha256: Mapped[str | None] = mapped_column(CHAR(64), nullable=True)
    page_count: Mapped[int] = mapped_column(Integer, nullable=False)
    approved_page_indices: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    parser_version: Mapped[str] = mapped_column(String(100), nullable=False, default="pending")
    processing_job_id: Mapped[str | None] = mapped_column(CHAR(36), ForeignKey("processing_jobs.id"), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str | None] = mapped_column(CHAR(36), ForeignKey("users.id"), nullable=True)
    approved_by: Mapped[str | None] = mapped_column(CHAR(36), ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    approved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    __table_args__ = (UniqueConstraint("material_id", "version_number", name="uq_material_version_number"),)


class MaterialPage(Base):
    __tablename__ = "material_pages"
    id: Mapped[str] = mapped_column(CHAR(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    version_id: Mapped[str] = mapped_column(CHAR(36), ForeignKey("material_versions.id"), nullable=False, index=True)
    page_index: Mapped[int] = mapped_column(Integer, nullable=False)
    printed_page_label: Mapped[str | None] = mapped_column(String(30), nullable=True)
    text: Mapped[str] = mapped_column(Text().with_variant(LONGTEXT(), "mysql").with_variant(LONGTEXT(), "mariadb"), nullable=False)
    text_sha256: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    origin: Mapped[str] = mapped_column(String(30), nullable=False, default="native_text_unverified")
    __table_args__ = (UniqueConstraint("version_id", "page_index", name="uq_material_page_index"),)


class MaterialChunk(Base):
    __tablename__ = "material_chunks"
    id: Mapped[str] = mapped_column(CHAR(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    version_id: Mapped[str] = mapped_column(CHAR(36), ForeignKey("material_versions.id"), nullable=False, index=True)
    page_index: Mapped[int] = mapped_column(Integer, nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    char_start: Mapped[int] = mapped_column(Integer, nullable=False)
    char_end: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    text_sha256: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    __table_args__ = (UniqueConstraint("version_id", "page_index", "ordinal", name="uq_material_chunk_position"),)


class QuestionMaterialScopeVersion(Base):
    __tablename__ = "question_material_scope_versions"
    id: Mapped[str] = mapped_column(CHAR(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    question_id: Mapped[str] = mapped_column(CHAR(36), ForeignKey("questions.id"), nullable=False, index=True)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    mode: Mapped[str] = mapped_column(String(20), nullable=False, default="required")
    bindings: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    scope_sha256: Mapped[str | None] = mapped_column(CHAR(64), nullable=True)
    created_by: Mapped[str | None] = mapped_column(CHAR(36), ForeignKey("users.id"), nullable=True)
    approved_by: Mapped[str | None] = mapped_column(CHAR(36), ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    approved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    __table_args__ = (UniqueConstraint("question_id", "version_number", name="uq_question_material_scope_version"),)


class AssessmentMaterialScopeVersion(Base):
    """Approved source defaults for future runs, not a mutable exam setting."""
    __tablename__ = "assessment_material_scope_versions"
    id: Mapped[str] = mapped_column(CHAR(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    exam_id: Mapped[str] = mapped_column(CHAR(36), ForeignKey("exams.id"), nullable=False, index=True)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    mode: Mapped[str] = mapped_column(String(20), nullable=False, default="required")
    bindings: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    scope_sha256: Mapped[str | None] = mapped_column(CHAR(64), nullable=True)
    created_by: Mapped[str | None] = mapped_column(CHAR(36), ForeignKey("users.id"), nullable=True)
    approved_by: Mapped[str | None] = mapped_column(CHAR(36), ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    approved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    __table_args__ = (UniqueConstraint("exam_id", "version_number", name="uq_assessment_material_scope_version"),)
