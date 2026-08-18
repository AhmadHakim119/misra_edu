from database import Base
from typing import Optional
from sqlalchemy import CHAR, String, DateTime, func
from sqlalchemy.orm import Mapped, mapped_column
from datetime import datetime
import uuid

class Institution(Base):
    __tablename__ = "institutions"

    id: Mapped[str] = mapped_column(CHAR(36),primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    country: Mapped[Optional[str]] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())