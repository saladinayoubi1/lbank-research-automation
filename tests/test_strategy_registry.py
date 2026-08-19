from copy import deepcopy

import pytest

from phase5_strategy_factory import build_experiment, qualify
from phase6_research_pipeline import bind_bybit_closed_dataset
from strategy_registry import StrategyRegistryError, build_strategy_record, evaluate_strategy_health


START = 1_700_000_100_000
STEP = 900_000


def dataset(count=60):
    rows = []
    for index in range(count):
        price = 100 + index * 0.2
        rows.append({
            "source": "Bybit", "market_type": "spot", "symbol": "BTCUSDT", "interval": "15",
            "open_time_ms": START + index * STEP, "close_time_ms": START + (index + 1) * STEP - 1,
            "open": f"{price:.8f}", "high": f"{price * 1.01:.8f}", "low": f"{price * 0.99:.8f}",
            "close": f"{price:.8f}", "volume": "10", "turnover": f"{price * 10:.8f}", "closed": True,
        })
    return bind_bybit_closed_dataset(rows, canonical_symbol="BTC/USDT", source_symbol="BTCUSDT", interval="15")


def kills():
    return {
        "min_robustness_score": -1.0,
        "max_cost_stress_loss_pct": 100.0,
        "min_walk_forward_score": -1.0,
        "min_oos_score": -1.0,
        "max_drawdown_pct": 100.0,
        "min_regime_pass_ratio": 0.0,
        "max_failure_mode_severity": 10.0,
    }


def evidence(*, supported=True):
    return {
        "evidence_refs": ["dataset-sha256:" + "a" * 64],
        "hypothesis_supported": supported,
        "preregistered": True,
        "robustness_score": 0.01,
        "cost_stress_loss_pct": 1.0,
        "walk_forward_score": 0.01,
        "oos_score": 0.01,
        "max_drawdown_pct": 5.0,
        "regime_pass_ratio": 0.67,
        "failure_mode_severity": 0.0,
        "benchmark_score": 0.005,
        "uncertainty_width": 0.01,
        "survivorship_control": True,
        "lookahead_control": True,
        "data_snooping_control": True,
    }


def experiment(ds):
    return build_experiment(
        ds,
        hypothesis="bounded momentum research hypothesis",
        family="momentum",
        strategy_version="momentum-v1",
        config={"lookback": 3, "entry_threshold": 0.0},
        code_sha="a" * 40,
        cost_model={"fee_bps": 10.0, "slippage_bps": 5.0},
        kill_criteria=kills(),
    )


def record(*, supported=True):
    ds = dataset()
    exp = experiment(ds)
    ev = evidence(supported=supported)
    qualification = qualify(ds, exp, ev)
    return build_strategy_record(ds, exp, qualification, ev)


def test_candidate_registry_record_is_immutable_evidence_bound_and_paper_only():
    item = record()
    assert item["lifecycle_state"] == "CANDIDATE"
    assert item["paper_only"] is True
    assert item["live_execution_allowed"] is False
    assert item["deterministic_risk_final_authority"] is True
    assert len(item["strategy_id"]) == 64
    assert len(item["config_sha256"]) == 64
    assert len(item["record_digest"]) == 64
    assert item["funding_model"]["status"] == "NOT_APPLICABLE"
    assert item["is_window"] == {"start_index": 0, "end_index_exclusive": 42}
    assert item["oos_window"] == {"start_index": 42, "end_index_exclusive": 60}


def test_killed_qualification_is_registered_as_rejected_not_promoted():
    item = record(supported=False)
    assert item["lifecycle_state"] == "REJECTED"
    assert "HYPOTHESIS_UNSUPPORTED" in item["kill_reasons"]


def test_tampered_qualification_or_evidence_cannot_enter_registry():
    ds = dataset()
    exp = experiment(ds)
    ev = evidence()
    q = qualify(ds, exp, ev)
    bad_q = deepcopy(q)
    bad_q["status"] = "killed"
    with pytest.raises(StrategyRegistryError, match="qualification identity"):
        build_strategy_record(ds, exp, bad_q, ev)
    bad_ev = deepcopy(ev)
    bad_ev["oos_score"] = 99.0
    with pytest.raises(StrategyRegistryError, match="evidence digest"):
        build_strategy_record(ds, exp, q, bad_ev)


def health_signals(**changes):
    value = {
        "data_eligible": True,
        "performance_drop_pct": 0.0,
        "execution_cost_increase_pct": 0.0,
        "regime_mismatch": False,
        "correlation_shift_pct": 0.0,
    }
    value.update(changes)
    return value


@pytest.mark.parametrize(
    ("signals", "expected"),
    [
        (health_signals(), "HEALTHY"),
        (health_signals(regime_mismatch=True), "WATCH"),
        (health_signals(performance_drop_pct=35.0), "DEGRADED"),
        (health_signals(data_eligible=False), "QUARANTINED"),
        (health_signals(execution_cost_increase_pct=120.0), "QUARANTINED"),
    ],
)
def test_health_states_are_deterministic_and_evidence_gated(signals, expected):
    item = record()
    first = evaluate_strategy_health(item, signals)
    second = evaluate_strategy_health(deepcopy(item), deepcopy(signals))
    assert first == second
    assert first["health_state"] == expected
    assert first["promotion_authority"] is False
    assert first["deterministic_risk_final_authority"] is True
    assert len(first["health_digest"]) == 64


def test_health_unknown_fields_or_record_tampering_fail_closed():
    item = record()
    bad_signals = health_signals()
    bad_signals["owner_override"] = True
    with pytest.raises(StrategyRegistryError, match="health signal schema mismatch"):
        evaluate_strategy_health(item, bad_signals)
    tampered = deepcopy(item)
    tampered["lifecycle_state"] = "PAPER"
    with pytest.raises(StrategyRegistryError, match="record digest mismatch"):
        evaluate_strategy_health(tampered, health_signals())
