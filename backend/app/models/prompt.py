from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Prompt(Base):
    """A versioned, mutable LLM prompt.

    Mirrors the cortex/emergent pattern: prompts are addressed by name,
    fetched at runtime, and version-bumped on each upsert so we can roll
    back. The training dashboard writes here instead of rewriting
    prompts.py on disk.
    """

    __tablename__ = "prompts"

    name: Mapped[str] = mapped_column(String(128), primary_key=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
