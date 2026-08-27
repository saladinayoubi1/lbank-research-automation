from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

import nexus_multitimeframe_strategy_discovery as discovery


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "experiments" / "nexus_multitimeframe_strategy_discovery_v1.json"


def _frame(symbol: str, timeframe: str, *, rows: int = 220, holdout_shock: float = 0.0) -> pd.DataFrame:
    index = np.arange(rows, dtype=float)
    base = 100.0 + 0.08 * index + 2.5 * np.sin(index / 7.0) + 0.9 * np.sin(index / 2.7)
    split = int(rows * 0.7)
    if holdout_shock:
        base[split:] = base[split:] * (1.0 + holdout_shock * np.linspace(0.0, 1.0, rows - split))
    open_ = base * (1.0 + 0.0005 * np.sin(index / 5.0))
    high = np.maximum(open_, base) * 1.004
    low = np.minimum(open_, base) * 0.996
    return pd.DataFrame({
        "timestamp": pd.date_range("2025-01-01", periods=rows, freq="15min", tz="UTC"),
        "open": open_,
        "high": high,
        "low": low,
        "close": base,
        "volume": 1000.0 + index,
        "symbol": symbol,
        "timeframe": timeframe,
    })


def _archive(root: Path, *, holdout_shock: float = 0.0) -> None:
    for symbol in discovery.APPROVED_SYMBOLS:
        for timeframe in discovery.APPROVED_TIMEFRAMES:
            path = root / "bybit_market" / symbol / f"{timeframe}.parquet"
            path.parent.mkdir(parents=True, exist_ok=True)
            shock = holdout_shock if symbol == "ETHUSDT" else 0.0
            _frame(symbol, timeframe, holdout_shock=shock).to_parquet(path, index=False)


def _manifest(dataset_root: Path) -> dict:
    value = json.loads(MANIFEST.read_text(encoding="utf-8"))
    value["dataset"]["dataset_root"] = str(dataset_root)
    return value


def test_repository_manifest_is_bounded_and_paper_only() -> None:
    value = discovery.load_manifest(MANIFEST)
    assert value["symbols"] == ["BTCUSDT", "ETHUSDT"]
    assert value["timeframes"] == ["minute15", "hour1", "hour4"]
    assert value["families"] == ["momentum", "trend_breakout", "mean_reversion"]
    assert sum(len(rows) for rows in value["variants"].values()) <= 72
    assert value["authority"]["research_only"] is True
    assert value["authority"]["paper_only"] is True
    assert value["authority"]["live_trading_authority"] is False
    assert value["authority"]["automatic_strategy_promotion"] is False


def test_locked_holdout_cannot_change_training_selected_variant(tmp_path: Path) -> None:
    baseline_root = tmp_path / "baseline"
    shocked_root = tmp_path / "shocked"
    _archive(baseline_root, holdout_shock=0.0)
    _archive(shocked_root, holdout_shock=-0.45)

    baseline = discovery.discover(_manifest(baseline_root))
    shocked = discovery.discover(_manifest(shocked_root))

    baseline_selected = {
        (row["timeframe"], row["family"]): row["selected_variant_id"]
        for row in baseline["cells"]
    }
    shocked_selected = {
        (row["timeframe"], row["family"]): row["selected_variant_id"]
        for row in shocked["cells"]
    }
    assert baseline_selected == shocked_selected
    assert all(row["selection_source"] == "training_only" for row in baseline["cells"])
    assert baseline["automatic_strategy_promotion"] is False
    assert shocked["live_trading_authority"] is False


def test_target_generation_has_no_future_leakage() -> None:
    frame = _frame("BTCUSDT", "minute15")
    cut = 150
    configs = {
        "momentum": {"lookback": 12, "entry_threshold": 0.002},
        "trend_breakout": {"entry_lookback": 20, "exit_lookback": 10},
        "mean_reversion": {"lookback": 20, "entry_z": -1.5, "exit_z": 0.0},
    }
    mutated = frame.copy()
    mutated.loc[cut:, ["open", "high", "low", "close"]] *= 1.8
    for family, config in configs.items():
        first = discovery.generate_targets(frame, family, config)
        second = discovery.generate_targets(mutated, family, config)
        pd.testing.assert_series_equal(first.iloc[:cut], second.iloc[:cut])


def test_archive_identity_substitution_fails_closed(tmp_path: Path) -> None:
    root = tmp_path / "archive"
    _archive(root)
    path = root / "bybit_market" / "BTCUSDT" / "hour1.parquet"
    frame = pd.read_parquet(path)
    frame["symbol"] = "ETHUSDT"
    frame.to_parquet(path, index=False)

    with pytest.raises(discovery.MultiTimeframeDiscoveryError, match="identity mismatch"):
        discovery.discover(_manifest(root))


def test_verifier_rejects_tampered_research_proposal(tmp_path: Path) -> None:
    root = tmp_path / "archive"
    _archive(root)
    result = discovery.discover(_manifest(root))
    verification = discovery.verify_discovery(result)
    assert verification["decision"] == "pass"
    assert result["research_only"] is True
    assert result["live_trading_authority"] is False

    tampered = deepcopy(result)
    tampered["automatic_strategy_promotion"] = True
    rejected = discovery.verify_discovery(tampered)
    assert rejected["decision"] == "reject"


def test_run_persists_verified_research_only_queue(tmp_path: Path) -> None:
    root = tmp_path / "archive"
    output = tmp_path / "output"
    _archive(root)
    manifest = _manifest(root)
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    result = discovery.run(manifest_path, output)
    queue = json.loads((output / "research_proposals.json").read_text(encoding="utf-8"))
    verification = json.loads((output / "verification.json").read_text(encoding="utf-8"))

    assert verification["decision"] == "pass"
    assert queue["automatic_strategy_promotion"] is False
    assert queue["live_trading_authority"] is False
    assert queue["source_discovery_digest"] == result["discovery_digest"]
    assert all(row["proposal_state"] == "RESEARCH_PROPOSAL" for row in queue["proposals"])
