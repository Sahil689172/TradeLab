"""ORM model for per-symbol ingestion tracking state."""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Date, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class IngestionStateModel(Base):
    """Tracks available date range and last fetch status for a symbol."""

    __tablename__ = "ingestion_state"

    symbol: Mapped[str] = mapped_column(String(32), primary_key=True)
    first_available_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    last_available_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    last_fetch_timestamp: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    last_fetch_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    row_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
