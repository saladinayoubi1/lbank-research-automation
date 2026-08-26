from copy import deepcopy
import hashlib
import json

import pytest

from nexus_regime_strategy_runtime import (
    RUNTIME_SCHEMA,
    RegimeStrategyRuntimeError,
    load_runtime_evidence,
    persist_runtime_evidence,
    run_regime_strategy_runtime,
    verify_runtime_evidence,
)
from tests.test_automated_signal_pipeline import (
    dataset,
    decision,
    policy as risk_policy,
    portfolio_state,
    qualification,
    regime,
    risk_state,
)
from tests.test_nexus_regime_strategy_selector import candidate, context, policy


SOURCE_SHA = "a" * 40
OCCURRED = "2026-08-17T00:05:00Z"


def canonical_digest(value):
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def rehash_runtime(evidence):
    evidence["runtime_digest"] = canonical_digest(
        {key: value for key, value in evidence.items() if key != "runtime_digest"}
    )


def selector_policy(weight="0.50"):
    value = policy()
    value["alignment_weights"]["ALIGNED_UP"] = {"momentum": weight}
    return value


def lane(*, risk_changes=None):
    selected_qualification = qualification(strategy_id="momentum-paper-v1")
    selected_decision = decision(strategy_id="momentum-paper-v1", quantity="0.01")
    selected_risk_policy = risk_policy(
        eligible_strategies=[{"id": "momentum-paper-v1", "version": "1.0.0"}],
        **(risk_changes or {}),
    )
    return {
        "family": "momentum",
        "dataset": dataset(),
        "qualification": selected_qualification,
        "regime": regime(),
        "decision": selected_decision,
        "risk_state": risk_state(),
        "risk_policy": selected_risk_policy,
        "portfolio_state": portfolio_state(),
        "fee_rate": "0.001",
        "slippage_bps": "10",
    }


def run(*, selected_context=None, selected_lanes=None, selected_policy=None):
    return run_regime_strategy_runtime(
        context=selected_context or context("ALIGNED_UP"),
        candidates=[candidate("momentum")],
        selector_policy=selected_policy or selector_policy(),
        lanes=[lane()] if selected_lanes is None else selected_lanes,
        source_sha=SOURCE_SHA,
        occurred_at=OCCURRED,
    )


def test_selection_is_scaled_and_routed_through_risk_and_isolated_paper():
    result = run()
    assert result.evidence["paper_only"] is True
    assert result.evidence["live_trading_authority"] is False
    assert result.evidence["deterministic_risk_final_authority"] is True
    assert result.evidence["lanes"][0]["weight"] == "0.500000"
    assert result.pipelines[0].signal["quantity"] == "0.00500000"
    assert result.pipelines[0].risk_decision.allowed is True
    assert result.pipelines[0].execution is not None
    assert len(result.evidence["runtime_digest"]) == 64


def test_preserve_cash_runs_no_paper_lane():
    result = run(selected_context=context("MIXED"), selected_lanes=[])
    assert result.evidence["cash_weight"] == "1.000000"
    assert result.evidence["lanes"] == []
    assert result.pipelines == ()
    assert verify_runtime_evidence(result.evidence)["decision"] == "pass"


def test_lane_set_must_exactly_match_selection():
    with pytest.raises(RegimeStrategyRuntimeError, match="exactly match"):
        run(selected_lanes=[])


def test_lane_strategy_must_match_selected_candidate():
    bad = lane()
    bad["qualification"] = qualification(strategy_id="other")
    with pytest.raises(RegimeStrategyRuntimeError, match="contradicts"):
        run(selected_lanes=[bad])


def test_risk_denial_is_recorded_without_execution():
    blocked = lane(risk_changes={"max_position_fraction": "0.0001"})
    result = run(selected_lanes=[blocked])
    assert result.pipelines[0].risk_decision.allowed is False
    assert result.pipelines[0].execution is None
    assert result.evidence["lanes"][0]["execution_status"] == "BLOCKED"


def test_runtime_is_deterministic_and_does_not_mutate_inputs():
    selected_context = context("ALIGNED_UP")
    selected_policy = selector_policy()
    selected_lanes = [lane()]
    original_context = deepcopy(selected_context)
    original_policy = deepcopy(selected_policy)
    first = run_regime_strategy_runtime(
        context=selected_context, candidates=[candidate("momentum")],
        selector_policy=selected_policy, lanes=selected_lanes,
        source_sha=SOURCE_SHA, occurred_at=OCCURRED,
    )
    second = run_regime_strategy_runtime(
        context=selected_context, candidates=[candidate("momentum")],
        selector_policy=selected_policy, lanes=selected_lanes,
        source_sha=SOURCE_SHA, occurred_at=OCCURRED,
    )
    assert first == second
    assert selected_context == original_context
    assert selected_policy == original_policy


def test_independent_verifier_rejects_tampered_risk_or_allocation():
    result = run()
    assert verify_runtime_evidence(result.evidence)["decision"] == "pass"
    tampered = deepcopy(result.evidence)
    tampered["lanes"][0]["risk_allowed"] = False
    assert verify_runtime_evidence(tampered)["decision"] == "reject"


def test_independent_verifier_rejects_rehashed_risk_and_event_forgery():
    tampered = deepcopy(run().evidence)
    tampered["lanes"][0]["risk_allowed"] = False
    tampered["lanes"][0]["risk_reason"] = "forged"
    tampered["lanes"][0]["execution_status"] = "BLOCKED"
    rehash_runtime(tampered)
    verification = verify_runtime_evidence(tampered)
    assert verification["decision"] == "reject"
    assert verification["checks"]["runtime_digest"] is True
    assert verification["checks"]["risk_execution_binding"] is False
    assert verification["checks"]["event_semantics"] is False


def test_independent_verifier_replays_selector_after_all_digests_are_rebuilt():
    tampered = deepcopy(run().evidence)
    allocation = tampered["selection"]["allocations"][0]
    allocation["weight"] = "0.400000"
    tampered["selection"]["cash_weight"] = "0.600000"
    selection_core = {
        key: value for key, value in tampered["selection"].items()
        if key != "selection_digest"
    }
    tampered["selection"]["selection_digest"] = canonical_digest(selection_core)
    tampered["selection_digest"] = tampered["selection"]["selection_digest"]
    tampered["cash_weight"] = "0.600000"
    tampered["lanes"][0]["weight"] = "0.400000"
    rehash_runtime(tampered)
    verification = verify_runtime_evidence(tampered)
    assert verification["checks"]["runtime_digest"] is True
    assert verification["checks"]["selection_digest"] is True
    assert verification["checks"]["allocation_total"] is True
    assert verification["checks"]["selection_replay"] is False
    assert verification["decision"] == "reject"


def test_independent_verifier_replays_pipeline_after_terminal_state_is_rehashed():
    tampered = deepcopy(run().evidence)
    tampered["lanes"][0]["terminal_portfolio"]["cash"] = "999999"
    rehash_runtime(tampered)
    verification = verify_runtime_evidence(tampered)
    assert verification["checks"]["runtime_digest"] is True
    assert verification["checks"]["event_chain"] is True
    assert verification["checks"]["pipeline_replay"] is False
    assert verification["decision"] == "reject"


def test_independent_verifier_rejects_malformed_evidence_without_throwing():
    verification = verify_runtime_evidence({"schema_version": RUNTIME_SCHEMA})
    assert verification["decision"] == "reject"
    for field, value in (("risk_input", []), ("events", []), ("terminal_portfolio", {})):
        malformed = deepcopy(run().evidence)
        malformed["lanes"][0][field] = value
        rehash_runtime(malformed)
        assert verify_runtime_evidence(malformed)["decision"] == "reject"


def test_verified_evidence_is_persisted_append_only_and_idempotently(tmp_path):
    evidence = run().evidence
    first = persist_runtime_evidence(evidence, tmp_path)
    second = persist_runtime_evidence(evidence, tmp_path)
    assert first == second
    assert first.read_bytes() == second.read_bytes()
    stored = __import__("json").loads(first.read_text())
    assert stored["verification"]["decision"] == "pass"
    assert load_runtime_evidence(first) == evidence


def test_restart_rejects_tampered_or_renamed_evidence(tmp_path):
    evidence = run().evidence
    path = persist_runtime_evidence(evidence, tmp_path)
    stored = __import__("json").loads(path.read_text())
    stored["lanes"][0]["risk_allowed"] = False
    path.write_text(__import__("json").dumps(stored))
    with pytest.raises(RegimeStrategyRuntimeError, match="restart verification"):
        load_runtime_evidence(path)

    clean = persist_runtime_evidence(evidence, tmp_path / "clean")
    renamed = clean.with_name("substituted.json")
    clean.rename(renamed)
    with pytest.raises(RegimeStrategyRuntimeError, match="filename binding"):
        load_runtime_evidence(renamed)


def test_persistence_rejects_preexisting_directory_or_symlink(tmp_path):
    evidence = run().evidence
    unsafe_root = tmp_path / "directory"
    unsafe_root.mkdir()
    (unsafe_root / f"{evidence['runtime_digest']}.json").mkdir()
    with pytest.raises(RegimeStrategyRuntimeError, match="path is unsafe"):
        persist_runtime_evidence(evidence, unsafe_root)

    clean = persist_runtime_evidence(evidence, tmp_path / "clean")
    symlink_root = tmp_path / "symlink"
    symlink_root.mkdir()
    link = symlink_root / f"{evidence['runtime_digest']}.json"
    try:
        link.symlink_to(clean)
    except OSError:
        pytest.skip("symlink creation is unavailable on this platform")
    with pytest.raises(RegimeStrategyRuntimeError, match="path is unsafe"):
        persist_runtime_evidence(evidence, symlink_root)
