from __future__ import annotations

import pytest

from recovery_chaos import (
    AtomicRecoveryStore,
    CandidateRejected,
    RecoveryScenario,
    RecoverySupervisor,
    SimulatedCrash,
    matrix_coverage,
    validate_event_window,
)


def fresh():
    store = AtomicRecoveryStore({"cash": "10000", "position": None, "sequence": 7})
    checkpoint = store.snapshot()
    return store, checkpoint, RecoverySupervisor(store)


def test_matrix_covers_every_frozen_gate17_scenario():
    assert set(matrix_coverage()) == {
        "process_crash",
        "runner_restart",
        "local_laptop_offline",
        "provider_outage",
        "partial_write",
        "corrupt_stale_conflicting_state",
        "duplicate_reordered_events",
        "interrupted_paper_operation",
        "malformed_ai_output",
        "unavailable_stale_market_data",
        "partial_artifact_evidence_failure",
    }


@pytest.mark.parametrize("fault_at", ["after_validate", "before_publish"])
def test_crash_before_publish_never_replaces_previous_valid_state(fault_at):
    store, checkpoint, _ = fresh()
    with pytest.raises(SimulatedCrash):
        store.commit_candidate(
            expected_revision=checkpoint.revision,
            candidate_state={"cash": "9000", "position": "candidate", "sequence": 8},
            fault_at=fault_at,
        )
    assert store.snapshot() == checkpoint


def test_process_crash_and_runner_restart_restore_durable_checkpoint():
    for scenario in (RecoveryScenario.PROCESS_CRASH, RecoveryScenario.RUNNER_RESTART):
        store, checkpoint, supervisor = fresh()
        store.commit_candidate(
            expected_revision=0,
            candidate_state={"cash": "9999", "position": "unconfirmed", "sequence": 8},
        )
        decision = supervisor.decide(scenario=scenario, previous_valid=checkpoint)
        assert decision.action == "restore_previous_valid"
        assert decision.reason_code == "restart_from_durable_checkpoint"
        assert store.snapshot() == checkpoint


def test_local_laptop_offline_degrades_and_preserves_state():
    store, checkpoint, supervisor = fresh()
    decision = supervisor.decide(
        scenario=RecoveryScenario.LOCAL_LAPTOP_OFFLINE,
        previous_valid=checkpoint,
        local_node_online=False,
    )
    assert decision.degraded is True
    assert decision.reason_code == "local_node_offline_fail_closed"
    assert store.snapshot() == checkpoint


def test_provider_outage_degrades_without_state_mutation():
    store, checkpoint, supervisor = fresh()
    decision = supervisor.decide(
        scenario=RecoveryScenario.PROVIDER_OUTAGE,
        previous_valid=checkpoint,
        provider_available=False,
    )
    assert decision.degraded is True
    assert decision.reason_code == "provider_unavailable_fail_closed"
    assert store.snapshot() == checkpoint


def test_partial_write_and_corrupt_candidate_preserve_previous_valid():
    store, checkpoint, supervisor = fresh()
    assert supervisor.decide(
        scenario=RecoveryScenario.PARTIAL_WRITE,
        previous_valid=checkpoint,
    ).reason_code == "partial_write_rejected"
    assert supervisor.decide(
        scenario=RecoveryScenario.CORRUPT_STALE_CONFLICTING_STATE,
        previous_valid=checkpoint,
        candidate_state={"bad": {"not-json"}},
    ).reason_code == "corrupt_candidate_rejected"
    assert store.snapshot() == checkpoint


def test_stale_conflicting_candidate_never_replaces_checkpoint():
    store, checkpoint, supervisor = fresh()
    decision = supervisor.decide(
        scenario=RecoveryScenario.CORRUPT_STALE_CONFLICTING_STATE,
        previous_valid=checkpoint,
        candidate_state={"cash": "1", "sequence": 999},
    )
    assert decision.reason_code == "stale_or_conflicting_candidate_rejected"
    assert store.snapshot() == checkpoint


def test_duplicate_or_reordered_event_window_is_rejected():
    store, checkpoint, supervisor = fresh()
    decision = supervisor.decide(
        scenario=RecoveryScenario.DUPLICATE_REORDERED_EVENTS,
        previous_valid=checkpoint,
        event_ids=("e1", "e1"),
        event_sequences=(8, 9),
    )
    assert decision.reason_code == "event_window_invalid"
    assert store.snapshot() == checkpoint

    with pytest.raises(CandidateRejected, match="reordered"):
        validate_event_window(("e1", "e2"), (9, 8))


def test_interrupted_paper_operation_replays_only_from_checkpoint():
    store, checkpoint, supervisor = fresh()
    decision = supervisor.decide(
        scenario=RecoveryScenario.INTERRUPTED_PAPER_OPERATION,
        previous_valid=checkpoint,
        paper_operation_committed=False,
    )
    assert decision.reason_code == "interrupted_paper_operation_replayed_from_checkpoint"
    assert store.snapshot() == checkpoint


def test_malformed_ai_output_is_rejected_without_authority_effect():
    store, checkpoint, supervisor = fresh()
    decision = supervisor.decide(
        scenario=RecoveryScenario.MALFORMED_AI_OUTPUT,
        previous_valid=checkpoint,
        ai_output_valid=False,
    )
    assert decision.reason_code == "malformed_ai_output_rejected"
    assert decision.state_changed is False
    assert store.snapshot() == checkpoint


@pytest.mark.parametrize("status", ["unavailable", "stale", "ambiguous"])
def test_unavailable_or_stale_market_data_fails_closed(status):
    store, checkpoint, supervisor = fresh()
    decision = supervisor.decide(
        scenario=RecoveryScenario.UNAVAILABLE_STALE_MARKET_DATA,
        previous_valid=checkpoint,
        market_data_status=status,
    )
    assert decision.degraded is True
    assert decision.reason_code == f"market_data_{status}_fail_closed"
    assert store.snapshot() == checkpoint


def test_partial_artifact_or_evidence_failure_is_not_promoted():
    store, checkpoint, supervisor = fresh()
    decision = supervisor.decide(
        scenario=RecoveryScenario.PARTIAL_ARTIFACT_EVIDENCE_FAILURE,
        previous_valid=checkpoint,
        artifact_complete=False,
    )
    assert decision.reason_code == "partial_evidence_rejected"
    assert store.snapshot() == checkpoint


def test_scenario_claim_without_matching_failure_evidence_is_rejected():
    store, checkpoint, supervisor = fresh()
    with pytest.raises(CandidateRejected, match="offline evidence"):
        supervisor.decide(
            scenario=RecoveryScenario.LOCAL_LAPTOP_OFFLINE,
            previous_valid=checkpoint,
            local_node_online=True,
        )
    with pytest.raises(CandidateRejected, match="outage evidence"):
        supervisor.decide(
            scenario=RecoveryScenario.PROVIDER_OUTAGE,
            previous_valid=checkpoint,
            provider_available=True,
        )
    with pytest.raises(CandidateRejected, match="invalid output evidence"):
        supervisor.decide(
            scenario=RecoveryScenario.MALFORMED_AI_OUTPUT,
            previous_valid=checkpoint,
            ai_output_valid=True,
        )


def test_restore_rejects_tampered_checkpoint():
    store, checkpoint, _ = fresh()
    tampered = type(checkpoint)(checkpoint.revision, {"cash": "0"}, checkpoint.state_digest)
    with pytest.raises(CandidateRejected, match="digest mismatch"):
        store.restore(tampered)
    assert store.snapshot() == checkpoint
