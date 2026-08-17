from copy import deepcopy
import json

import pytest

from mission_control import (
    MissionControlError,
    apply_command,
    create_mission,
    load_state,
    mark_running,
    mission_control_projection,
    reconcile_restart,
    record_result,
    save_state,
    schedule,
    validate_state,
)

NOW = "2026-08-17T08:00:00Z"
LATER = "2026-08-17T08:01:00Z"
EVIDENCE = "a" * 64


def task(task_id="T1", **changes):
    value = {
        "task_id": task_id,
        "idempotency_key": f"idem-{task_id}",
        "title": f"Task {task_id}",
        "priority": 50,
        "dependencies": [],
        "authority": 2,
        "owner_group": "cloud",
        "timeout_seconds": 120,
        "max_attempts": 2,
        "requires_local_node": False,
        "circuit_requirements": [],
    }
    value.update(changes)
    return value


def spec(tasks=None, **changes):
    value = {
        "schema_version": 1,
        "mission_id": "mission-13",
        "idempotency_key": "mission-idem-13",
        "title": "Gate 13 mission",
        "priority": 80,
        "authority": 3,
        "deadline_at": "2026-08-17T10:00:00Z",
        "max_parallel_tasks": 2,
        "tasks": tasks or [task()],
    }
    value.update(changes)
    return value


def policy(**changes):
    value = {
        "schema_version": 1,
        "max_mission_authority": 3,
        "max_task_authority": 3,
        "max_attempts": 2,
        "max_timeout_seconds": 300,
        "max_parallel_tasks": 3,
        "max_notifications": 30,
    }
    value.update(changes)
    return value


def environment(**changes):
    value = {
        "local_node_online": True,
        "resource_limited": False,
        "budget_limited": False,
        "circuits": {"provider": False, "data": False, "strategy": False, "risk": False},
        "owners": {"cloud": ["agent-b", "agent-a"], "local": ["runner-1"]},
        "agents": ["agent-a", "agent-b"],
        "runners": ["runner-1"],
        "data_state": "ready",
        "provider_state": "ready",
        "paper_state": "paper-only",
    }
    value.update(changes)
    return value


def state(tasks=None, **changes):
    return create_mission(spec(tasks, **changes), policy(), created_at=NOW)


def success_result(lease, **changes):
    value = {
        "command_id": "result-1",
        "task_id": lease["task_id"],
        "lease_id": lease["lease_id"],
        "owner_id": lease["owner_id"],
        "outcome": "success",
        "failure_class": None,
        "evidence_digest": EVIDENCE,
    }
    value.update(changes)
    return value


def test_priority_and_dependency_order_are_deterministic():
    s = state([
        task("A", priority=10),
        task("B", priority=100),
        task("C", priority=90, dependencies=["B"]),
    ])
    scheduled, leases = schedule(s, environment(), policy(), now=LATER)
    assert [lease["task_id"] for lease in leases] == ["B", "A"]
    by_id = {item["task_id"]: item for item in scheduled["tasks"]}
    assert by_id["C"]["status"] == "PENDING"
    assert by_id["B"]["assigned_owner"] == "agent-a"


def test_dependency_cycle_and_unknown_dependency_fail_closed():
    with pytest.raises(MissionControlError, match="cycle"):
        state([task("A", dependencies=["B"]), task("B", dependencies=["A"])])
    with pytest.raises(MissionControlError, match="unknown dependency"):
        state([task("A", dependencies=["missing"])])


def test_task_and_mission_idempotency_keys_must_be_unique():
    duplicate = task("B", idempotency_key="idem-T1")
    with pytest.raises(MissionControlError, match="idempotency"):
        state([task("T1"), duplicate])


def test_l4_mission_and_task_are_owner_required_not_dispatched():
    mission = create_mission(spec(authority=4), policy(), created_at=NOW)
    assert mission["status"] == "OWNER_REQUIRED"
    assert any(note["kind"] == "owner_required" for note in mission["notifications"])
    scheduled, leases = schedule(mission, environment(), policy(), now=LATER)
    assert leases == ()

    task_owner = state([task(authority=4)])
    assert task_owner["tasks"][0]["status"] == "OWNER_REQUIRED"


def test_parallelism_is_bounded_and_dispatch_key_is_attempt_idempotent():
    s = state([task("A"), task("B"), task("C")], max_parallel_tasks=2)
    scheduled, leases = schedule(s, environment(), policy(), now=LATER)
    assert len(leases) == 2
    assert len({lease["dispatch_key"] for lease in leases}) == 2
    repeated, repeated_leases = schedule(scheduled, environment(), policy(), now=LATER)
    assert repeated_leases == ()
    assert repeated == scheduled


def test_lease_ownership_is_enforced_for_running_and_results():
    scheduled, leases = schedule(state(), environment(), policy(), now=LATER)
    lease = leases[0]
    with pytest.raises(MissionControlError, match="ownership"):
        mark_running(scheduled, task_id=lease["task_id"], lease_id=lease["lease_id"], owner_id="spoof", now=LATER)
    running = mark_running(scheduled, task_id=lease["task_id"], lease_id=lease["lease_id"], owner_id=lease["owner_id"], now=LATER)
    with pytest.raises(MissionControlError, match="ownership"):
        record_result(running, success_result(lease, owner_id="spoof"), policy(), now="2026-08-17T08:02:00Z")


def test_success_releases_lease_and_completes_mission():
    scheduled, leases = schedule(state(), environment(), policy(), now=LATER)
    lease = leases[0]
    running = mark_running(scheduled, task_id=lease["task_id"], lease_id=lease["lease_id"], owner_id=lease["owner_id"], now=LATER)
    done = record_result(running, success_result(lease), policy(), now="2026-08-17T08:02:00Z")
    assert done["tasks"][0]["status"] == "DONE"
    assert done["tasks"][0]["lease_id"] is None
    assert done["status"] == "DONE"


def test_duplicate_result_command_is_idempotent():
    scheduled, leases = schedule(state(), environment(), policy(), now=LATER)
    lease = leases[0]
    done = record_result(scheduled, success_result(lease), policy(), now="2026-08-17T08:02:00Z")
    duplicate = record_result(done, success_result(lease), policy(), now="2026-08-17T08:03:00Z")
    assert duplicate == done


def test_only_explicit_transient_failures_get_one_bounded_retry():
    scheduled, leases = schedule(state(), environment(), policy(), now=LATER)
    lease = leases[0]
    failed = record_result(
        scheduled,
        success_result(lease, outcome="failure", failure_class="provider_unavailable"),
        policy(),
        now="2026-08-17T08:02:00Z",
    )
    assert failed["tasks"][0]["status"] == "READY"
    assert any(note["kind"] == "recovery" for note in failed["notifications"])
    retried, second = schedule(failed, environment(), policy(), now="2026-08-17T08:03:00Z")
    assert len(second) == 1
    assert retried["tasks"][0]["attempt"] == 2

    final = record_result(
        retried,
        success_result(second[0], command_id="result-2", outcome="failure", failure_class="provider_unavailable"),
        policy(),
        now="2026-08-17T08:04:00Z",
    )
    assert final["tasks"][0]["status"] == "BLOCKED"
    assert final["tasks"][0]["blocked_reason"] == "root_cause_required"


def test_persistent_failure_does_not_blind_retry():
    scheduled, leases = schedule(state(), environment(), policy(), now=LATER)
    failed = record_result(
        scheduled,
        success_result(leases[0], outcome="failure", failure_class="invalid_data"),
        policy(),
        now="2026-08-17T08:02:00Z",
    )
    assert failed["tasks"][0]["status"] == "BLOCKED"
    assert failed["tasks"][0]["blocked_reason"] == "root_cause_required"
    assert any(note["kind"] == "failure" for note in failed["notifications"])


def test_local_node_offline_blocks_and_recovery_unblocks():
    s = state([task(owner_group="local", requires_local_node=True)])
    offline = environment(local_node_online=False)
    blocked, leases = schedule(s, offline, policy(), now=LATER)
    assert leases == ()
    assert blocked["tasks"][0]["blocked_reason"] == "local_node_offline"
    recovered = reconcile_restart(blocked, environment(), policy(), now="2026-08-17T08:02:00Z")
    assert recovered["tasks"][0]["status"] == "READY"
    assert any(note["kind"] == "recovery" for note in recovered["notifications"])


def test_provider_data_strategy_and_risk_circuits_fail_closed():
    for circuit in ("provider", "data", "strategy", "risk"):
        s = state([task(circuit_requirements=[circuit])])
        circuits = {"provider": False, "data": False, "strategy": False, "risk": False}
        circuits[circuit] = True
        blocked, leases = schedule(s, environment(circuits=circuits), policy(), now=LATER)
        assert leases == ()
        assert blocked["tasks"][0]["blocked_reason"] == f"{circuit}_circuit_open"


def test_stale_data_budget_and_resource_limits_generate_notifications():
    stale, _ = schedule(
        state([task(circuit_requirements=["data"])]),
        environment(data_state="stale"), policy(), now=LATER,
    )
    assert stale["tasks"][0]["blocked_reason"] == "stale_data"
    assert any(note["kind"] == "stale_data" for note in stale["notifications"])

    budget, _ = schedule(state(), environment(budget_limited=True), policy(), now=LATER)
    assert budget["tasks"][0]["blocked_reason"] == "budget_limit"
    assert any(note["kind"] == "budget_limit" for note in budget["notifications"])

    resource, _ = schedule(state(), environment(resource_limited=True), policy(), now=LATER)
    assert resource["tasks"][0]["blocked_reason"] == "resource_limit"
    assert any(note["kind"] == "resource_limit" for note in resource["notifications"])


def test_restart_recovery_requeues_expired_lease_without_duplicate_dispatch():
    scheduled, leases = schedule(
        state([task(timeout_seconds=60)]), environment(), policy(), now=LATER
    )
    old_dispatch = leases[0]["dispatch_key"]
    recovered = reconcile_restart(scheduled, environment(), policy(), now="2026-08-17T08:02:01Z")
    assert recovered["tasks"][0]["status"] == "READY"
    assert recovered["tasks"][0]["dispatch_key"] is None
    rescheduled, leases2 = schedule(recovered, environment(), policy(), now="2026-08-17T08:03:00Z")
    assert leases2[0]["dispatch_key"] != old_dispatch
    assert rescheduled["tasks"][0]["attempt"] == 2


def test_restart_after_retry_budget_exhaustion_fails_closed():
    s = state([task(timeout_seconds=60, max_attempts=1)])
    scheduled, _ = schedule(s, environment(), policy(), now=LATER)
    recovered = reconcile_restart(scheduled, environment(), policy(), now="2026-08-17T08:02:01Z")
    assert recovered["tasks"][0]["status"] == "FAILED"
    assert recovered["status"] == "FAILED"
    assert any(note["reason_code"] == "retry_exhausted" for note in recovered["notifications"])


def test_timeout_deadline_cancels_remaining_work_fail_closed():
    s = create_mission(
        spec(deadline_at="2026-08-17T08:01:30Z"), policy(), created_at=NOW
    )
    expired, leases = schedule(s, environment(), policy(), now="2026-08-17T08:01:31Z")
    assert leases == ()
    assert expired["status"] == "FAILED"
    assert expired["tasks"][0]["status"] == "FAILED"
    assert any(note["reason_code"] == "mission_deadline_exceeded" for note in expired["notifications"])


def test_pause_resume_cancel_and_command_idempotency():
    s = state()
    pause = {"command_id": "cmd-1", "action": "pause_mission", "task_id": None, "notification_id": None}
    paused = apply_command(s, pause, policy(), now=LATER)
    assert paused["status"] == "PAUSED"
    assert apply_command(paused, pause, policy(), now="2026-08-17T08:02:00Z") == paused
    _, leases = schedule(paused, environment(), policy(), now="2026-08-17T08:02:00Z")
    assert leases == ()

    resumed = apply_command(
        paused,
        {"command_id": "cmd-2", "action": "resume_mission", "task_id": None, "notification_id": None},
        policy(), now="2026-08-17T08:03:00Z",
    )
    assert resumed["status"] == "READY"
    cancelled = apply_command(
        resumed,
        {"command_id": "cmd-3", "action": "cancel_mission", "task_id": None, "notification_id": None},
        policy(), now="2026-08-17T08:04:00Z",
    )
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["tasks"][0]["status"] == "CANCELLED"


def test_cancel_task_is_bounded_and_does_not_mutate_other_task():
    s = state([task("A"), task("B")])
    cancelled = apply_command(
        s,
        {"command_id": "cmd-cancel", "action": "cancel_task", "task_id": "A", "notification_id": None},
        policy(), now=LATER,
    )
    by_id = {item["task_id"]: item for item in cancelled["tasks"]}
    assert by_id["A"]["status"] == "CANCELLED"
    assert by_id["B"]["status"] == "PENDING"


def test_notification_acknowledgement_is_durable_and_idempotent():
    blocked, _ = schedule(state(), environment(budget_limited=True), policy(), now=LATER)
    note = blocked["notifications"][0]
    command = {"command_id": "ack-1", "action": "ack_notification", "task_id": None, "notification_id": note["notification_id"]}
    acked = apply_command(blocked, command, policy(), now="2026-08-17T08:02:00Z")
    assert acked["notifications"][0]["acknowledged"] is True
    assert apply_command(acked, command, policy(), now="2026-08-17T08:03:00Z") == acked


def test_state_is_digest_bound_and_atomic_persistence_recovers_exact_state(tmp_path):
    scheduled, _ = schedule(state(), environment(), policy(), now=LATER)
    path = tmp_path / "mission.json"
    save_state(path, scheduled)
    assert load_state(path) == scheduled

    tampered = json.loads(path.read_text(encoding="utf-8"))
    tampered["priority"] = 999
    path.write_text(json.dumps(tampered), encoding="utf-8")
    with pytest.raises(MissionControlError, match="digest mismatch"):
        load_state(path)


def test_projection_contains_queue_agents_runners_data_providers_paper_and_notifications():
    blocked, _ = schedule(state(), environment(budget_limited=True), policy(), now=LATER)
    projection = mission_control_projection(blocked, environment(budget_limited=True))
    assert projection["contract_version"] == "nexus.mission-control.read.v1"
    assert projection["queue"]["total"] == 1
    assert projection["agents"] == ["agent-a", "agent-b"]
    assert projection["runners"] == ["runner-1"]
    assert projection["data"] == "ready"
    assert projection["providers"] == "ready"
    assert projection["paper"] == "paper-only"
    assert projection["limits"]["budget_limited"] is True
    assert projection["notifications"]


def test_inputs_are_not_mutated_and_same_input_same_output():
    s = state()
    env = environment()
    pol = policy()
    original_s, original_env, original_pol = deepcopy(s), deepcopy(env), deepcopy(pol)
    first = schedule(s, env, pol, now=LATER)
    second = schedule(s, env, pol, now=LATER)
    assert first == second
    assert s == original_s
    assert env == original_env
    assert pol == original_pol


def test_unknown_fields_and_policy_expansion_fail_closed():
    bad = spec()
    bad["live_order"] = True
    with pytest.raises(MissionControlError, match="schema mismatch"):
        create_mission(bad, policy(), created_at=NOW)
    with pytest.raises(MissionControlError, match="L4"):
        create_mission(spec(), policy(max_task_authority=4), created_at=NOW)


def test_validate_state_rejects_tamper_in_memory():
    s = state()
    tampered = deepcopy(s)
    tampered["tasks"][0]["priority"] = 999
    with pytest.raises(MissionControlError, match="digest mismatch"):
        validate_state(tampered)
