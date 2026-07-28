"""ORM model for company metadata."""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Date, DateTime, Float, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class CompanyMetadataModel(Base):
    """Persistent company metadata keyed by trading symbol."""

    __tablename__ = "company_metadata"

    symbol: Mapped[str] = mapped_column(String(32), primary_key=True)
    company_name: Mapped[str] = mapped_column(String(256), nullable=False)
    sector: Mapped[str | None] = mapped_column(String(128), nullable=True)
    industry: Mapped[str | None] = mapped_column(String(128), nullable=True)
    exchange: Mapped[str] = mapped_column(String(32), nullable=False)
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="INR")
    market_cap: Mapped[float | None] = mapped_column(Float, nullable=True)
    market_cap_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    last_updated: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
