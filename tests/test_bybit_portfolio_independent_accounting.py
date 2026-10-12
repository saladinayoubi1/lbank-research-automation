"""Independent closed-form accounting and complete scheduled search acceptance."""
from decimal import Decimal, localcontext
import hashlib
import json

import numpy as np
import pandas as pd
import pytest

import bybit_portfolio_search_v3 as engine
import bybit_portfolio_search_v3_scheduled as scheduled


def test_full_allocation_round_trip_matches_decimal_cash_oracle():
    timestamps = pd.Series(pd.date_range("2026-01-01", periods=60, freq="4h", tz="UTC"))
    for allocation in (0.25, 0.5, 1.0):
        prices = np.full((60, 2), 100.0)
        prices[-1, 0] = 120.0
        market = dict(timestamps=timestamps, open=prices, close=prices)
        weights = np.zeros((60, 2)); weights[:, 0] = allocation
        result = engine.exact_backtest(market, weights,
            dict(start="2026-01-01", end="2026-01-11"),
            dict(initial_cash=500.0, fee_bps=8.0, slippage_bps=7.0))
        with localcontext() as ctx:
            ctx.prec = 50
            cash, fee, slip = Decimal(500), Decimal("0.0008"), Decimal("0.0007")
            quantity = min(cash * Decimal(str(allocation)) / Decimal(100),
                           cash / (Decimal(100) * (1+slip) * (1+fee)))
            buy = quantity * Decimal(100) * (1+slip)
            sell = quantity * Decimal(120) * (1-slip)
            final = cash - buy*(1+fee) + sell*(1-fee)
            expected_return = float(final/cash - 1)
            expected_fees = float((buy+sell)*fee)
        assert result["total_return"] == pytest.approx(expected_return, abs=1e-12)
        assert result["total_fees"] == pytest.approx(expected_fees, abs=1e-12)
        assert result["fill_count"] == 2
        assert result["minimum_cash_usdt"] >= 0


def test_scheduled_full_search_forwards_global_union_and_source_receipt(tmp_path, monkeypatch):
    # Real candidate enumeration, construction, ranking, exact folds, stress and
    # report persistence; only disk market loading is replaced by bounded data.
    timestamp = pd.Series(pd.date_range("2026-01-01", periods=360, freq="4h", tz="UTC"))
    x = np.arange(360)
    close = np.column_stack([100*np.exp(.001*x + .002*np.sin(x)),
                             100*np.exp(.0003*x + .003*np.cos(x))])
    market = dict(timestamps=timestamp, open=close.copy(), close=close,
                  high=close*1.01, low=close*.99, symbols=["btc_usdt", "eth_usdt"])
    monkeypatch.setattr(engine, "load_market", lambda *_: market)
    calls = []
    canonical = engine.exact_backtest
    def observed(*args, **kwargs):
        calls.append(kwargs["rebalance_mask"].copy())
        return canonical(*args, **kwargs)
    monkeypatch.setattr(engine, "exact_backtest", observed)
    gates = dict(minimum_positive_ratio=0, minimum_median_return=-1,
                 minimum_worst_return=-1, maximum_drawdown=1,
                 minimum_median_sharpe=-100, minimum_sharpe=-100,
                 minimum_fill_count=999999)
    stress = dict(minimum_total_return=-1, maximum_drawdown=1,
                  minimum_sharpe=-100, minimum_fill_count=999999,
                  minimum_asset_fill_count=999999)
    cfg = dict(experiment_id="bounded_full_search_qa", symbols=market["symbols"],
        dataset=dict(dataset_root="unused", archive_sha256="a"*64),
        execution=dict(conservative=dict(initial_cash=500, fee_bps=8, slippage_bps=7),
                       stress=dict(initial_cash=500, fee_bps=16, slippage_bps=14)),
        development_folds=[dict(start="2026-01-03", end="2026-01-22"),
                           dict(start="2026-01-23", end="2026-02-11")],
        development_gate=gates, recent_stress_period=dict(start="2026-02-12", end="2026-03-02"),
        recent_stress_gate=dict(conservative=stress, stress=stress),
        search=dict(top_exact=6, ensemble_size=6,
            risk=dict(vol_days=[1], target_vol=[.15], rebalance_days=[2,3], quantum=.05),
            dual_rotation=dict(lookback_sets=[[1]], absolute_days=[1], ma_filter_days=[0],
                               minimum_absolute_return=[0], allocation=["winner"]),
            trend_risk_parity=dict(lookback_sets=[[1]], vote_threshold=[.5], ma_filter_days=[0]),
            relative_breakout=dict(entry_days=[2], exit_days=[1], ma_filter_days=[0], allocation=["winner"])))
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps(cfg), encoding="utf-8")
    report = scheduled.base.run_search(manifest, tmp_path / "result")
    assert report["summary"]["candidate_count"] == 6
    assert len(calls) == 16  # six finalists x two folds, ensemble x two, two stress
    mask2 = np.arange(360) % 12 == 0
    mask3 = np.arange(360) % 18 == 0
    assert any(np.array_equal(mask, mask2) for mask in calls[:12])
    assert any(np.array_equal(mask, mask3) for mask in calls[:12])
    assert np.array_equal(calls[12], mask2 | mask3)
    assert np.array_equal(calls[13], mask2 | mask3)
    selected = report["selected_strategy"]
    expected = mask2 | mask3 if selected["type"] == "median_ensemble" else (
        mask2 if selected["params"]["rebalance_days"] == 2 else mask3)
    assert all(np.array_equal(mask, expected) for mask in calls[14:])
    assert all(row["minimum_cash_usdt"] >= 0 for row in report["recent_stress_results"].values())
    assert "fills" not in selected["development_checks"]
    assert not report["summary"]["automatic_paper_forward_started"]
    assert not report["summary"]["live_trading_enabled"]
    assert report["experiment_manifest_sha256"] == hashlib.sha256(manifest.read_bytes()).hexdigest()
    assert json.loads((tmp_path/"result"/"portfolio_search_v3.json").read_text()) == report
