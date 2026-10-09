"""Cash-safe, cadence-explicit NEXUS 4h Spot portfolio research regression."""
from __future__ import annotations
import numpy as np
import pandas as pd
import pytest
from bybit_portfolio_search_v3 import (
    exact_backtest, evaluate_development, _candidate_rebalance_mask,
    PortfolioSearchError,
)

def tape():
    t = pd.date_range("2026-09-01", periods=80, freq="4h", tz="UTC")
    close = np.full((80, 2), 100.0)
    return {"timestamps": pd.Series(t), "open": close.copy(), "close": close.copy(),
            "high": close.copy(), "low": close.copy(),
            "symbols": ["btc_usdt", "eth_usdt"]}

PERIOD = {"start": "2026-09-01", "end": "2026-09-14"}
PROFILE = {"initial_cash": 500.0, "fee_bps": 8.0, "slippage_bps": 7.0}

@pytest.mark.parametrize("allocation", [0.5, 1.0])
def test_constant_allocation_without_explicit_schedule_only_enters_and_exits(allocation):
    w = np.zeros((80, 2))
    w[:, 0] = allocation
    r = exact_backtest(tape(), w, PERIOD, PROFILE)
    assert r["fill_count"] == 2
    assert r["rebalance_event_count"] == 1
    assert r["minimum_cash_usdt"] >= 0
    assert r["total_return"] < 0  # flat market, only cost

def test_explicit_rebalance_even_when_target_unchanged():
    market = tape()
    market["open"][20:] = 120
    market["close"][20:] = 120
    w = np.zeros((80, 2)); w[:, 0] = 0.5
    m = np.zeros(80, dtype=bool); m[0] = True; m[20] = True
    passive = exact_backtest(market, w, PERIOD, PROFILE)
    scheduled = exact_backtest(market, w, PERIOD, PROFILE, rebalance_mask=m)
    assert passive["fill_count"] == 2
    assert passive["rebalance_event_count"] == 1
    assert scheduled["fill_count"] == 3
    assert scheduled["rebalance_event_count"] == 2
    assert scheduled["minimum_cash_usdt"] >= 0

def test_all_cash_funded_two_asset_100_percent_allocation():
    w = np.full((80, 2), 0.5)
    r = exact_backtest(tape(), w, PERIOD, PROFILE)
    assert r["fill_count"] == 4
    assert r["minimum_cash_usdt"] >= 0
    assert r["total_fees"] > 0

def test_closed_bar_decision_uses_only_next_open():
    market = tape()
    market["open"][9:] = 120
    market["close"][9:] = 120
    w = np.zeros((80, 2)); w[8:, 0] = 0.5
    r = exact_backtest(market, w, PERIOD, PROFILE)
    assert r["fill_count"] == 2
    assert -.01 < r["total_return"] < 0
    assert r["minimum_cash_usdt"] >= 0

def test_last_bar_signal_is_not_executable():
    w = np.zeros((80, 2)); w[-1, 0] = 0.5
    r = exact_backtest(tape(), w, PERIOD, PROFILE)
    assert r["fill_count"] == 0
    assert r["total_fees"] == 0

@pytest.mark.parametrize("bad", [-0.1, 1.01, np.nan])
def test_disallow_leverage_short_and_nonfinite(bad):
    w = np.zeros((80, 2)); w[:, 0] = bad
    with pytest.raises(PortfolioSearchError):
        exact_backtest(tape(), w, PERIOD, PROFILE)

@pytest.mark.parametrize("bad_mask", [np.zeros(80, dtype=int), np.zeros(79, dtype=bool)])
def test_explicit_mask_is_boolean_full_dataset(bad_mask):
    w = np.zeros((80, 2)); w[:, 0] = 0.5
    with pytest.raises(PortfolioSearchError):
        exact_backtest(tape(), w, PERIOD, PROFILE, rebalance_mask=bad_mask)

def test_folds_pass_same_global_rebalance_schedule():
    market=tape();market["open"][20:]=120;market["close"][20:]=120
    w=np.zeros((80,2));w[:,0]=0.5
    mask=np.zeros(80,dtype=bool);mask[20]=True
    _, rows=evaluate_development(market,w,[PERIOD],"exact",profile=PROFILE,rebalance_mask=mask)
    assert rows[0]["rebalance_event_count"]==2
    assert rows[0]["fill_count"]==3

def test_global_candidate_cadence_matches_weight_hold_origin():
    m=_candidate_rebalance_mask(40,{"params":{"rebalance_days":2}})
    assert np.flatnonzero(m).tolist()==[0,12,24,36]

@pytest.mark.parametrize(
    "invalid_field,invalid_value",
    [("fee_bps", 10000.0), ("fee_bps", 12000.0),
     ("slippage_bps", 10000.0), ("slippage_bps", 12000.0)],
)
def test_reject_costs_that_could_make_sells_have_negative_proceeds(invalid_field, invalid_value):
    profile = dict(PROFILE)
    profile[invalid_field] = invalid_value
    target = np.ones((80, 2)) * 0.5
    with pytest.raises(PortfolioSearchError, match="Invalid cash or cost profile"):
        exact_backtest(tape(), target, PERIOD, profile)


def test_execution_model_receipt_binds_exact_code_bytes_without_paper_authority():
    import hashlib
    from pathlib import Path
    import bybit_portfolio_search_v3 as engine

    receipt = engine.execution_model_receipt()
    assert receipt["schema"] == "nexus.spot-cash-next-open-scheduled.v2"
    assert receipt["module_sha256"] == hashlib.sha256(
        Path(engine.__file__).resolve().read_bytes()
    ).hexdigest()
    assert receipt["decision_time"] == "prior_closed_4h_bar"
    assert receipt["execution_time"] == "next_4h_open"
    assert receipt["historical_report_compatibility"] == "explicit_replay_required"
    assert receipt["automatic_paper_promotion"] is False
    assert receipt["live_trading_authority"] is False
