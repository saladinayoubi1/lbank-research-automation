from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from phase6_research_pipeline import bind_bybit_closed_dataset
import nexus_low_turnover_hypothesis_v1 as low
import nexus_low_turnover_training_v1 as train

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "experiments" / "nexus_low_turnover_hypothesis_v1.json"


def _dataset(symbol: str, *, shift: int = 0) -> dict:
    rows = []
    for index in range(train.COUNT):
        time_ms = train.START_MS + (index + shift) * train.STEP_MS
        close = (100.0 if symbol == "BTCUSDT" else 200.0) * (
            1 + 0.001 * index + 0.012 * math.sin(index / 5)
        )
        rows.append({
            "source": "Bybit", "market_type": "spot", "symbol": symbol,
            "interval": "240", "open_time_ms": time_ms,
            "open": str(close), "high": str(close * 1.01),
            "low": str(close * 0.99), "close": str(close),
            "volume": str(100 + index), "closed": True,
        })
    from market_data_source_validator import load_and_validate
    from product_research_runtime import _public_mapping, _registry_path

    mapping, source = _public_mapping(load_and_validate(_registry_path()), symbol, "hour4")
    assert source["symbol"] == symbol
    return bind_bybit_closed_dataset(
        rows, canonical_symbol=mapping["canonical_symbol"],
        source_symbol=symbol, interval="240",
    )


def test_frozen_real_time_boundary_and_source_identity() -> None:
    manifest = low.load_manifest(MANIFEST)
    assert train.SOURCE_SHA == "aca436fff20f1d208d4ec67f54099f7d3fc75d89"
    assert train.CUTOFF.isoformat() == "2026-08-20T00:00:00+00:00"
    assert manifest["evaluation"]["future_holdout_no_earlier_than_utc"] > "2026-08-20"


def test_training_only_cross_asset_cost_diagnostics_are_deterministic() -> None:
    datasets = {symbol: _dataset(symbol) for symbol in ("BTCUSDT", "ETHUSDT")}
    manifest = low.load_manifest(MANIFEST)
    result = train.evaluate(manifest, datasets)
    assert train.evaluate(manifest, datasets) == result
    assert len(result["evaluated_cells"]) == 6
    assert result["locked_holdout_evaluated"] is False
    assert result["qualifies_for_paper_review"] is False
    assert result["live_trading_authority"] is False
    assert result["failed_prior_paper_period_excluded"] is True
    assert {c["strategy"] for c in result["evaluated_cells"]} == {
        "control_existing_12bar_momentum", "frozen_variant_1", "frozen_variant_2"
    }
    for cell in result["evaluated_cells"]:
        assert set(cell["profiles"]) == {"conservative", "stress"}
        for profile in cell["profiles"].values():
            assert set(profile) == {"full", "early_training", "late_training"}
            assert profile["full"]["fill_count"] >= 0
            assert math.isfinite(profile["full"]["total_return"])


def test_future_row_and_tampered_public_binding_fail_closed() -> None:
    valid = _dataset("BTCUSDT")
    assert len(train._frame(valid, "BTCUSDT")) == train.COUNT
    future = _dataset("BTCUSDT", shift=1)
    with pytest.raises(train.HistoricalTrainingError, match="cutoff"):
        train._frame(future, "BTCUSDT")
    invalid = json.loads(json.dumps(valid))
    invalid["rows"][12]["close"] = "999999"
    with pytest.raises(Exception):
        train._frame(invalid, "BTCUSDT")


def test_no_third_variant_or_downgraded_stress_allowed() -> None:
    base = low.load_manifest(MANIFEST)
    changed = json.loads(json.dumps(base))
    changed["variants"].append({
        "lookback": 10, "entry_deadband": 0.005,
        "min_hold_bars": 1, "exit_cooldown_bars": 0,
    })
    with pytest.raises(train.HistoricalTrainingError, match="manifest"):
        train.evaluate(changed, {})
    changed = json.loads(json.dumps(base))
    changed["execution"]["stress"]["fee_bps"] = 0.0
    with pytest.raises(train.HistoricalTrainingError, match="manifest"):
        train.evaluate(changed, {})
