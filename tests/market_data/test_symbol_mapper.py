"""Tests for corporate-action symbol mapping."""

from __future__ import annotations

import json
from pathlib import Path

from app.market_data.universe.symbol_mapper import SymbolMapper


def test_symbol_mapper_loads_versioned_corporate_actions() -> None:
    mapper = SymbolMapper(discoverer=lambda *_: None)

    assert mapper.map_symbol("LTI") == "LTIM"
    assert mapper.map_symbol("MINDTREE") == "LTIM"
    assert mapper.map_symbol("PVR") == "PVRINOX"
    assert mapper.map_symbol("CADILAHC") == "ZYDUSLIFE"
    assert mapper.map_symbol("HDFC") == "HDFCBANK"
    assert mapper.map_symbol("MOTHERSUMI") == "MOTHERSON"


def test_symbol_mapper_preserves_unmapped_symbol() -> None:
    mapper = SymbolMapper(discoverer=lambda *_: None)
    assert mapper.map_symbol("TATAMOTORS.NS") == "TATAMOTORS"


def test_symbol_mapper_uses_injected_discovery(tmp_path: Path) -> None:
    mapping_file = tmp_path / "mapping.json"
    mapping_file.write_text(json.dumps({}), encoding="utf-8")
    mapper = SymbolMapper(
        mapping_file,
        discoverer=lambda company, symbol: "NEWNAME.NS",
    )

    assert mapper.discover_symbol("OLDNAME", "New Name Ltd.") == "NEWNAME"
