from copy import deepcopy

import pytest

from phase5_strategy_factory import build_experiment, qualify
from phase6_research_pipeline import bind_bybit_closed_dataset
from strategy_lifecycle import (
    StrategyLifecycleError,
    apply_health_lifecycle,
    build_research_lifecycle,
    promote_candidate_to_paper,
    replay_lifecycle,
)
from strategy_registry import build_strategy_record, evaluate_strategy_health


START = 1_700_000_100_000
STEP = 900_000


def dataset(count=60):
    rows = []
    for index in range(count):
        price = 100 + index * 0.2
        rows.append(
            {
                "source": "Bybit",
                "market_type": "spot",
                "symbol": "BTCUSDT",
                "interval": "15",
                "open_time_ms": START + index * STEP,
                "close_time_ms": START + (index + 1) * STEP - 1,
                "open": f"{price:.8f}",
                "high": f"{price * 1.01:.8f}",
                "low": f"{price * 0.99:.8f}",
                "close": f"{price:.8f}",
                "volume": "10",
                "turnover": f"{price * 10:.8f}",
                "closed": True,
            }
        )
    return bind_bybit_closed_dataset(
        rows,
        canonical_symbol="BTC/USDT",
        source_symbol="BTCUSDT",
        interval="15",
    )


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


def qualification_evidence(*, supported=True):
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


def record(*, supported=True):
    ds = dataset()
    experiment = build_experiment(
        ds,
        hypothesis="bounded momentum research hypothesis",
        family="momentum",
        strategy_version="momentum-v1",
        config={"lookback": 3, "entry_threshold": 0.0},
        code_sha="a" * 40,
        cost_model={"fee_bps": 10.0, "slippage_bps": 5.0},
        kill_criteria=kills(),
    )
    evidence = qualification_evidence(supported=supported)
    qualification = qualify(ds, experiment, evidence)
    return build_strategy_record(ds, experiment, qualification, evidence)


def paper_acceptance(**changes):
    value = {
        "risk_gate_allowed": True,
        "replay_verified": True,
        "paper_execution_evidence_sha256": "b" * 64,
        "independent_verifier_evidence_sha256": "c" * 64,
        "producer_id": "paper-executor",
        "verifier_id": "independent-cloud-verifier",
    }
    value.update(changes)
    return value


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


def test_candidate_research_lifecycle_is_append_only_and_deterministic():
    item = record()
    first = build_research_lifecycle(item)
    second = build_research_lifecycle(deepcopy(item))
    assert first == second
    assert [event["to_state"] for event in first] == [
        "RESEARCHED",
        "BACKTESTED",
        "VALIDATED",
        "CANDIDATE",
    ]
    assert replay_lifecycle(first) == "CANDIDATE"
    assert all(event["paper_only"] is True for event in first)
    assert all(event["promotion_authority"] is False for event in first)
    assert all(event["deterministic_risk_final_authority"] is True for event in first)


def test_candidate_can_enter_paper_only_with_risk_replay_and_independent_verifier_evidence():
    item = record()
    research = build_research_lifecycle(item)
    paper = promote_candidate_to_paper(item, research, paper_acceptance())
    assert replay_lifecycle(paper) == "PAPER"
    assert paper[-1]["from_state"] == "CANDIDATE"
    assert paper[-1]["to_state"] == "PAPER"
    assert paper[-1]["reason_code"] == "PAPER_ACCEPTANCE_VERIFIED"

    health = evaluate_strategy_health(item, health_signals(data_eligible=False))
    quarantined = apply_health_lifecycle(item, paper, health)
    assert replay_lifecycle(quarantined) == "QUARANTINED"
    assert quarantined[-1]["reason_code"] == "HEALTH_QUARANTINE"


def test_non_quarantined_health_preserves_current_lifecycle_byte_for_byte():
    item = record()
    paper = promote_candidate_to_paper(item, build_research_lifecycle(item), paper_acceptance())
    health = evaluate_strategy_health(item, health_signals(regime_mismatch=True))
    assert health["health_state"] == "WATCH"
    assert apply_health_lifecycle(item, paper, health) == paper


def test_rejected_research_record_is_terminal_and_cannot_enter_paper():
    item = record(supported=False)
    lifecycle = build_research_lifecycle(item)
    assert replay_lifecycle(lifecycle) == "REJECTED"
    with pytest.raises(StrategyLifecycleError, match="CANDIDATE"):
        promote_candidate_to_paper(item, lifecycle, paper_acceptance())


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"risk_gate_allowed": False}, "Risk gate"),
        ({"replay_verified": False}, "replay verification"),
        ({"producer_id": "same", "verifier_id": "same"}, "must be distinct"),
        ({"paper_execution_evidence_sha256": "not-a-sha"}, "SHA-256"),
        (
            {
                "paper_execution_evidence_sha256": "d" * 64,
                "independent_verifier_evidence_sha256": "d" * 64,
            },
            "evidence must be distinct",
        ),
    ],
)
def test_paper_acceptance_fail_closed(changes, message):
    item = record()
    with pytest.raises(StrategyLifecycleError, match=message):
        promote_candidate_to_paper(
            item,
            build_research_lifecycle(item),
            paper_acceptance(**changes),
        )


def test_unknown_acceptance_authority_field_is_rejected():
    item = record()
    widened = paper_acceptance()
    widened["live_override"] = True
    with pytest.raises(StrategyLifecycleError, match="schema mismatch"):
        promote_candidate_to_paper(item, build_research_lifecycle(item), widened)


def test_transition_tampering_reordering_and_identity_mix_fail_closed():
    item = record()
    lifecycle = list(build_research_lifecycle(item))

    tampered = deepcopy(lifecycle)
    tampered[1]["to_state"] = "PAPER"
    with pytest.raises(StrategyLifecycleError, match="digest"):
        replay_lifecycle(tampered)

    reordered = [lifecycle[1], lifecycle[0], *lifecycle[2:]]
    with pytest.raises(StrategyLifecycleError):
        replay_lifecycle(reordered)

    other = record(supported=False)
    mixed = deepcopy(lifecycle)
    mixed[-1]["record_digest"] = other["record_digest"]
    with pytest.raises(StrategyLifecycleError, match="digest"):
        replay_lifecycle(mixed)
