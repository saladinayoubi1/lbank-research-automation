from __future__ import annotations

import json
from pathlib import Path

import nexus_multipair_discovery_snapshot as snapshot
from nexus_multipair_trusted_surface import (
    FAMILIES,
    MATRIX_MANIFEST,
    SYMBOLS,
    TIMEFRAMES,
    load_trusted_surface,
)


ROOT = Path(__file__).resolve().parents[1]


def test_trusted_surface_is_exact_matrix_v2_surface() -> None:
    raw = json.loads(MATRIX_MANIFEST.read_text(encoding="utf-8"))
    symbols, timeframes, families = load_trusted_surface()
    assert symbols == tuple(raw["symbols"])
    assert timeframes == tuple(raw["timeframes"])
    assert families == tuple(raw["families"])
    assert len(symbols) * len(timeframes) == 12
    assert len(symbols) * len(timeframes) * len(families) == 36


def test_discovery_snapshot_consumes_trusted_runtime_surface() -> None:
    assert snapshot.SYMBOLS is SYMBOLS
    assert snapshot.TIMEFRAME_NAMES is TIMEFRAMES
    assert list(snapshot.SYMBOLS) == ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT"]
    assert list(snapshot.TIMEFRAME_NAMES) == ["minute15", "hour1", "hour4"]
    assert list(FAMILIES) == ["momentum", "trend_breakout", "mean_reversion"]


def test_trusted_surface_has_no_authority_to_enable_live() -> None:
    raw = json.loads((ROOT / "config" / "nexus-demo-strategy-matrix-v2.json").read_text(encoding="utf-8"))
    assert raw["authority"]["paper_only"] is True
    assert raw["authority"]["live_trading_authority"] is False
    assert raw["authority"]["private_credentials_allowed"] is False
    assert raw["authority"]["automatic_strategy_promotion"] is False
    assert raw["authority"]["deterministic_risk_final_authority"] is True
