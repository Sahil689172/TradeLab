"""Tests for MarketDataGateway."""

from __future__ import annotations

import pytest

from app.market_data.exceptions import RepositoryError, ValidationError
from tests.market_data.conftest import make_company_metadata, make_ingestion_state, make_ohlcv_dataframe


def test_gateway_save_and_get_history(gateway) -> None:
    """Gateway validates and persists OHLCV history."""
    frame = make_ohlcv_dataframe()
    path = gateway.save_history("RELIANCE", frame)

    assert path.name == "RELIANCE.parquet"
    loaded = gateway.get_history("RELIANCE")
    assert len(loaded) == len(frame)
    assert gateway.history_exists("RELIANCE") is True


def test_gateway_rejects_invalid_history(gateway) -> None:
    """Gateway raises ValidationError for invalid OHLCV data."""
    bad = make_ohlcv_dataframe()
    bad.loc[0, "volume"] = -5.0

    with pytest.raises(ValidationError):
        gateway.save_history("RELIANCE", bad)


def test_gateway_metadata_operations(gateway) -> None:
    """Gateway exposes metadata save/get/update/delete."""
    metadata = make_company_metadata("TCS")
    saved = gateway.save_metadata(metadata)
    assert saved.symbol == "TCS"

    fetched = gateway.get_metadata("TCS")
    assert fetched is not None
    assert fetched.company_name == metadata.company_name

    updated = gateway.update_metadata(
        metadata.model_copy(update={"company_name": "TCS Ltd"}),
    )
    assert updated.company_name == "TCS Ltd"
    assert gateway.delete_metadata("TCS") is True
    assert gateway.get_metadata("TCS") is None


def test_gateway_ingestion_state_operations(gateway) -> None:
    """Gateway exposes ingestion state save/get/update."""
    state = make_ingestion_state("INFY")
    saved = gateway.save_ingestion_state(state)
    assert saved.row_count == 1000

    fetched = gateway.get_ingestion_state("INFY")
    assert fetched is not None
    assert fetched.last_fetch_status == "success"

    updated = gateway.update_ingestion_state(
        state.model_copy(update={"row_count": 1500, "last_fetch_status": "ok"}),
    )
    assert updated.row_count == 1500
    assert updated.last_fetch_status == "ok"


def test_gateway_get_history_missing_raises(gateway) -> None:
    """Gateway propagates RepositoryError for missing history."""
    with pytest.raises(RepositoryError, match="not found"):
        gateway.get_history("UNKNOWN")


def test_gateway_delete_history(gateway) -> None:
    """Gateway can delete stored OHLCV history."""
    gateway.save_history("HDFCBANK", make_ohlcv_dataframe())
    assert gateway.delete_history("HDFCBANK") is True
    assert gateway.history_exists("HDFCBANK") is False
