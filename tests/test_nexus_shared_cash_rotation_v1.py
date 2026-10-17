"""Adversarial causal, no-borrowing, next-open and friction tests for shared-cash research."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

PATH = Path(__file__).resolve().parents[1] / "research/shared_cash_rotation/rotation_v1.py"
spec = importlib.util.spec_from_file_location("shared_cash_rotation_v1", PATH)
r = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(r)


def fake(n=256):
    t = pd.Series(pd.date_range("2025-01-01", periods=n, freq="15min", tz="UTC"))
    a = np.arange(n, dtype=float)
    btc = np.full(n, 100.0)
    eth = 100.0 * 1.001 ** a
    values = {
        "BTC": {"open": btc.copy(), "close": btc.copy(), "low": btc.copy(), "high": btc.copy()},
        "ETH": {"open": eth.copy(), "close": eth.copy(), "low": eth.copy(), "high": eth.copy()},
    }
    return values, t


def test_entry_only_at_next_open_of_closed_signal():
    d, t = fake()
    x = r.replay(d, t, 100, 242, fee_bps=0.0, slip_bps=0.0)
    buys = [e for e in x["events"] if e["event"] == "BUY"]
    assert buys and buys[0] == {"index": 100, "event": "BUY", "symbol": "ETH"}
    assert x["trades"][0]["entry_index"] == 100
    assert x["ending_cash_usdt"] > 500.0
    assert x["round_trips"] == len(x["trades"])
    assert x["events"][-1]["event"] == "SELL"
    assert x["trades"][-1]["exit_index"] == 241
    assert x["live_trading_authority"] is False if "live_trading_authority" in x else True


def test_future_candles_never_change_earlier_entry_rank():
    d, t = fake()
    baseline = r.rank_at_closed_bar(d, 99)
    assert baseline == "ETH"
    d["BTC"]["close"][100:] *= 10
    d["ETH"]["close"][100:] *= 0.1
    assert r.rank_at_closed_bar(d, 99) == baseline


def test_stop_can_close_on_entry_bar_with_conservative_stop_first():
    d, t = fake()
    d["ETH"]["low"][100] = d["ETH"]["open"][100] * 0.90
    x = r.replay(d, t, 100, 196, fee_bps=10, slip_bps=5)
    assert x["trades"][0]["exit_index"] == 100
    assert x["trades"][0]["exit_reason"] == "hard_stop_stop_first"
    assert x["trades"][0]["net_pnl_usdt"] < 0
    assert x["ending_cash_usdt"] <= 500.0 or x["round_trips"] > 1


def test_fee_stress_does_not_outperform_same_identical_fills():
    d, t = fake()
    base = r.replay(d, t, 100, 200, fee_bps=10, slip_bps=5)
    stress = r.replay(d, t, 100, 200, fee_bps=25, slip_bps=15)
    assert stress["net_pnl_usdt"] < base["net_pnl_usdt"]
    assert base["fee_paid_usdt"] > 0


def test_sell_before_buy_shared_cash_never_borrows():
    d, t = fake(290)
    # From index 148, BTC return leads 16-bar ETH and its 48-bar market guard.
    for i in range(126, 290):
        d["BTC"]["close"][i] = 100.0 * (1.004 ** (i - 125))
        d["BTC"]["open"][i] = d["BTC"]["close"][i]
        d["BTC"]["low"][i] = d["BTC"]["close"][i]
        d["BTC"]["high"][i] = d["BTC"]["close"][i]
    a = r.replay(d, t, 100, 258, fee_bps=10, slip_bps=5)
    switches = [i for i in range(len(a["events"]) - 1)
                if a["events"][i]["event"] == "SELL" and
                a["events"][i+1]["event"] == "BUY" and
                a["events"][i]["index"] == a["events"][i+1]["index"]]
    assert switches
    assert a["switch_count"] == len(switches)
    assert all(t["entry_spend_usdt"] >= 0 for t in a["trades"])
    assert a["ending_cash_usdt"] >= 0


def test_no_short_and_terminal_released_even_if_always_rising():
    d, t = fake()
    x = r.replay(d, t, 100, 220, fee_bps=0, slip_bps=0)
    assert sum(e["event"] == "BUY" for e in x["events"]) == x["round_trips"]
    assert sum(e["event"] == "SELL" for e in x["events"]) == x["round_trips"]
    assert x["trades"][-1]["exit_reason"] == "terminal"


def test_missing_aligned_peer_rejected():
    n = 192
    t = pd.Series(pd.date_range("2025-01-01", periods=n, freq="15min", tz="UTC"))
    f = pd.DataFrame({"timestamp": t, "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0})
    a, b = f.copy(), f.copy()
    b.loc[100, "timestamp"] += pd.Timedelta(minutes=15)
    with pytest.raises(r.RotationResearchError, match="alignment"):
        r.as_arrays({"BTC": a, "ETH": b})


def test_reject_bad_replay_fees_or_too_short_partition():
    d, t = fake()
    for kwargs in ({"fee_bps": -1, "slip_bps": 0}, {"fee_bps": 0, "slip_bps": float("nan")}):
        with pytest.raises(r.RotationResearchError):
            r.replay(d, t, 100, 220, **kwargs)
    with pytest.raises(r.RotationResearchError):
        r.replay(d, t, 100, 120, fee_bps=0, slip_bps=0)


def test_source_lock_and_trading_authority_declared():
    code = PATH.read_text("utf-8")
    assert "hashlib.sha256(path.read_bytes()).hexdigest()" in code
    assert '"historical_holdouts_already_inspected": True' in code
    assert '"novelty_independently_certified": False' in code
    assert '"automatic_demo_promotion": False' in code
    assert '"live_trading_authority": False' in code
    assert "requests.post(" not in code and "bybit_order" not in code
