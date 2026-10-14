"""Immutable OCR page inventory; no new columns on existing submission tables."""
import uuid
from datetime import datetime
from sqlalchemy import CHAR, DateTime, ForeignKey, Integer, JSON, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column
from database import Base


class ExtractionInventory(Base):
    __tablename__ = "extraction_inventories"
    id: Mapped[str] = mapped_column(CHAR(36),primary_key=True,default=lambda:str(uuid.uuid4()))
    submission_id: Mapped[str] = mapped_column(CHAR(36),ForeignKey("submissions.id",ondelete="CASCADE"),nullable=False,index=True)
    institution_id: Mapped[str] = mapped_column(CHAR(36),ForeignKey("institutions.id"),nullable=False,index=True)
    version_number: Mapped[int] = mapped_column(Integer,nullable=False)
    schema_version: Mapped[int] = mapped_column(Integer,nullable=False,default=1)
    page_count: Mapped[int] = mapped_column(Integer,nullable=False)
    document_sha256: Mapped[str] = mapped_column(CHAR(64),nullable=False)
    manifest_sha256: Mapped[str] = mapped_column(CHAR(64),nullable=False)
    pages: Mapped[list] = mapped_column(JSON,nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime,server_default=func.now())
    __table_args__ = (UniqueConstraint("submission_id","version_number",name="uq_extraction_inventory_version"),)
