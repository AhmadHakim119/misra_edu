from datetime import datetime
import uuid

from sqlalchemy import CHAR, DateTime, ForeignKey, Integer, JSON, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from database import Base


class InstructorPreferenceVersion(Base):
    """A user-owned, versioned proposal for instructor marking preferences.

    These records are deliberately independent from rubrics and grading runs. An
    approved profile is evidence of an instructor's stated preferences; it is
    never an instruction to rewrite an assessment policy automatically.
    """

    __tablename__ = "instructor_preference_versions"

    id: Mapped[str] = mapped_column(
        CHAR(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    institution_id: Mapped[str] = mapped_column(
        CHAR(36), ForeignKey("institutions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[str] = mapped_column(
        CHAR(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft", index=True)
    explicit_preferences: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    scenario_answers: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    derived_proposal: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    proposal_provenance: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    change_summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_by: Mapped[str] = mapped_column(
        CHAR(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    approved_by: Mapped[str | None] = mapped_column(
        CHAR(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "version_number",
            name="uq_instructor_preference_user_version",
        ),
    )
