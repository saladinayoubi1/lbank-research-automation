"""Align the existing portfolio evaluator with the reviewed System Map policy."""
from bybit_portfolio_search_v3 import development_checks, stress_checks, execution_model_receipt


def test_low_frequency_development_uses_return_and_risk_evidence():
    summary = dict(positive_ratio=1.0, median_return=0.08, worst_return=0.03,
                   worst_drawdown=0.06, median_sharpe=1.2, minimum_sharpe=0.8,
                   minimum_fill_count=1)
    gate = dict(minimum_positive_ratio=0.8, minimum_median_return=0.05,
                minimum_worst_return=-0.08, maximum_drawdown=0.22,
                minimum_median_sharpe=0.55, minimum_sharpe=-0.35,
                minimum_fill_count=999)
    checks = development_checks(summary, gate)
    assert all(checks.values())
    assert "fills" not in checks
    assert summary["minimum_fill_count"] == 1


def test_single_asset_round_trip_has_no_arbitrary_fill_veto():
    result = dict(total_return=0.05, max_drawdown=0.03, sharpe=0.8,
                  fill_count=2, asset_fill_counts=[2, 0])
    gate = dict(minimum_total_return=0.02, maximum_drawdown=0.20,
                minimum_sharpe=0.25, minimum_fill_count=4,
                minimum_asset_fill_count=1)
    checks = stress_checks(result, gate)
    assert all(checks.values())
    assert set(checks) == {"return", "drawdown", "sharpe"}
    assert result["fill_count"] == 2 and result["asset_fill_counts"] == [2, 0]


def test_return_drawdown_and_sharpe_vetoes_remain_with_large_counts():
    result = dict(total_return=-0.5, max_drawdown=0.7, sharpe=-2,
                  fill_count=10000, asset_fill_counts=[5000, 5000])
    gate = dict(minimum_total_return=0.02, maximum_drawdown=0.20,
                minimum_sharpe=0.25, minimum_fill_count=4,
                minimum_asset_fill_count=1)
    assert stress_checks(result, gate) == {"return": False, "drawdown": False, "sharpe": False}


def test_source_bound_receipt_declares_trade_count_policy():
    receipt = execution_model_receipt()
    assert receipt["arbitrary_minimum_trade_count_gate"] is False
    assert receipt["trade_count_policy"] == "diagnostic_only"
