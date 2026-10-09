"""Scientific-claim denial and physically source-bound QA coverage checks."""
from copy import deepcopy

import pytest

from nexus_composite_evidence_adequacy import (
    CompositeObservationError,
    MIN_REVIEW_DAYS,
    assess,
)


def _profile(name, *, trades=2):
    return {
        "profile": name,
        "closed_round_trips": trades,
        "net_pnl_usdt": 20.0 if trades else 0.0,
        "net_return_pct": 0.2 if trades else 0.0,
        "max_drawdown_pct": 0.4,
        "turnover_usdt": 1000.0 if trades else 0.0,
        "exposure_bar_ratio": 0.02 if trades else 0.0,
        "win_rate_pct": 50.0 if trades else None,
        "fee_bps": 10.0 if name == "conservative" else 25.0,
        "slippage_bps": 5.0 if name == "conservative" else 15.0,
        "halted_on_drawdown": False,
        "trade_count_limit": None,
    }


def _sample(*, minute_bars=3000, trades=2):
    intervals = {"minute15": 900_000, "hour1": 3_600_000, "hour4": 14_400_000}
    rows = []
    for symbol in ("BTCUSDT", "ETHUSDT"):
        datasets = {}
        for timeframe, step in intervals.items():
            count = minute_bars if timeframe == "minute15" else 1000
            end = 1_900_000_000_000 // step * step
            datasets[timeframe] = {
                "timeframe": timeframe,
                "row_count": count,
                "first_open_time_ms": end - (count - 1) * step,
                "last_open_time_ms": end,
            }
        rows.append({
            "symbol": symbol,
            "datasets": datasets,
            "profiles": [_profile("conservative", trades=trades),
                         _profile("stress", trades=trades)],
        })
    return {"evaluations": rows}


def test_10_day_window_is_inconclusive_even_if_profitable():
    report = assess(_sample(minute_bars=1000))
    assert report["decision"] == "INCONCLUSIVE"
    assert report["reason_codes"] == ["INSUFFICIENT_OBSERVATION_COVERAGE"]
    assert all(days < MIN_REVIEW_DAYS for days in
               report["actual_contiguous_window_days"].values())
    assert report["owner_demo_admission_allowed"] is False
    assert report["statistical_significance_established"] is False


def test_30_day_coverage_only_allows_independent_qa_no_demo_claim():
    report = assess(_sample())
    assert report["decision"] == "READY_FOR_INDEPENDENT_QA_ONLY"
    assert report["historical_minimum_trade_count"] is None
    assert report["conservative_closed_trades_by_symbol"] == {
        "BTCUSDT": 2, "ETHUSDT": 2,
    }
    assert report["statistical_significance_established"] is False
    assert report["pristine_prospective_evidence_present"] is False
    assert report["owner_demo_admission_allowed"] is False
    assert report["live_trading_authority"] is False
    assert report == assess(_sample())


def test_long_window_without_trades_does_not_label_strategy_unprofitable():
    report = assess(_sample(trades=0))
    assert report["decision"] == "INCONCLUSIVE"
    assert report["reason_codes"] == ["NO_CLOSED_TRADES_IN_OBSERVED_WINDOW"]
    assert report["conservative_closed_trades_by_symbol"] == {
        "BTCUSDT": 0, "ETHUSDT": 0,
    }


@pytest.mark.parametrize(
    "mutate",
    [
        lambda data: data["evaluations"][0]["datasets"]["minute15"].update(
            {"row_count": 1000}
        ),
        lambda data: data["evaluations"][0]["profiles"][0].update(
            {"net_return_pct": 9.9}
        ),
        lambda data: data["evaluations"][1]["profiles"][1].update(
            {"fee_bps": 10.0}
        ),
        lambda data: data["evaluations"][0]["profiles"][0].update(
            {"max_drawdown_pct": 170}
        ),
        lambda data: data["evaluations"][0]["profiles"][0].update(
            {"exposure_bar_ratio": 2}
        ),
        lambda data: data["evaluations"][1].update({"symbol": "BTCUSDT"}),
        lambda data: data["evaluations"][0]["profiles"].append(
            _profile("conservative")
        ),
        lambda data: data["evaluations"][1]["profiles"][0].update(
            {"win_rate_pct": 180}
        ),
        lambda data: data["evaluations"][1]["profiles"][0].update(
            {"net_pnl_usdt": float("nan")}
        ),
        lambda data: data["evaluations"][1]["profiles"][0].update(
            {"closed_round_trips": True}
        ),
    ],
)
def test_bad_physical_evidence_never_passes_observation_gate(mutate):
    candidate = deepcopy(_sample())
    mutate(candidate)
    with pytest.raises(CompositeObservationError):
        assess(candidate)


def test_nonpositive_and_single_trade_are_not_disguised_as_significance():
    data = _sample(trades=1)
    report = assess(data)
    assert report["decision"] == "READY_FOR_INDEPENDENT_QA_ONLY"
    assert report["statistical_significance_established"] is False
    assert report["owner_demo_admission_allowed"] is False
    assert report["conservative_closed_trades_by_symbol"]["BTCUSDT"] == 1


def test_profile_stress_trades_do_not_multiply_effective_sample_size():
    evidence = _sample(trades=1)
    evidence["evaluations"][0]["profiles"][1]["closed_round_trips"] = 12
    report = assess(evidence)
    assert report["conservative_closed_trades_by_symbol"]["BTCUSDT"] == 1
    assert report["owner_demo_admission_allowed"] is False
