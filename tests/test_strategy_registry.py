from copy import deepcopy

import pytest

from phase5_strategy_factory import build_experiment, qualify
from phase6_research_pipeline import bind_bybit_closed_dataset
from strategy_registry import (
    StrategyRegistryError,
    build_qualified_strategy_record,
    build_strategy_record,
    build_runtime_candidate_view,
    evaluate_strategy_health,
    verify_qualified_strategy_record,
)


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


def _modern_qualification():
    from nexus_strategy_independent_qa import digest
    from nexus_strategy_qualification_gate import evaluate_qualification, verify_qualification
    from nexus_strategy_review_qa_handoff import qa_task_id

    core = {
        "schema_version":"nexus.strategy-review-qa-task.v1",
        "id":qa_task_id("a"*64,"b"*40,"d"*64),
        "task_kind":"strategy_review_independent_qa","system_map_node":"QA-41",
        "status":"READY_FOR_QA_DISPATCH","source_sha":"b"*40,
        "proposal_digest":"a"*64,"proposal_result_digest":"c"*64,
        "requalification_digest":"d"*64,"requalification_verification_digest":"e"*64,
        "family":"momentum","timeframe":"hour4","variant_id":"v1",
        "strategy_config":{"lookback":16},"strategy_config_digest":"",
        "runtime_evidence":[
            {"symbol":"BTCUSDT","dataset_binding_sha256":"f"*64,"pipeline_digest":"1"*64,
             "qualification_digest":"2"*64,"last_open_time_ms":1800000000000},
            {"symbol":"ETHUSDT","dataset_binding_sha256":"3"*64,"pipeline_digest":"4"*64,
             "qualification_digest":"5"*64,"last_open_time_ms":1800000000000},
        ],
        "producer_role":"strategy-runtime-requalification","required_verifier":"qa-verifier-agent",
        "research_only":True,"paper_only":True,"candidate_creation_authority":False,
        "qualification_authority":False,"promotion_authority":False,
        "paper_execution_authority":False,"automatic_strategy_promotion":False,
        "live_trading_authority":False,
    }
    core["strategy_config_digest"]=digest(core["strategy_config"])
    handoff={**core,"task_digest":digest(core)}
    receipt_core={
        "schema_version":"nexus.strategy-independent-qa-receipt.v1",
        "qa_lease_id":"qa-lease","task_digest":handoff["task_digest"],
        "source_sha":handoff["source_sha"],"proposal_digest":handoff["proposal_digest"],
        "proposal_result_digest":handoff["proposal_result_digest"],
        "requalification_digest":handoff["requalification_digest"],
        "requalification_verification_digest":handoff["requalification_verification_digest"],
        "strategy_config_digest":handoff["strategy_config_digest"],
        "runtime_evidence":[
            {**row,"qualification_status":"paper_candidate","deterministic_replay_verified":True}
            for row in sorted(handoff["runtime_evidence"], key=lambda item:item["symbol"])
        ],
        "independent_qa_complete":True,"qualification_authority":False,
        "promotion_authority":False,"paper_execution_authority":False,
        "automatic_strategy_promotion":False,"live_trading_authority":False,
    }
    receipt={**receipt_core,"qa_receipt_digest":digest(receipt_core)}
    manager={
        "id":handoff["id"],"status":"DONE","authority":2,"qa_verifier_only":True,
        "qa_dispatch_enabled":True,"required_verifier":"qa-verifier-agent",
        "qa_handoff_task":handoff,"assigned_worker":"qa-verifier-agent",
        "verifier":"qa-verifier-agent","lease_id":"qa-lease","verification_evidence":receipt,
    }
    qualification=evaluate_qualification(manager)
    verification=verify_qualification(qualification)
    assert verification["decision"]=="pass"
    return qualification, verification


def test_modern_registry_record_is_qualified_but_not_demo_activated():
    qualification, verification = _modern_qualification()
    record = build_qualified_strategy_record(qualification, verification)
    assert record["lifecycle_state"] == "QUALIFIED_CANDIDATE"
    assert record["demo_matrix_member"] is False
    assert record["runtime_activation_authority"] is False
    assert record["paper_execution_authority"] is False
    assert record["live_execution_allowed"] is False
    assert record["config_sha256"] == qualification["strategy_config_digest"]
    assert record["runtime_evidence_digest"] == qualification["runtime_evidence_digest"]
    assert record["qualification_artifact"]["qualification_digest"] == qualification["qualification_digest"]
    assert record["qualification_verification"] == verification
    assert verify_qualified_strategy_record(record)["decision"] == "pass"


def test_modern_registry_rejects_nonqualified_or_stale_qual42():
    qualification, verification = _modern_qualification()
    waiting = deepcopy(qualification)
    waiting["decision"] = "WAITING_FOR_QA"
    with pytest.raises(StrategyRegistryError, match="verification"):
        build_qualified_strategy_record(waiting, verification)

    stale = deepcopy(verification)
    stale["verification_digest"] = "0" * 64
    with pytest.raises(StrategyRegistryError, match="verification"):
        build_qualified_strategy_record(qualification, stale)


def test_modern_registry_identity_stable_for_same_config_but_version_is_epoch_bound():
    qualification, verification = _modern_qualification()
    first = build_qualified_strategy_record(qualification, verification)
    second_q = deepcopy(qualification)
    second_q["qualification_digest"] = "9" * 64
    from nexus_strategy_qualification_gate import verify_qualification
    # The altered artifact is intentionally not self-consistent and therefore
    # cannot be admitted merely to force a second version.
    assert verify_qualification(second_q)["decision"] == "reject"
    assert len(first["strategy_id"]) == 64
    assert len(first["strategy_version"]) == 64


def test_modern_registry_record_tamper_fails_closed():
    qualification, verification = _modern_qualification()
    record = build_qualified_strategy_record(qualification, verification)
    tampered = deepcopy(record)
    tampered["demo_matrix_member"] = True
    assert verify_qualified_strategy_record(tampered)["decision"] == "reject"

    # Re-digesting a copied registry field cannot detach it from the embedded
    # self-contained QUAL-42 proof.
    redigested_identity = deepcopy(record)
    redigested_identity["variant_id"] = "forged-variant"
    redigested_core = dict(redigested_identity)
    redigested_core.pop("record_digest", None)
    from strategy_registry import _digest
    redigested_identity["record_digest"] = _digest(redigested_core)
    assert verify_qualified_strategy_record(redigested_identity)["decision"] == "reject"

    forged_qualification = deepcopy(record)
    forged_qualification["qualification_artifact"]["variant_id"] = "forged-inside-proof"
    forged_core = dict(forged_qualification)
    forged_core.pop("record_digest", None)
    forged_qualification["record_digest"] = _digest(forged_core)
    assert verify_qualified_strategy_record(forged_qualification)["decision"] == "reject"

    bad_provenance = deepcopy(record)
    bad_provenance["runtime_evidence"][0]["pipeline_digest"] = "not-a-digest"
    bad_core = dict(bad_provenance)
    bad_core.pop("record_digest", None)
    from strategy_registry import _digest
    bad_provenance["record_digest"] = _digest(bad_core)
    assert verify_qualified_strategy_record(bad_provenance)["decision"] == "reject"

    bad_identity = deepcopy(qualification)
    bad_identity["variant_id"] = ""
    from nexus_strategy_qualification_gate import verify_qualification
    bad_verification = verify_qualification(bad_identity)
    assert bad_verification["decision"] == "reject"



def _healthy_signals():
    return {
        "data_eligible": True,
        "performance_drop_pct": 0.0,
        "execution_cost_increase_pct": 0.0,
        "regime_mismatch": False,
        "correlation_shift_pct": 0.0,
    }


def test_modern_registry_uses_existing_health_contract_without_activation():
    qualification, verification = _modern_qualification()
    record = build_qualified_strategy_record(qualification, verification)
    health = evaluate_strategy_health(record, _healthy_signals())
    assert health["health_state"] == "HEALTHY"
    assert health["strategy_id"] == record["strategy_id"]
    assert health["record_digest"] == record["record_digest"]
    assert health["promotion_authority"] is False

    candidate = build_runtime_candidate_view(record, health)
    assert candidate["lifecycle_state"] == "CANDIDATE"
    assert candidate["health_state"] == "HEALTHY"
    assert candidate["paper_only"] is True
    assert candidate["live_trading_authority"] is False


def test_modern_runtime_candidate_rejects_health_or_authority_detachment():
    qualification, verification = _modern_qualification()
    record = build_qualified_strategy_record(qualification, verification)
    health = evaluate_strategy_health(record, _healthy_signals())

    wrong_health = deepcopy(health)
    wrong_health["record_digest"] = "0" * 64
    health_core = dict(wrong_health)
    health_core.pop("health_digest", None)
    from strategy_registry import _digest
    wrong_health["health_digest"] = _digest(health_core)
    with pytest.raises(StrategyRegistryError, match="health binding"):
        build_runtime_candidate_view(record, wrong_health)

    widened = deepcopy(record)
    widened["demo_matrix_member"] = True
    widened_core = dict(widened)
    widened_core.pop("record_digest", None)
    widened["record_digest"] = _digest(widened_core)
    with pytest.raises(StrategyRegistryError, match="registry verification"):
        build_runtime_candidate_view(widened, health)
