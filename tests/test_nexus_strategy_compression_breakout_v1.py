"""Adversarial contracts for research-only, source-pinned strategy discovery."""
from __future__ import annotations

from copy import deepcopy

import numpy as np
import pandas as pd
import pytest

from research.strategy_frontier import compression_breakout_v1 as subject


def synthetic(n=260):
    # A stable narrow range, a breakout, and a later below-low exit.
    base = np.full(n, 100.0)
    base[:80] = 100 + np.sin(np.arange(80) / 2) * 2.0
    base[80:160] = 100 + np.sin(np.arange(80, 160) / 3) * .05
    base[160:200] = np.linspace(101, 110, 40)
    base[200:] = np.linspace(110, 95, n - 200)
    return pd.DataFrame({
        "open": base, "high": base + .1, "low": base - .1, "close": base,
        "timestamp": pd.date_range("2022-12-01", periods=n, freq="15min", tz="UTC"),
        "volume": np.ones(n), "symbol": ["btc_usdt"] * n,
        "timeframe": ["minute15"] * n,
    })


def test_close_confirmation_cannot_read_future_data():
    frame = synthetic()
    config = subject.ARMS[1]
    original = subject.targets(frame, config)
    altered = frame.copy(deep=True)
    altered.loc[205:, "close"] = altered.loc[205:, "close"] * 2
    altered.loc[205:, "high"] = altered.loc[205:, "high"] * 3
    assert np.array_equal(original[:205], subject.targets(altered, config)[:205])
    assert set(original) <= {0, 1}
    assert original[:80].sum() == 0


def test_unregistered_parameters_are_rejected():
    frame = synthetic()
    modified = dict(subject.ARMS[0])
    modified["entry_bars"] = True
    with pytest.raises(ValueError, match="invalid preregistered"):
        subject.targets(frame, modified)
    modified = dict(subject.ARMS[0])
    modified["future_price"] = 1
    with pytest.raises(ValueError, match="unexpected"):
        subject.targets(frame, modified)


def test_next_open_only_and_forced_last_close():
    frame = pd.DataFrame({
        "open": [100., 100., 105., 104., 102.],
        "close": [100., 101., 102., 103., 99.],
    })
    # A close at bar 1 may execute at bar 2 open, never at bar 1 open.
    signal = np.array([0, 1, 1, 1, 1], dtype=np.int8)
    result = subject.simulate(frame, signal, 0, 5, 0, 0)
    assert result["entries"] == 1
    assert result["closed_roundtrips"] == 1
    assert result["forced_end_exits"] == 1
    assert result["net_pnl_usdt"] < 0
    short = subject.simulate(frame, np.array([0, 0, 0, 0, 1], dtype=np.int8), 0, 5, 0, 0)
    assert short["entries"] == 0
    assert short["net_pnl_usdt"] == 0


def test_both_sources_are_required_and_inspected_history_not_promoted(monkeypatch):
    monkeypatch.setattr(subject, "BARS", 260)
    btc = synthetic()
    eth = synthetic().assign(symbol="eth_usdt")
    with pytest.raises(ValueError, match="both exact physical"):
        subject.evaluate({"BTCUSDT": btc}, {})
    result = subject.evaluate({"BTCUSDT": btc, "ETHUSDT": eth},
                              {"BTCUSDT": "a" * 64, "ETHUSDT": "b" * 64})
    assert len(result["arms"]) == 4
    assert subject.digest({k: v for k, v in result.items() if k != "result_sha256"}) == result["result_sha256"]
    assert all(set(v["per_symbol"]) == {"BTCUSDT", "ETHUSDT"} for v in result["arms"])
    assert result["scope"] == "HISTORICAL_INSPECTED_EXPLORATORY_ONLY"
    assert result["paper_eligible"] is False
    assert result["live_enabled"] is False
    assert result["actual_orders"] == 0
    tampered = deepcopy(result)
    tampered["arms"][0]["training_net_pnl_both_usdt"] += 10
    assert subject.digest({k: v for k, v in tampered.items() if k != "result_sha256"}) != result["result_sha256"]


def test_source_hash_tamper_is_hard_failure(tmp_path):
    base = tmp_path / "bybit_market"
    for symbol, (folder, _) in subject.EXPECTED.items():
        location = base / folder
        location.mkdir(parents=True)
        (location / "minute15.parquet").write_bytes(b"not-the-verified-archive")
    with pytest.raises(ValueError, match="byte hash changed"):
        subject.read_archive(tmp_path)
