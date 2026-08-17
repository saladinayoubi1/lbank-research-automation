from __future__ import annotations

import sqlite3
from copy import deepcopy

import pytest

import phase5_attempts as attempts
import phase5_mission_contract as mc
import phase5_shadow_migration as migration
import phase5_state_store as state
import phase5_verification as verification
import phase5_worker_policy as workers

SOURCE_SHA = "a" * 64


def worker_config():
    return {
        "workers": [
            {"id": "cloud", "trust_domain": "github-cloud", "capabilities": ["implementation"], "resources": ["github-cloud"], "authority_max": 3, "enabled": True, "verifier": False, "max_concurrent_tasks": 2},
            {"id": "windows", "trust_domain": "windows-local", "capabilities": ["implementation", "integration_tests"], "resources": ["windows-local"], "authority_max": 3, "enabled": True, "verifier": True, "max_concurrent_tasks": 1},
            {"id": "deepseek", "trust_domain": "deepseek-external", "capabilities": ["diagnostics"], "resources": ["deepseek"], "authority_max": 2, "enabled": True, "verifier": False, "max_concurrent_tasks": 1},
        ]
    }


def runtime(worker_id, health="online", active=0, paid=False):
    return {"worker_id": worker_id, "health": health, "active": active, "estimated_cost_usd": 0.0, "paid_budget_authorized": paid}


def task():
    return {"id": "T", "required_capabilities": ["implementation"], "preferred_resources": ["github-cloud"], "authority": 1}


def verification_config():
    cfg = {
        "schema_version": mc.MISSION_SCHEMA, "mission_id": "chaos", "mission_revision": 1, "phase": 5,
        "policy": {"version": "p1", "max_parallel_tasks": 1},
        "workers": [
            {"id": "producer", "trust_domain": "github-cloud", "capabilities": ["implementation"], "resources": ["github-cloud"], "authority_max": 3, "enabled": True, "verifier": False},
            {"id": "windows", "trust_domain": "windows-local", "capabilities": ["integration_tests"], "resources": ["windows-local"], "authority_max": 3, "enabled": True, "verifier": True},
        ],
        "tasks": [{
            "id": "T", "title": "verify", "phase": 5, "gate": 8, "status": "RUNNING", "priority": 1,
            "dependencies": [], "required_capabilities": ["implementation"], "preferred_resources": ["github-cloud"],
            "authority": 1, "acceptance": ["independent evidence"],
            "verification": {"mode": "independent_trust_domain", "required_capabilities": ["integration_tests"]},
        }],
    }
    return mc.to_agent_manager_config(cfg)


def test_restart_and_corrupted_state_recover_previous_valid_without_reset(tmp_path):
    path = tmp_path / "state.sqlite3"
    store = state.SQLiteStateStore(path)
    first = store.compare_and_swap("m", None, {"decision": "hold"})
    store.compare_and_swap("m", 0, {"decision": "paper-only"})
    restarted = state.SQLiteStateStore(path)
    assert restarted.load_current("m").payload == {"decision": "paper-only"}

    with sqlite3.connect(path) as conn:
        conn.execute("UPDATE snapshots SET payload_json=? WHERE mission_id=? AND generation=?", ('{\"decision\":\"tampered\"}', "m", 1))
        conn.commit()
    with pytest.raises(state.StateCorruption):
        restarted.load_current("m")
    recovered = restarted.recover_to_previous_valid("m", expected_tip_generation=1)
    assert recovered.payload == first.payload
    assert recovered.quarantined_generations == (1,)


def test_stale_lease_and_duplicate_callback_are_fenced_and_idempotent():
    t = {"mission_id": "m", "id": "T", "spec_digest": "b" * 64, "authority": 1, "status": "RUNNING"}
    old = attempts.begin_attempt(t, worker_id="cloud", lease_id="L1", source_sha=SOURCE_SHA, state_generation=0)
    current = attempts.begin_attempt(t, worker_id="windows", lease_id="L2", source_sha=SOURCE_SHA, state_generation=1)
    with pytest.raises(attempts.StaleAttempt):
        attempts.accept_result(t, attempts.build_result(old, outcome="success", evidence={"stale": True}))
    result = attempts.build_result(current, outcome="success", evidence={"ok": True})
    assert attempts.accept_result(t, result) is True
    assert attempts.accept_result(t, deepcopy(result)) is False


def test_provider_github_and_windows_outages_fail_closed_then_reconnect():
    cfg = worker_config()
    blocked = workers.route_task(
        cfg, task(),
        {"schema_version": workers.WORKER_RUNTIME_SCHEMA, "workers": [runtime("cloud", "offline"), runtime("windows", "offline"), runtime("deepseek", "offline")]},
    )
    assert blocked["status"] == "blocked"

    github_out = workers.route_task(
        cfg, task(),
        {"schema_version": workers.WORKER_RUNTIME_SCHEMA, "workers": [runtime("cloud", "offline"), runtime("windows", "online"), runtime("deepseek", "offline")]},
    )
    assert github_out["worker_id"] == "windows"

    reconnected = workers.route_task(
        cfg, task(),
        {"schema_version": workers.WORKER_RUNTIME_SCHEMA, "workers": [runtime("cloud", "offline"), runtime("windows", "online"), runtime("deepseek", "offline")]},
    )
    assert reconnected["status"] == "routed"
    assert reconnected["worker_id"] == "windows"


def test_partial_independent_evidence_blocks_completion():
    config = verification_config()
    t = config["tasks"][0]
    issued = attempts.begin_attempt(t, worker_id="producer", lease_id="L", source_sha=SOURCE_SHA, state_generation=0)
    result = attempts.build_result(issued, outcome="success", evidence={"producer": "claims-success"})
    attempts.accept_result(t, result)
    manifest = verification.build_verification_manifest(
        config, t, result, verifier_id="windows",
        checks=[{"name": "partial-evidence", "passed": False, "evidence_sha256": "c" * 64}], artifacts=[],
    )
    verification.accept_verification(config, t, result, manifest)
    assert t["status"] == "BLOCKED"
    assert t["blocked_reason"] == "independent_verification_failed"


def test_shadow_parity_and_all_chaos_are_required_for_cutover():
    chaos = {name: True for name in migration.CHAOS_CASES}
    report = migration.build_shadow_report({"next": "A"}, {"next": "A"}, chaos)
    assert report["exact_parity"] is True
    assert report["cutover_ready"] is True
    assert report["legacy_mode"] == "watchdog_fallback"
    assert migration.validate_shadow_report(report) == report

    failed = dict(chaos)
    failed["windows_offline_reconnect"] = False
    report = migration.build_shadow_report({"next": "A"}, {"next": "A"}, failed)
    assert report["cutover_ready"] is False


def test_unexplained_shadow_difference_never_cuts_over():
    report = migration.build_shadow_report(
        {"next": "A"}, {"next": "B"}, {name: True for name in migration.CHAOS_CASES}
    )
    assert report["exact_parity"] is False
    assert report["parity_accepted"] is False
    assert report["cutover_ready"] is False
