"""Independent fill accounting: adversarial bracket/cost/fee and drift tests."""
from copy import deepcopy

import numpy as np
import pandas as pd
import pytest

import nexus_composite_strategy_research as producer
from nexus_composite_fill_oracle import (
    CompositeFillOracleError,
    recompute,
    verify_fills,
)


def _frame(kind="both", length=5):
    t = pd.date_range("2026-01-01", periods=length, freq="15min", tz="UTC")
    open_prices = [100.0] * length
    highs = [100.1] * length
    lows = [99.9] * length
    closes = [100.0] * length
    if kind == "both":
        highs[1], lows[1] = 115., 95.
    elif kind == "target":
        highs[1], lows[1] = 104., 99.9
    elif kind == "gap_stop":
        open_prices[1] = 97.0
        highs[1], lows[1], closes[1] = 97.4, 96.5, 97.0
    elif kind == "trend":
        for j in range(length):
            closes[j] = 100 + j * 0.09
            open_prices[j] = closes[j] - 0.01
            highs[j] = closes[j] + 0.2
            lows[j] = closes[j] - 0.2
    elif kind == "random":
        for j in range(length):
            base = 100 + (j % 7) * 0.34 - (j % 11) * 0.39
            closes[j] = base
            open_prices[j] = base + 0.12
            highs[j] = base + 1.8
            lows[j] = base - 1.6
    return pd.DataFrame({
        "decision_at": t,
        "open": open_prices, "high": highs,
        "low": lows, "close": closes, "atr": np.ones(length),
    })


@pytest.mark.parametrize("kind,length", [
    ("both", 5), ("target", 5), ("gap_stop", 5), ("trend", 105),
    ("random", 3072),
])
@pytest.mark.parametrize("variant", [0, 1])
@pytest.mark.parametrize("fees,slip", [(10, 5), (25, 15)])
def test_independent_decimal_fill_accounting_matches_source_under_stress(
    kind, length, variant, fees, slip,
):
    frame = _frame(kind, length)
    signals = np.zeros(length, dtype=bool)
    if kind == "random":
        signals[::7] = True
    else:
        signals[0] = True
    observed = producer.backtest(
        frame, signals, fee_bps=fees, slip_bps=slip, risk_variant=variant
    )
    result = verify_fills(
        frame, signals, fee_bps=fees, slip_bps=slip, risk_variant=variant,
        observed=observed,
    )
    assert result["decision"] == "PASS_RESEARCH_ONLY"
    assert result["closed_round_trips"] == observed["closed_round_trips"]
    assert result["owner_demo_admission"] is False
    assert result["live_trading_authority"] is False


def test_same_bar_stop_target_conflict_is_adversarial_stop():
    frame = _frame("both")
    signals = [True, False, False, False, False]
    own = recompute(frame, signals, fee_bps=10, slip_bps=5, risk_variant=0)
    exits = [x for x in own["fills"] if x["side"] == "SELL"]
    assert len(exits) == 1
    assert exits[0]["reason"] == "stop"
    assert own["net_pnl_usdt"] < 0


def test_no_trade_is_not_automatically_approved_for_demo():
    frame = _frame("trend", 20)
    signals = np.zeros(20, dtype=bool)
    observed = producer.backtest(
        frame, signals, fee_bps=10, slip_bps=5, risk_variant=0
    )
    row = verify_fills(
        frame, signals, fee_bps=10, slip_bps=5, risk_variant=0,
        observed=observed,
    )
    assert row["closed_round_trips"] == 0
    assert row["owner_demo_admission"] is False


@pytest.mark.parametrize("column,delta", [
    ("net_pnl_usdt", 0.05),
    ("net_return_pct", 0.01),
    ("turnover_usdt", 0.02),
    ("max_drawdown_pct", 0.001),
    ("exposure_bar_ratio", 0.001),
])
def test_independent_oracle_rejects_redigested_mutated_metric(column, delta):
    frame = _frame("random", 200)
    signals = np.zeros(200, dtype=bool)
    signals[::8] = True
    observed = producer.backtest(
        frame, signals, fee_bps=10, slip_bps=5, risk_variant=0,
    )
    forged = deepcopy(observed)
    forged[column] += delta
    with pytest.raises(CompositeFillOracleError, match="mismatch"):
        verify_fills(
            frame, signals, fee_bps=10, slip_bps=5, risk_variant=0,
            observed=forged,
        )


def test_oracle_rejects_trade_count_fee_cost_and_exposure_fraud():
    frame = _frame("both", 5)
    signals = [True, False, False, False, False]
    observed = producer.backtest(
        frame, signals, fee_bps=10, slip_bps=5, risk_variant=0,
    )
    for name, value in [
        ("closed_round_trips", 123),
        ("fee_bps", 0.0),
        ("slippage_bps", 0.0),
        ("halted_on_drawdown", True),
        ("concurrent_risk_model", "unlimited_leverage"),
    ]:
        forged = {**observed, name: value}
        with pytest.raises(CompositeFillOracleError):
            verify_fills(
                frame, signals, fee_bps=10, slip_bps=5, risk_variant=0,
                observed=forged,
            )


def test_nonfinite_and_nonmonotonic_candles_fail_closed():
    frame = _frame("trend", 5)
    frame.loc[2, "high"] = float("nan")
    with pytest.raises(CompositeFillOracleError):
        recompute(frame, [True]*5, fee_bps=10, slip_bps=5, risk_variant=0)
    duplicate_time = _frame("trend", 5)
    duplicate_time.loc[3, "decision_at"] = duplicate_time.loc[2, "decision_at"]
    with pytest.raises(CompositeFillOracleError, match="nonmonotonic"):
        recompute(duplicate_time, [True]*5, fee_bps=10, slip_bps=5, risk_variant=0)


def test_val40_real_entrypoint_refuses_corrupted_engine_numeric_output(
    monkeypatch, tmp_path,
):
    """Exercises VAL-40 default evaluator, not merely direct helper tests.

    Synthetic canonical frames are injected at the market-data boundary;
    no network, demo journal, or QA receipt is involved.
    """
    import canonical_backtest as canonical
    import nexus_canonical_paged_history as history
    import nexus_composite_runtime_requalification as val40
    import product_research_runtime as product

    def _artifact(symbol, tf):
        step = {"minute15": 900_000, "hour1": 3_600_000,
                "hour4": 14_400_000}[tf]
        return {
            "instrument": symbol, "rows": [
                {"open_time_ms": 1_900_000_000_000 + i * step}
                for i in range(65)
            ], "row_count": 65, "binding_sha256": "a" * 64,
        }

    class _FakeRuntime:
        def __init__(self, *args, **kwargs):
            pass

        def fetch_dataset(self, *, symbol, timeframe, limit):
            return _artifact(symbol, timeframe)

    monkeypatch.setattr(product, "ProductResearchRuntime", _FakeRuntime)
    monkeypatch.setattr(
        history, "fetch_verified_15m_window",
        lambda _runtime, *, symbol, limit: _artifact(symbol, "minute15"),
    )
    monkeypatch.setattr(
        canonical, "canonical_ohlcv_frame",
        lambda artifact: (artifact, pd.DataFrame({
            "timestamp": pd.date_range(
                "2026-01-01", periods=65, freq="15min", tz="UTC"
            ),
            "open": np.full(65, 100.), "high": np.full(65, 110.),
            "low": np.full(65, 96.), "close": np.full(65, 100.),
            "volume": np.full(65, 1000.),
        })),
    )
    f = _frame("both", 65)
    monkeypatch.setattr(producer, "build_features",
                        lambda frames, peer_15m=None: f)
    signal = np.zeros(65, dtype=bool)
    signal[0] = True
    monkeypatch.setattr(producer, "signal_for",
                        lambda features, config: signal)
    correct = producer.backtest

    def broken_backtest(*args, **kwargs):
        fake = correct(*args, **kwargs)
        fake["net_pnl_usdt"] += 5
        return fake

    monkeypatch.setattr(producer, "backtest", broken_backtest)
    candidate = {
        "strategy_config": {"mechanism": "structural_pullback", "risk_variant": 0},
        "mechanism": "structural_pullback",
    }
    with pytest.raises(val40.CompositeRuntimeRequalificationError,
                       match="independent fill accounting disagrees"):
        val40._default_evaluator(candidate, "a" * 40, 1_900_000_000_000,
                                 tmp_path)
