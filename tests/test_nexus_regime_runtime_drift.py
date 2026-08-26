from copy import deepcopy

import pytest

import nexus_regime_runtime_drift as drift
from nexus_regime_runtime_drift import (
    RegimeRuntimeDriftError,
    build_regime_runtime_drift,
    persist_regime_runtime_drift,
)
from tests.test_nexus_regime_strategy_runtime import run


SOURCE_SHA = "a" * 40
VERIFICATION_DIGEST = "v" * 64


def supervisor():
    return {"source_sha": SOURCE_SHA, "tasks": []}


def performance(status="HEALTHY", *, include=True):
    strategies = []
    if include:
        strategies.append({
            "family": "momentum",
            "strategy_id": "momentum-paper-v1",
            "status": status,
            "lifecycle_state": "PAPER",
            "closed_trade_count": 5,
            "expectancy": "1",
            "max_drawdown_pct": "1",
            "net_pnl": "5",
            "monitor_digest": "m" * 64,
        })
    core = {
        "contract_version": "nexus.mission-control.paper-performance.v1",
        "supervisor_verification_digest": VERIFICATION_DIGEST,
        "paper_only": True,
        "live_trading_authority": False,
        "strategy_count": len(strategies),
        "status_counts": {status: 1} if strategies else {},
        "strategies": strategies,
    }
    return {**core, "projection_digest": drift._digest(core)}


@pytest.fixture(autouse=True)
def verified_supervisor(monkeypatch):
    monkeypatch.setattr(drift, "verify_ledger", lambda _ledger: {
        "decision": "pass", "verification_digest": VERIFICATION_DIGEST,
    })


def test_healthy_runtime_is_bound_to_stable_performance_projection():
    result = build_regime_runtime_drift(
        supervisor_ledger=supervisor(),
        performance_projection=performance(),
        runtime_evidence=run().evidence,
    )
    assert result["drift_state"] == "STABLE"
    assert result["next_cycle_controls"] == []
    assert result["selected_strategies"][0]["next_cycle_action"] == "KEEP"
    assert result["current_runtime_mutated"] is False
    assert result["paper_only"] is True
    assert result["live_trading_authority"] is False


@pytest.mark.parametrize(
    ("status", "action"),
    [
        ("WATCH", "WATCH_HAIRCUT_NEXT_CYCLE"),
        ("DEGRADED", "REMOVE_FROM_NEXT_SELECTION"),
        ("QUARANTINED", "REMOVE_FROM_NEXT_SELECTION"),
        ("INSUFFICIENT_EVIDENCE", "PRESERVE_CURRENT_POLICY_BOUND"),
    ],
)
def test_drift_can_only_control_the_next_cycle(status, action):
    result = build_regime_runtime_drift(
        supervisor_ledger=supervisor(),
        performance_projection=performance(status),
        runtime_evidence=run().evidence,
    )
    assert result["drift_state"] == "ACTION_REQUIRED"
    assert result["next_cycle_controls"][0]["next_cycle_action"] == action
    assert result["promotion_authority"] is False


def test_missing_family_or_tampered_input_fails_closed():
    with pytest.raises(RegimeRuntimeDriftError, match="lacks performance"):
        build_regime_runtime_drift(
            supervisor_ledger=supervisor(),
            performance_projection=performance(include=False),
            runtime_evidence=run().evidence,
        )
    tampered = deepcopy(run().evidence)
    tampered["cash_weight"] = "1.000000"
    with pytest.raises(RegimeRuntimeDriftError, match="runtime evidence"):
        build_regime_runtime_drift(
            supervisor_ledger=supervisor(),
            performance_projection=performance(),
            runtime_evidence=tampered,
        )


def test_cross_sha_or_tampered_performance_fails_closed():
    wrong_sha = supervisor()
    wrong_sha["source_sha"] = "b" * 40
    with pytest.raises(RegimeRuntimeDriftError, match="source SHA"):
        build_regime_runtime_drift(
            supervisor_ledger=wrong_sha,
            performance_projection=performance(),
            runtime_evidence=run().evidence,
        )
    tampered = performance()
    tampered["strategies"][0]["status"] = "QUARANTINED"
    with pytest.raises(RegimeRuntimeDriftError, match="verification failed"):
        build_regime_runtime_drift(
            supervisor_ledger=supervisor(),
            performance_projection=tampered,
            runtime_evidence=run().evidence,
        )


def test_drift_evidence_is_append_only_and_idempotent(tmp_path):
    result = build_regime_runtime_drift(
        supervisor_ledger=supervisor(),
        performance_projection=performance(),
        runtime_evidence=run().evidence,
    )
    first = persist_regime_runtime_drift(result, tmp_path)
    second = persist_regime_runtime_drift(result, tmp_path)
    assert first == second
    assert first.read_bytes() == second.read_bytes()

    collision = deepcopy(result)
    collision["drift_state"] = "ACTION_REQUIRED"
    with pytest.raises(RegimeRuntimeDriftError, match="verification failed"):
        persist_regime_runtime_drift(collision, tmp_path)
