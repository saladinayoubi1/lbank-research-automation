from copy import deepcopy

import pytest

from performance_analytics import PerformanceAnalyticsError, analyze_performance


BINDING = "a" * 64


def trade(
    trade_id,
    opened,
    closed,
    gross,
    fees,
    *,
    regime="RANGE",
    entry_notional="100",
    exit_notional="100",
):
    return {
        "trade_id": trade_id,
        "opened_at_ms": opened,
        "closed_at_ms": closed,
        "gross_pnl": gross,
        "fees": fees,
        "entry_notional": entry_notional,
        "exit_notional": exit_notional,
        "regime": regime,
    }


def sample_trades():
    return [
        trade("t1", 1_000, 2_000, "100", "10", regime="TREND_UP"),
        trade("t2", 2_000, 3_000, "-50", "5", regime="TREND_UP"),
        trade("t3", 3_000, 4_000, "-25", "5", regime="RANGE"),
        trade("t4", 4_000, 5_000, "50", "5", regime="RANGE"),
    ]


def windows():
    return [
        {"window_id": "w1", "score": "0.8", "parameters": {"lookback": "5", "threshold": "0.01"}},
        {"window_id": "w2", "score": "0.6", "parameters": {"lookback": "7", "threshold": "0.02"}},
    ]


def test_advanced_metrics_are_deterministic_replayable_and_bound():
    first = analyze_performance(
        source_binding_sha256=BINDING,
        initial_equity="1000",
        trades=sample_trades(),
        evaluation_windows=windows(),
    )
    second = analyze_performance(
        source_binding_sha256=BINDING,
        initial_equity="1000",
        trades=deepcopy(sample_trades()),
        evaluation_windows=deepcopy(windows()),
    )
    assert first == second
    assert first["source_binding_sha256"] == BINDING
    assert first["paper_only"] is True
    assert first["analytics_authority"] is False
    assert first["promotion_authority"] is False
    assert first["trade_count"] == 4
    assert first["final_equity"] == "1050.00000000"
    assert first["net_pnl"] == "50.00000000"
    assert first["win_rate"] == "0.500000"
    assert first["profit_factor"] == "1.58823529"
    assert first["expectancy"] == "12.50000000"
    assert first["max_drawdown_pct"] == "7.798165"
    assert first["drawdown_duration_trades"] == 3
    assert first["tail_loss_95_mean"] == "55.00000000"
    assert first["max_consecutive_losses"] == 2
    assert len(first["analytics_sha256"]) == 64


def test_turnover_exposure_regime_and_parameter_stability_are_explicit():
    result = analyze_performance(
        source_binding_sha256=BINDING,
        initial_equity="1000",
        trades=sample_trades(),
        evaluation_windows=windows(),
    )
    assert result["turnover_ratio"] == "0.774818"
    assert result["exposure_ratio"] == "1.000000"
    assert result["regime_breakdown"]["TREND_UP"]["trade_count"] == 2
    assert result["regime_breakdown"]["TREND_UP"]["net_pnl"] == "35.00000000"
    assert result["regime_breakdown"]["RANGE"]["net_pnl"] == "15.00000000"
    stability = result["parameter_stability"]
    assert stability["status"] == "MEASURED"
    assert stability["score_mean"] == "0.70000000"
    assert stability["score_stddev"] == "0.10000000"
    assert stability["score_range"] == "0.20000000"
    assert stability["parameter_ranges"] == {
        "lookback": "2.00000000",
        "threshold": "0.01000000",
    }


def test_no_windows_is_truthfully_not_applicable():
    result = analyze_performance(
        source_binding_sha256=BINDING,
        initial_equity="1000",
        trades=sample_trades(),
    )
    assert result["parameter_stability"] == {
        "status": "NOT_APPLICABLE",
        "reason_code": "NO_EVALUATION_WINDOWS",
    }


def test_no_losses_has_explicit_infinite_profit_factor_and_zero_tail_loss():
    result = analyze_performance(
        source_binding_sha256=BINDING,
        initial_equity="1000",
        trades=[trade("t1", 1_000, 2_000, "10", "1")],
    )
    assert result["profit_factor"] == "INF"
    assert result["tail_loss_95_mean"] == "0"
    assert result["max_consecutive_losses"] == 0


@pytest.mark.parametrize(
    ("trades", "message"),
    [
        ([trade("t1", 1_000, 2_000, 10.0, "1")], "floating point"),
        ([trade("t1", 1_000, 2_000, "10", "-1")], "non-negative"),
        ([trade("t1", 2_000, 1_000, "10", "1")], "timestamps"),
        (
            [trade("same", 1_000, 2_000, "10", "1"), trade("same", 2_000, 3_000, "10", "1")],
            "duplicate trade_id",
        ),
        (
            [trade("t1", 1_000, 3_000, "10", "1"), trade("t2", 1_500, 2_500, "10", "1")],
            "strictly ordered",
        ),
    ],
)
def test_invalid_trade_inputs_fail_closed(trades, message):
    with pytest.raises(PerformanceAnalyticsError, match=message):
        analyze_performance(
            source_binding_sha256=BINDING,
            initial_equity="1000",
            trades=trades,
        )


def test_unknown_fields_and_unbounded_parameter_windows_fail_closed():
    widened = sample_trades()
    widened[0]["live_order_id"] = "no"
    with pytest.raises(PerformanceAnalyticsError, match="schema mismatch"):
        analyze_performance(
            source_binding_sha256=BINDING,
            initial_equity="1000",
            trades=widened,
        )

    bad_windows = windows()
    bad_windows[1]["parameters"] = {"different": "1"}
    with pytest.raises(PerformanceAnalyticsError, match="parameter names"):
        analyze_performance(
            source_binding_sha256=BINDING,
            initial_equity="1000",
            trades=sample_trades(),
            evaluation_windows=bad_windows,
        )


def test_non_positive_equity_path_is_rejected():
    with pytest.raises(PerformanceAnalyticsError, match="non-positive"):
        analyze_performance(
            source_binding_sha256=BINDING,
            initial_equity="100",
            trades=[trade("wipe", 1_000, 2_000, "-100", "1")],
        )
