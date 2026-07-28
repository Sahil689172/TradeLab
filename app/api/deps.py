"""Shared FastAPI dependencies."""

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.database import get_db
from app.market_data.services import MarketDataGateway


def get_app_settings(request: Request) -> Settings:
    """Return settings bound to the running FastAPI application.

    Using ``app.state.settings`` keeps configuration consistent for the
    process that created the app (including tests that pass overrides).
    """
    return request.app.state.settings


def get_market_data_gateway(session: Session = Depends(get_db)) -> MarketDataGateway:
    """Return the market data gateway using the current database session."""
    return MarketDataGateway(session)
