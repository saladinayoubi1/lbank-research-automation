from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

import nexus_demo_archive_replay as archive
import nexus_multitimeframe_strategy_discovery as discovery
import nexus_multitimeframe_verified_archive_discovery as verified


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "experiments" / "nexus_multitimeframe_strategy_discovery_v1.json"
ARCHIVE_SYMBOL = {"BTCUSDT": "btc_usdt", "ETHUSDT": "eth_usdt"}
FREQ = {"minute15": "15min", "hour1": "1h", "hour4": "4h"}


def _frame(symbol: str, timeframe: str, rows: int = 220) -> pd.DataFrame:
    index = np.arange(rows, dtype=float)
    close = 100.0 + 0.08 * index + 2.2 * np.sin(index / 7.0) + 0.7 * np.sin(index / 2.9)
    open_ = close * (1.0 + 0.0004 * np.sin(index / 5.0))
    return pd.DataFrame({
        "timestamp": pd.date_range("2025-01-01", periods=rows, freq=FREQ[timeframe], tz="UTC"),
        "open": open_,
        "high": np.maximum(open_, close) * 1.004,
        "low": np.minimum(open_, close) * 0.996,
        "close": close,
        "volume": 1000.0 + index,
        "symbol": ARCHIVE_SYMBOL[symbol],
        "timeframe": timeframe,
    })


def _archive(root: Path) -> None:
    for symbol in discovery.APPROVED_SYMBOLS:
        for timeframe in discovery.APPROVED_TIMEFRAMES:
            path = root / "bybit_market" / ARCHIVE_SYMBOL[symbol] / f"{timeframe}.parquet"
            path.parent.mkdir(parents=True, exist_ok=True)
            _frame(symbol, timeframe).to_parquet(path, index=False)


def _manifest(root: Path, *, digest: str = archive.ARCHIVE_SHA256) -> dict:
    value = json.loads(MANIFEST.read_text(encoding="utf-8"))
    value["dataset"]["dataset_root"] = str(root)
    value["dataset"]["archive_sha256"] = digest
    return value


def test_verified_loader_accepts_historical_namespace_and_normalizes_metadata(tmp_path: Path) -> None:
    _archive(tmp_path)
    frame = verified.load_verified_archive_frame(tmp_path, "BTCUSDT", "minute15")

    assert frame.columns.tolist() == discovery.REQUIRED_COLUMNS
    assert set(frame["symbol"].astype(str)) == {"BTCUSDT"}
    assert set(frame["timeframe"].astype(str)) == {"minute15"}
    assert frame["timestamp"].iloc[0] == pd.Timestamp("2025-01-01T00:00:00Z")


def test_adapter_rejects_nonapproved_archive_digest_before_discovery(tmp_path: Path) -> None:
    _archive(tmp_path)
    value = _manifest(tmp_path, digest="0" * 64)
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(value), encoding="utf-8")

    with pytest.raises(verified.VerifiedArchiveDiscoveryError, match="approved immutable"):
        verified.run(path, tmp_path / "output")


def test_raw_archive_identity_substitution_fails_closed(tmp_path: Path) -> None:
    _archive(tmp_path)
    path = tmp_path / "bybit_market" / "btc_usdt" / "hour1.parquet"
    frame = pd.read_parquet(path)
    frame["symbol"] = "eth_usdt"
    frame.to_parquet(path, index=False)

    with pytest.raises(verified.VerifiedArchiveDiscoveryError, match="archive symbol identity mismatch"):
        verified.load_verified_archive_frame(tmp_path, "BTCUSDT", "hour1")


def test_verified_adapter_runs_existing_discovery_without_widening_authority(tmp_path: Path) -> None:
    archive_root = tmp_path / "archive"
    output = tmp_path / "output"
    _archive(archive_root)
    value = _manifest(archive_root)
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(value), encoding="utf-8")

    result = verified.run(path, output)

    assert result["dataset_archive_sha256"] == archive.ARCHIVE_SHA256
    assert len(result["cells"]) == 9
    assert result["research_only"] is True
    assert result["paper_only"] is True
    assert result["live_trading_authority"] is False
    assert result["automatic_strategy_promotion"] is False
    persisted = json.loads((output / "multitimeframe_strategy_discovery.json").read_text())
    assert discovery.verify_discovery(persisted)["decision"] == "pass"
