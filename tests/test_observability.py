from copy import deepcopy
from decimal import Decimal
import json

import pytest

from observability import (
    GENESIS_DIGEST,
    ObservabilityError,
    ObservabilityState,
    append_observation,
    build_observation,
    load_ledger,
    replay,
    save_projection,
    state_projection,
    validate_observation,
)

D1 = "a" * 64
D2 = "b" * 64
D3 = "c" * 64


def actor(**changes):
    value = {
        "actor_type": "system",
        "actor_id": "nexus-core",
        "provider_id": None,
        "model_id": None,
        "model_version": None,
        "agent_id": None,
    }
    value.update(changes)
    return value


def inputs(**changes):
    value = {
        "input_digest": D1,
        "provenance_digest": D2,
        "context_id": None,
        "dataset_id": "btc-usdt-1h",
        "dataset_revision": "rev-7",
    }
    value.update(changes)
    return value


def policy(**changes):
    value = {"policy_id": "paper-risk", "policy_version": "7", "policy_digest": D3}
    value.update(changes)
    return value


def decision(**changes):
    value = {"decision": "allow", "reason_code": "validated", "authority_level": 2}
    value.update(changes)
    return value


def action(**changes):
    value = {"tool": "paper-engine", "operation": "observe", "target": "paper-account", "reversible": True}
    value.update(changes)
    return value


def result(**changes):
    value = {
        "status": "success",
        "failure_class": None,
        "latency_ms": 11,
        "retry_count": 0,
        "cost_usd": "0",
        "resource_units": 1,
    }
    value.update(changes)
    return value


def evidence(**changes):
    value = {"evidence_digest": D1, "resulting_state_digest": D2, "refs": ["event#7"]}
    value.update(changes)
    return value


def metrics(**changes):
    value = {
        "queue_latency_ms": None,
        "provider_failure": None,
        "ai_cost_usd": None,
        "data_ready": None,
        "qualification_state": None,
        "signal_accepted": None,
        "risk_denied": None,
        "fill_count": None,
        "open_positions": None,
        "pnl": None,
        "drawdown": None,
        "exposure": None,
        "recovery_event": None,
        "stale_memory": None,
        "circuit_break": None,
        "policy_denial": None,
    }
    value.update(changes)
    return value


def event(sequence=1, previous=GENESIS_DIGEST, category="queue", **changes):
    args = {
        "event_id": f"obs-{sequence}",
        "sequence": sequence,
        "category": category,
        "occurred_at": f"2026-08-17T08:{sequence:02d}:00Z",
        "correlation_id": "corr-1",
        "causation_id": "cause-1",
        "actor": actor(),
        "inputs": inputs(),
        "policy": policy(),
        "decision": decision(),
        "action": action(),
        "result": result(),
        "evidence": evidence(),
        "metrics": metrics(queue_latency_ms=5) if category == "queue" else metrics(),
        "previous_event_digest": previous,
    }
    args.update(changes)
    return build_observation(**args)


def chain(*events_specs):
    values = []
    previous = GENESIS_DIGEST
    for index, spec in enumerate(events_specs, start=1):
        category, changes = spec
        current = event(index, previous, category, **changes)
        values.append(current)
        previous = current["event_digest"]
    return values


def test_full_audit_envelope_binds_actor_inputs_policy_decision_action_result_evidence_and_state():
    item = event()
    assert item["actor"]["actor_id"] == "nexus-core"
    assert item["inputs"]["provenance_digest"] == D2
    assert item["policy"]["policy_version"] == "7"
    assert item["decision"]["reason_code"] == "validated"
    assert item["action"]["tool"] == "paper-engine"
    assert item["result"]["status"] == "success"
    assert item["evidence"]["resulting_state_digest"] == D2
    assert len(item["event_digest"]) == 64
    assert validate_observation(item) == item


def test_model_and_agent_identity_are_explicit_when_used():
    model_event = event(actor=actor(actor_type="model", actor_id="model-worker", provider_id="openai", model_id="gpt-5.6-sol", model_version="2026-08-17"))
    assert model_event["actor"]["provider_id"] == "openai"
    with pytest.raises(ObservabilityError, match="provider/model"):
        event(actor=actor(actor_type="model", actor_id="broken-model"))
    with pytest.raises(ObservabilityError, match="agent_id"):
        event(actor=actor(actor_type="agent", actor_id="broken-agent"))


def test_queue_provider_ai_data_strategy_signal_risk_paper_recovery_memory_and_policy_metrics_are_tracked():
    events = chain(
        ("queue", {"metrics": metrics(queue_latency_ms=20), "result": result(retry_count=1)}),
        ("agent_provider", {"metrics": metrics(provider_failure=True), "result": result(status="failure", failure_class="provider-unavailable", latency_ms=30)}),
        ("ai_usage", {"metrics": metrics(ai_cost_usd="0.125"), "result": result(cost_usd="0.125", resource_units=7)}),
        ("data_readiness", {"metrics": metrics(data_ready=True)}),
        ("strategy_qualification", {"metrics": metrics(qualification_state="paper-eligible")}),
        ("signal_decision", {"metrics": metrics(signal_accepted=True)}),
        ("risk_denial", {"metrics": metrics(risk_denied=True, signal_accepted=False), "decision": decision(decision="deny", reason_code="risk_limit")}),
        ("paper_execution", {"metrics": metrics(fill_count=2, open_positions=1, pnl="12.50", drawdown="3.25", exposure="100.00")}),
        ("recovery", {"metrics": metrics(recovery_event=True)}),
        ("context_memory", {"metrics": metrics(stale_memory=True), "result": result(status="blocked", failure_class="stale-state")}),
        ("circuit_policy", {"metrics": metrics(circuit_break=True, policy_denial=True), "decision": decision(decision="deny", reason_code="policy_denied")}),
    )
    state = replay(events)
    projection = state_projection(state)
    assert state.event_count == 11
    assert state.queue_latency_total_ms == 20
    assert state.provider_failures == 1
    assert state.ai_cost_usd == Decimal("0.125")
    assert state.resource_units == 17
    assert state.data_ready_events == 1
    assert state.qualification_events == 1
    assert state.accepted_signals == 1
    assert state.rejected_signals == 1
    assert state.risk_denials == 1
    assert state.fill_count == 2
    assert state.open_positions == 1
    assert state.pnl == Decimal("12.50")
    assert state.drawdown == Decimal("3.25")
    assert state.exposure == Decimal("100.00")
    assert state.recoveries == 1
    assert state.stale_memory_events == 1
    assert state.circuit_breaks == 1
    assert state.policy_denials == 1
    assert state.retries == 1
    assert projection["contract_version"] == "nexus.observability.read.v1"
    assert projection["paper"]["pnl"] == "12.50"


def test_signal_acceptance_and_rejection_are_distinct():
    events = chain(
        ("signal_decision", {"metrics": metrics(signal_accepted=True)}),
        ("signal_decision", {"metrics": metrics(signal_accepted=False), "decision": decision(decision="deny", reason_code="stale_signal")}),
    )
    state = replay(events)
    assert state.accepted_signals == 1
    assert state.rejected_signals == 1


def test_failure_taxonomy_is_exact_and_unknown_class_fails_closed():
    accepted = event(result=result(status="failure", failure_class="invalid-data"))
    assert accepted["result"]["failure_class"] == "invalid-data"
    with pytest.raises(ObservabilityError, match="unknown failure class"):
        event(result=result(status="failure", failure_class="something-new"))


def test_binary_float_decimal_nan_and_infinity_are_rejected():
    with pytest.raises(ObservabilityError, match="binary floating point"):
        event(result=result(cost_usd=0.1))
    with pytest.raises(ObservabilityError, match="finite"):
        event(result=result(cost_usd="NaN"))
    with pytest.raises(ObservabilityError, match="finite"):
        event(metrics=metrics(pnl="Infinity"))


def test_unknown_fields_tamper_and_secret_material_fail_closed():
    item = event()
    extra = deepcopy(item)
    extra["unexpected"] = True
    with pytest.raises(ObservabilityError, match="schema mismatch"):
        validate_observation(extra)

    tampered = deepcopy(item)
    tampered["decision"]["reason_code"] = "changed"
    with pytest.raises(ObservabilityError, match="digest"):
        validate_observation(tampered)

    with pytest.raises(ObservabilityError, match="sensitive"):
        event(action=action(target="api_key=abcdefghijklmnop"))


def test_duplicate_gap_reordering_and_digest_chain_mismatch_fail_replay():
    first = event()
    duplicate = deepcopy(first)
    with pytest.raises(ObservabilityError, match="sequence"):
        replay([first, duplicate])

    gap = event(3, first["event_digest"])
    with pytest.raises(ObservabilityError, match="sequence"):
        replay([first, gap])

    reordered = event(2, first["event_digest"], occurred_at="2026-08-17T07:59:00Z")
    with pytest.raises(ObservabilityError, match="UTC-time ordered"):
        replay([first, reordered])

    bad_chain = event(2, "f" * 64)
    with pytest.raises(ObservabilityError, match="digest chain"):
        replay([first, bad_chain])


def test_replay_failure_does_not_mutate_previous_valid_state():
    first = event()
    state = replay([first])
    original = deepcopy(state)
    bad = event(3, first["event_digest"])
    with pytest.raises(ObservabilityError):
        replay([bad], previous=state)
    assert state == original


def test_append_ledger_is_durable_and_rejects_stale_tail(tmp_path):
    path = tmp_path / "observability.jsonl"
    first = event()
    state1 = append_observation(path, first)
    assert state1.event_count == 1
    second = event(2, first["event_digest"])
    state2 = append_observation(path, second)
    assert state2.event_count == 2
    assert load_ledger(path) == [first, second]

    stale = event(3, GENESIS_DIGEST)
    with pytest.raises(ObservabilityError, match="previous digest"):
        append_observation(path, stale)
    assert load_ledger(path) == [first, second]


def test_corrupt_or_partial_ledger_fails_closed(tmp_path):
    path = tmp_path / "observability.jsonl"
    path.write_text('{"partial":', encoding="utf-8")
    with pytest.raises(ObservabilityError, match="corrupt"):
        load_ledger(path)

    path.write_text("\n", encoding="utf-8")
    with pytest.raises(ObservabilityError, match="blank line"):
        load_ledger(path)


def test_projection_commit_is_canonical_and_contains_no_raw_event_payload(tmp_path):
    state = replay(chain(("paper_execution", {"metrics": metrics(fill_count=1, pnl="1.25", exposure="20")})))
    path = tmp_path / "projection.json"
    save_projection(path, state)
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["contract_version"] == "nexus.observability.read.v1"
    assert payload["paper"]["fills"] == 1
    assert "actor" not in payload
    assert "inputs" not in payload


def test_same_inputs_produce_same_observation_and_replay_state():
    first = event()
    second = event()
    assert first == second
    assert replay([first]) == replay([second])


def test_event_builder_does_not_mutate_nested_inputs():
    a = actor()
    i = inputs()
    p = policy()
    d = decision()
    ac = action()
    r = result()
    e = evidence()
    m = metrics(queue_latency_ms=5)
    originals = [deepcopy(x) for x in (a, i, p, d, ac, r, e, m)]
    event(actor=a, inputs=i, policy=p, decision=d, action=ac, result=r, evidence=e, metrics=m)
    assert [a, i, p, d, ac, r, e, m] == originals


def test_empty_projection_is_valid_and_decimal_safe():
    projection = state_projection(ObservabilityState())
    assert projection["event_count"] == 0
    assert projection["ai"]["cost_usd"] == "0"
    assert projection["paper"]["pnl"] == "0"
