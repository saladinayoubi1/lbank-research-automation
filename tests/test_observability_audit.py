from __future__ import annotations

import json

import pytest

from observability_audit import (
    AuditJournal,
    MissingCriticalAuditEvidence,
    ObservabilityAuditError,
    TRACKED_CATEGORIES,
    audit_coverage,
    operator_snapshot,
    require_gate15_evidence,
)

NOW = "2026-08-17T06:40:00Z"
CORRELATION = "corr-gate15"

CATEGORY_STAGE = (
    ("data_readiness", "market_data"),
    ("strategy_qualification", "strategy_regime"),
    ("signal", "signal"),
    ("signal", "decision"),
    ("risk", "risk"),
    ("queue", "dispatch"),
    ("paper_execution", "paper_execution"),
    ("agent_provider", "provider"),
    ("ai_budget", "ai_control"),
    ("recovery_replay", "recovery"),
    ("memory_context", "memory"),
    ("circuit_policy", "policy"),
)


def append_event(journal: AuditJournal, *, index: int, category: str, stage: str, kind: str = "decision_action"):
    return journal.append(
        event_id=f"audit-{index}",
        event_kind=kind,
        category=category,
        stage=stage,
        occurred_at=NOW,
        correlation_id=CORRELATION,
        causation_id=None if index == 0 else f"audit-{index - 1}",
        actor="nexus",
        model_id="gpt-test" if category == "ai_budget" else None,
        agent_id="agent-test" if category == "agent_provider" else None,
        inputs_provenance={"source": "validated", "revision": "r1"},
        policy_version="phase4/v1",
        decision="allow",
        reason_code="ok",
        action=f"observe:{stage}",
        result="recorded",
        evidence={"digest": "a" * 64},
        resulting_state={"status": "valid"},
        metrics={"latency_ms": "12.5", "attempt": index + 1},
    )


def full_journal() -> AuditJournal:
    journal = AuditJournal()
    for index, (category, stage) in enumerate(CATEGORY_STAGE):
        append_event(journal, index=index, category=category, stage=stage)
    return journal


def test_full_gate15_evidence_covers_required_categories_and_decision_path():
    journal = full_journal()
    coverage = require_gate15_evidence(journal.events)

    assert coverage.complete is True
    assert coverage.missing_categories == ()
    assert coverage.missing_stages == ()
    assert coverage.event_count == len(CATEGORY_STAGE)
    assert {event["category"] for event in journal.events} == TRACKED_CATEGORIES


def test_missing_critical_stage_fails_closed():
    journal = AuditJournal()
    for index, (category, stage) in enumerate(CATEGORY_STAGE):
        if stage == "risk":
            continue
        append_event(journal, index=index, category=category, stage=stage)

    with pytest.raises(MissingCriticalAuditEvidence, match="Gate 15 evidence incomplete"):
        require_gate15_evidence(journal.events)


def test_missing_tracked_category_fails_closed():
    journal = AuditJournal()
    index = 0
    for category, stage in CATEGORY_STAGE:
        if category == "ai_budget":
            continue
        append_event(journal, index=index, category=category, stage=stage)
        index += 1

    coverage = audit_coverage(journal.events)
    assert coverage.complete is False
    assert "ai_budget" in coverage.missing_categories


def test_tampering_is_detected_without_replacing_valid_chain():
    journal = full_journal()
    tampered = [dict(event) for event in journal.events]
    tampered[3] = {**tampered[3], "result": "silently_changed"}

    with pytest.raises(ObservabilityAuditError, match="payload digest mismatch"):
        AuditJournal(tampered)

    journal.verify()
    assert journal.events[3]["result"] == "recorded"


def test_reordered_chain_is_rejected():
    journal = full_journal()
    reordered = list(journal.events)
    reordered[1], reordered[2] = reordered[2], reordered[1]

    with pytest.raises(ObservabilityAuditError, match="previous digest mismatch"):
        AuditJournal(reordered)


def test_incident_and_operator_snapshot_are_read_only_and_visible():
    journal = full_journal()
    journal.append(
        event_id="audit-incident",
        event_kind="incident",
        category="circuit_policy",
        stage="policy",
        occurred_at=NOW,
        correlation_id=CORRELATION,
        causation_id="audit-11",
        actor="risk-policy",
        inputs_provenance={"policy": "phase4/v1"},
        policy_version="phase4/v1",
        decision="deny",
        reason_code="circuit_open",
        action="block",
        result="denied",
        evidence={"digest": "b" * 64},
        resulting_state={"circuit": "open"},
        metrics={"denial_count": 1},
    )

    snapshot = operator_snapshot(journal.events)
    assert snapshot["read_only"] is True
    assert snapshot["contract_version"] == "nexus.observability.read.v1"
    assert snapshot["incident_count"] == 1
    assert snapshot["coverage_complete"] is True
    assert snapshot["last_reason_codes"][-1] == "circuit_open"
    assert "action" not in snapshot


def test_jsonl_round_trip_preserves_exact_hash_chain(tmp_path):
    journal = full_journal()
    target = tmp_path / "audit" / "gate15.jsonl"
    journal.write_jsonl(target)

    restored = AuditJournal.read_jsonl(target)
    assert restored.events == journal.events
    assert restored.previous_event_digest == journal.previous_event_digest


def test_binary_floats_and_non_utc_timestamps_are_rejected():
    journal = AuditJournal()
    fields = dict(
        event_id="audit-bad",
        event_kind="metric",
        category="queue",
        stage="dispatch",
        occurred_at=NOW,
        correlation_id=CORRELATION,
        causation_id=None,
        actor="mission-control",
        inputs_provenance={"mission": "m1"},
        policy_version="phase4/v1",
        decision="observe",
        reason_code="ok",
        action="measure",
        result="recorded",
        evidence={"digest": "c" * 64},
        resulting_state={"status": "queued"},
        metrics={"queue_latency_ms": 1.5},
    )
    with pytest.raises(ObservabilityAuditError, match="binary floating point"):
        journal.append(**fields)

    fields["metrics"] = {"queue_latency_ms": "1.5"}
    fields["occurred_at"] = "2026-08-17T10:10:00+03:30"
    with pytest.raises(ObservabilityAuditError, match="must be UTC"):
        journal.append(**fields)


def test_malformed_or_blank_jsonl_fails_closed(tmp_path):
    malformed = tmp_path / "malformed.jsonl"
    malformed.write_text("{}\n\n", encoding="utf-8")
    with pytest.raises(ObservabilityAuditError):
        AuditJournal.read_jsonl(malformed)

    invalid = tmp_path / "invalid.jsonl"
    invalid.write_text(json.dumps({"not": "an audit event"}) + "\n", encoding="utf-8")
    with pytest.raises(ObservabilityAuditError, match="schema mismatch"):
        AuditJournal.read_jsonl(invalid)
