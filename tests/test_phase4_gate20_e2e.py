from __future__ import annotations

import copy

import pytest

from ai_room import evaluate_room_message
from phase4_e2e import Phase4E2EError, run_phase4_gate20, verify_gate20_evidence
from scripts.phase4_gate20_evidence import require_exact_runtime_head

SOURCE_SHA = "1" * 40


def test_full_gate20_path_is_same_sha_paper_only_and_recoverable(tmp_path):
    evidence = run_phase4_gate20(SOURCE_SHA, tmp_path)
    verified = verify_gate20_evidence(evidence, expected_source_sha=SOURCE_SHA)

    assert verified["source_sha"] == SOURCE_SHA
    assert verified["paper_only"] is True
    assert verified["path"] == [
        "validated_data",
        "qualified_strategy",
        "signal",
        "decision",
        "deterministic_risk",
        "paper_fill_position",
        "accounting",
        "dashboard",
        "event_audit",
        "restart_replay",
        "identical_valid_state",
    ]
    assert verified["pipeline"]["risk_allowed"] is True
    assert verified["pipeline"]["paper_event_count"] >= 4
    assert verified["dashboard"]["read_only"] is True
    assert verified["dashboard"]["state_digest"] == verified["pipeline"]["state_digest"]
    assert verified["audit"]["coverage_complete"] is True
    assert verified["audit"]["restart_replay_identical"] is True
    assert verified["recovery"]["paper_replay_identical"] is True
    assert verified["recovery"]["previous_valid_restored"] is True
    assert verified["security"]["airgap_result"] == "independent_paper_airgap_pass"
    assert verified["security"]["live_authority_available"] is False
    assert verified["resources"]["complete"] is True
    assert "deny" not in verified["resources"]["actions"].values()


def test_ai_chat_can_inspect_and_orchestrate_but_not_take_owner_live_authority(tmp_path):
    evidence = run_phase4_gate20(SOURCE_SHA, tmp_path)
    ai = evidence["ai_control"]

    assert ai["observe_allowed"] is True
    assert ai["observe_authority"] == 0
    assert ai["workflow_allowed"] is True
    assert ai["workflow_authority"] == 3
    assert ai["workflow_route"] == "mission-runner"
    assert ai["owner_sensitive_allowed"] is False
    assert ai["owner_sensitive_status"] == "owner_required"
    assert ai["owner_sensitive_reason_code"] == "human_required"


def test_interactive_ai_room_is_persian_aware_and_route_only():
    memory = {
        "schema_version": 2,
        "project": "NEXUS",
        "memory_policy": {
            "repository_is_durable_source": True,
            "chat_is_source_of_truth": False,
            "secrets_allowed": False,
        },
    }
    mission = {
        "mission": {"status": "RUNNING"},
        "queue": {"counts": {"RUNNING": 1}},
        "agents": ["producer", "verifier"],
        "runners": ["cloud", "windows"],
        "local_node": "offline",
        "data": "ready",
        "providers": "ready",
        "paper": "paper-only",
    }
    workflow = evaluate_room_message(
        {
            "session_id": "gate20-session",
            "conversation_id": "gate20-conversation",
            "turn_id": "turn-1",
            "message": "خودمختار ادامه بده تا تمام شود",
        },
        project_memory_snapshot=memory,
        mission_control=mission,
        evaluated_at="2026-08-17T08:00:00Z",
    )
    assert workflow["decision"]["allowed"] is True
    assert workflow["decision"]["authority_level"] == 3
    assert workflow["decision"]["route"] == "mission-runner"
    assert workflow["proposal"]["executed"] is False
    assert workflow["proposal"]["state_mutation"] is False
    assert workflow["privacy"]["server_persisted_transcript"] is False
    assert workflow["privacy"]["external_provider_called"] is False

    owner = evaluate_room_message(
        {
            "session_id": "gate20-session",
            "conversation_id": "gate20-conversation",
            "turn_id": "turn-2",
            "message": "معامله واقعی انجام بده",
        },
        project_memory_snapshot=memory,
        mission_control=mission,
        evaluated_at="2026-08-17T08:00:01Z",
    )
    assert owner["decision"]["allowed"] is False
    assert owner["decision"]["status"] == "owner_required"
    assert owner["decision"]["route"] is None


def test_same_inputs_reproduce_identical_trading_and_recovery_state(tmp_path):
    first = run_phase4_gate20(SOURCE_SHA, tmp_path / "first")
    second = run_phase4_gate20(SOURCE_SHA, tmp_path / "second")

    assert first["pipeline"]["signal_id"] == second["pipeline"]["signal_id"]
    assert first["pipeline"]["last_event_digest"] == second["pipeline"]["last_event_digest"]
    assert first["pipeline"]["state_digest"] == second["pipeline"]["state_digest"]
    assert first["pipeline"]["fill_price"] == second["pipeline"]["fill_price"]
    assert first["recovery"]["checkpoint_digest"] == second["recovery"]["checkpoint_digest"]
    # Audit records may contain measured runtime telemetry, so their chain head is
    # intentionally run-specific. Integrity and replay must still hold independently.
    assert first["audit"]["coverage_complete"] is True
    assert second["audit"]["coverage_complete"] is True
    assert first["audit"]["restart_replay_identical"] is True
    assert second["audit"]["restart_replay_identical"] is True
    assert first["audit"]["event_count"] == second["audit"]["event_count"]


def test_evidence_digest_and_exact_source_sha_are_fail_closed(tmp_path):
    evidence = run_phase4_gate20(SOURCE_SHA, tmp_path)

    with pytest.raises(Phase4E2EError, match="expected source SHA"):
        verify_gate20_evidence(evidence, expected_source_sha="2" * 40)

    tampered = copy.deepcopy(evidence)
    tampered["pipeline"]["risk_allowed"] = False
    with pytest.raises(Phase4E2EError, match="digest mismatch"):
        verify_gate20_evidence(tampered, expected_source_sha=SOURCE_SHA)


def test_mutation_cannot_claim_live_authority_or_writable_dashboard(tmp_path):
    evidence = run_phase4_gate20(SOURCE_SHA, tmp_path)

    live = copy.deepcopy(evidence)
    live["security"]["live_authority_available"] = True
    live.pop("evidence_digest")
    # A caller cannot re-seal arbitrary evidence through the verifier; missing digest fails first.
    with pytest.raises(Phase4E2EError, match="digest mismatch"):
        verify_gate20_evidence(live, expected_source_sha=SOURCE_SHA)

    writable = copy.deepcopy(evidence)
    writable["dashboard"]["read_only"] = False
    with pytest.raises(Phase4E2EError, match="digest mismatch"):
        verify_gate20_evidence(writable, expected_source_sha=SOURCE_SHA)


def test_malformed_source_sha_is_rejected_before_e2e_execution(tmp_path):
    for source_sha in ("short", "g" * 40, "1" * 41):
        with pytest.raises(Phase4E2EError, match="source_sha"):
            run_phase4_gate20(source_sha, tmp_path / source_sha[:8])


def test_final_evidence_runtime_head_must_equal_declared_source_sha():
    assert require_exact_runtime_head(SOURCE_SHA, SOURCE_SHA.upper()) == SOURCE_SHA

    with pytest.raises(Phase4E2EError, match="runtime Git HEAD does not match source_sha"):
        require_exact_runtime_head(SOURCE_SHA, "2" * 40)

    with pytest.raises(Phase4E2EError, match="runtime_git_head"):
        require_exact_runtime_head(SOURCE_SHA, "not-a-sha")
