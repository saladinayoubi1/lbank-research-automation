from __future__ import annotations

import numpy as np
import pandas as pd

import nexus_a7_range_failure_reversal_research as a7


def _signal_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "h4_range": [1.0, 1.0, 1.0, 0.0],
            "h1_vol_ok": [1.0, 1.0, 0.0, 1.0],
            "prior_lo": [100.0, 100.0, 100.0, 100.0],
            "rel_vol": [1.2, 0.8, 1.2, 1.2],
            "atr": [2.0, 2.0, 2.0, 2.0],
            "a7_rv15_ratio": [1.0, 1.0, 1.0, 1.0],
            "a7_h4_vol_ratio": [1.0, 1.0, 1.0, 1.0],
            "low": [99.0, 99.0, 99.0, 99.0],
            "close": [101.0, 101.0, 101.0, 101.0],
            "open": [100.5, 100.5, 100.5, 100.5],
        }
    )


def test_a7_signal_requires_range_failure_and_multi_horizon_context():
    signal = a7.signal_for_a7(_signal_frame())
    assert signal.tolist() == [True, False, False, False]


def test_a7_signal_fails_closed_on_extreme_volatility():
    frame = _signal_frame()
    frame.loc[0, "a7_rv15_ratio"] = 2.5
    assert a7.signal_for_a7(frame).tolist()[0] is False
    frame.loc[0, "a7_rv15_ratio"] = 1.0
    frame.loc[0, "a7_h4_vol_ratio"] = 2.0
    assert a7.signal_for_a7(frame).tolist()[0] is False


def test_a7_preregistration_is_uncapped_non_martingale_and_research_only(monkeypatch, tmp_path):
    timestamps = pd.date_range("2026-08-01T00:00:00Z", periods=1000, freq="15min")
    base = pd.DataFrame(
        {
            "timestamp": timestamps,
            "open": 100.0,
            "high": 101.0,
            "low": 99.0,
            "close": 100.5,
            "volume": 10.0,
            "symbol": "BTCUSDT",
            "timeframe": "minute15",
        }
    )
    frames = {}
    for symbol in a7.SYMBOLS:
        frames[(symbol, "minute15")] = base.assign(symbol=symbol)
        h1 = base.iloc[::4].reset_index(drop=True).copy()
        h1["timeframe"] = "hour1"
        frames[(symbol, "hour1")] = h1
        h4 = base.iloc[::16].reset_index(drop=True).copy()
        h4["timeframe"] = "hour4"
        frames[(symbol, "hour4")] = h4

    source = {
        "snapshot_digest": "a" * 64,
        "source_manifest_digest": "b" * 64,
        "dataset_digest": "c" * 64,
        "source_window_start": "2026-08-01",
        "source_window_end": "2026-08-11",
        "data_as_of_ms": 1,
        "symbols": list(a7.SYMBOLS),
        "timeframes": list(a7.TIMEFRAMES),
        "research_only": True,
        "paper_only": True,
        "automatic_strategy_promotion": False,
        "live_trading_authority": False,
    }
    monkeypatch.setattr(a7, "load_verified_recent_surface", lambda *args, **kwargs: (frames, source))

    feature = base.copy()
    feature["decision_at"] = feature["timestamp"] + pd.Timedelta(minutes=15)
    feature["atr"] = 1.0
    feature["h4_range"] = 1.0
    feature["h1_vol_ok"] = 1.0
    feature["prior_lo"] = 99.5
    feature["rel_vol"] = 1.1
    feature["a7_rv15_ratio"] = 1.0
    feature["a7_h4_vol_ratio"] = 1.0
    monkeypatch.setattr(a7, "build_a7_features", lambda own: feature.copy())
    monkeypatch.setattr(
        a7.composite,
        "backtest",
        lambda *args, **kwargs: {
            "net_return_pct": -0.1,
            "net_pnl_usdt": -10.0,
            "max_drawdown_pct": 0.2,
            "closed_round_trips": 3,
            "win_rate_pct": 33.333333,
            "profit_factor": 0.5,
            "profit_factor_status": "AVAILABLE",
            "turnover_usdt": 1000.0,
            "exposure_bar_ratio": 0.1,
            "halted_on_drawdown": False,
            "fee_bps": kwargs["fee_bps"],
            "slippage_bps": kwargs["slip_bps"],
            "trade_count_limit": None,
            "concurrent_risk_model": "one_collateral_backed_net_long_per_symbol;10pct_position_budget",
        },
    )

    report = a7.evaluate(tmp_path, tmp_path, source_sha="d" * 40, now_ms=1)
    assert report["preregistration"]["martingale"] is False
    assert report["preregistration"]["trade_count_limit"] is None
    assert report["historical_july_previously_inspected"] is True
    assert report["recent_window_used_for_selection"] is False
    assert report["research_only"] is True
    assert report["paper_only"] is True
    assert report["automatic_strategy_promotion"] is False
    assert report["derivative_execution_authority"] is False
    assert report["live_trading_authority"] is False
    assert report["owner_500_usdt_profile_touched"] is False
    assert len(report["rows"]) == len(a7.SYMBOLS) * 2
    assert len(report["owner_review_cells"]) == len(a7.SYMBOLS) * 3
    assert report["conclusion"] == "REJECTED_NO_POSITIVE_RECENT_STRESS_CELL"
