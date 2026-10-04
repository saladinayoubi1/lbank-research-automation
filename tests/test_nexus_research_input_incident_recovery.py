"""Exact incident requeue, ordinary input/QA gates, and adversarial provenance."""
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path

import pytest

import agent_manager as am
import agent_manager_runner as runner
import agent_transport as at
from nexus_research_missions import NINTH, TENTH, TASKS, PREDECESSOR, attested_predecessor
from scripts import nexus_research_input_incident_recovery as recovery

CURRENT = "c" * 40


def incident():
    spec = recovery.load_spec()
    config = am.load_config(Path("config/nexus-agent-manager.json"))
    tasks = am.task_index(config)
    for task in config["tasks"]:
        if task["id"] != TENTH:
            task["status"] = "DONE"
    prior = tasks[NINTH]
    binding = spec["predecessor"]
    prior.update(
        producer="research-agent", verifier="qa-verifier-agent", research_producer_lease_id="ninth-producer",
        result_evidence={
            "executor": "nexus-real-composite-backtest", "independent_qa_complete": False,
            "source_sha": binding["research_predecessor_source_sha"],
            "receipt_digest": binding["research_predecessor_receipt_digest"],
            "ledger_digest": binding["research_predecessor_ledger_digest"],
            "mechanism": binding["research_predecessor_mechanism"],
            "prior_ledger_digest": "a" * 64, "config_fingerprint": "b" * 64,
            "auto_demo_promotion": False, "live_enabled": False,
        },
        verification_evidence={
            "executor": "nexus-independent-composite-numeric-qa", "independent_qa_complete": True,
            "source_sha": binding["research_predecessor_source_sha"],
            "producer_receipt_digest": binding["research_predecessor_receipt_digest"],
            "producer_lease_id": "ninth-producer", "qa_digest": binding["research_predecessor_qa_digest"],
            "auto_demo_promotion": False, "live_enabled": False,
        },
    )
    for task_id in sorted(TASKS - {NINTH, TENTH}):
        item = tasks[task_id]
        item.update(producer="research-agent", verifier="qa-verifier-agent",
                    research_producer_lease_id=task_id + "-producer")
        item["result_evidence"] = {**prior["result_evidence"], "mechanism": "earlier_reviewed_mechanism"}
        item["verification_evidence"] = {
            **prior["verification_evidence"], "producer_lease_id": item["research_producer_lease_id"],
        }
    for successor, predecessor in PREDECESSOR.items():
        if successor != TENTH:
            tasks[successor].update(attested_predecessor(tasks[predecessor]))
    task = tasks[TENTH]
    task.update(
        **binding, status="RUNNING", producer="research-agent", assigned_worker="architect-agent",
        attempt=2, research_cache_recovery_count=1, triage_mode="root_cause_first",
        lease_id="wrong-architect-lease", dispatch_id="e" * 32,
        failure_class=recovery.FAILURE["failure_class"], failure_evidence=deepcopy(recovery.FAILURE),
        research_cache_race_evidence={"first_failed_lease_id": spec["first_failed_lease_id"],
                                      "first_failure": deepcopy(recovery.FAILURE)},
        triage_evidence={"worker_id": "architect-agent", "preserved_original_failure": True,
                         "evidence": {k: v for k, v in recovery.FAILURE.items() if k != "reason"}},
        external_wait_timeline=[{
            "dispatch_id": spec["failed_dispatch_id"], "worker_id": "research-agent",
            "transport": "github-cloud", "from_status": "LEASED", "outcome": "failure",
            "started_at": "2026-10-03T11:58:42.838064+00:00",
        }],
    )
    task["triage_evidence"]["evidence"]["failure_class"] = "research_lease_worker_phase_or_transport_mismatch"
    return config, spec, task


def proofs(spec):
    return {
        f"repos/{recovery.REPO}/actions/runs/{spec['failed_run_id']}": {
            "id": spec["failed_run_id"], "name": "NEXUS Runtime Worker",
            "path": ".github/workflows/nexus-runtime-worker.yml", "head_branch": "main",
            "head_sha": spec["failed_source_sha"], "status": "completed", "conclusion": "success",
            "event": "workflow_dispatch", "created_at": "2026-10-03T11:58:42Z",
            "repository": {"full_name": recovery.REPO}, "head_repository": {"full_name": recovery.REPO},
            "actor": {"login": "github-actions[bot]"},
        },
        f"repos/{recovery.REPO}/actions/runs/{spec['failed_run_id']}/artifacts?per_page=100": {
            "artifacts": [{"id": spec["failed_artifact_id"], "expired": False,
                           "name": "nexus-agent-result-" + spec["failed_lease_id"],
                           "digest": "sha256:" + spec["failed_artifact_digest"],
                           "workflow_run": {"head_sha": spec["failed_source_sha"]}}],
        },
        f"repos/{recovery.REPO}/compare/{spec['fix_commit_sha']}...{CURRENT}": {
            "status": "ahead", "base_commit": {"sha": spec["fix_commit_sha"]},
            "merge_base_commit": {"sha": spec["fix_commit_sha"]},
        },
        f"repos/{recovery.REPO}/contents/nexus_agent_research_prepare.py?ref={CURRENT}": {
            "type": "file", "sha": spec["fix_prepare_blob_sha"],
        },
    }


@pytest.fixture(autouse=True)
def context(monkeypatch):
    monkeypatch.setenv("GITHUB_REPOSITORY", recovery.REPO)
    monkeypatch.setenv("GITHUB_REF", "refs/heads/main")
    monkeypatch.setenv("GITHUB_SHA", CURRENT)
    monkeypatch.setattr(am, "emit", lambda *a, **k: None)


def test_exact_incident_requeues_once_through_input_and_independent_qa_gates():
    config, spec, task = incident()
    proof = proofs(spec)
    old = deepcopy(task)
    assert recovery.recover_incident(config, spec=spec, current_sha=CURRENT, api_get=proof.__getitem__)
    assert task["status"] == "PENDING" and task["lease_id"] is None
    assert task["attempt"] == 2 and task["failure_evidence"] == old["failure_evidence"]
    assert task["external_wait_timeline"] == old["external_wait_timeline"]
    assert runner.apply_research_input_gate(config, ready=False) == "parked_waiting_cache"
    assert task["status"] == "BLOCKED"
    assert runner.apply_research_input_gate(config, ready=True) == "ready_for_producer_lease"
    am.assign_ready_tasks(config, datetime(2026, 10, 4, 4, 0, tzinfo=timezone.utc))
    assert task["assigned_worker"] == "research-agent" and task["attempt"] == 3
    assert task["lease_id"] != old["lease_id"]
    producer_lease = task["lease_id"]
    receipt = {
        "receipt_digest": "d" * 64, "source_sha": CURRENT, "independent_qa_complete": False,
        "prior_ledger_digest": spec["predecessor"]["research_predecessor_ledger_digest"],
        "mechanism": "new_reviewed_frontier_mechanism", "auto_demo_promotion": False, "live_enabled": False,
    }
    am.record_result(config, TENTH, "research-agent", "success", receipt)
    assert task["status"] == "VERIFYING" and task["assigned_worker"] == "qa-verifier-agent"
    assert task["research_producer_lease_id"] == producer_lease
    assert not recovery.recover_incident(config, spec=spec, current_sha=CURRENT, api_get=proof.__getitem__)
    assert "verification_evidence" not in task


def test_recovery_marker_survives_definition_merge_and_new_failure_cannot_recover():
    config, spec, task = incident()
    assert recovery.recover_incident(config, spec=spec, current_sha=CURRENT, api_get=proofs(spec).__getitem__)
    merged = runner.merge_definition(am.load_config(Path("config/nexus-agent-manager.json")), config)
    restored = am.task_index(merged)[TENTH]
    assert restored["research_input_incident_recovery"] == task["research_input_incident_recovery"]
    restored.update(status="TRIAGE", triage_mode="root_cause_first", attempt=3)
    assert not recovery.recover_incident(merged, spec=spec, current_sha=CURRENT, api_get=proofs(spec).__getitem__)
    am.route_triage(merged, datetime(2026, 10, 4, 4, 0, tzinfo=timezone.utc))
    assert restored["status"] == "BLOCKED" and restored["assigned_worker"] is None


@pytest.mark.parametrize("change", [
    {"authority": 4}, {"status": "DONE"}, {"attempt": 3}, {"verifier": "qa-verifier-agent"},
    {"result_evidence": {"receipt_digest": "a" * 64}}, {"triage_evidence": "malformed"},
    {"research_predecessor_ledger_digest": "f" * 64},
    {"status": "BLOCKED", "blocked_reason": "security incident"},
    {"failure_evidence": {**recovery.FAILURE, "reason": "digest mismatch"}},
])
def test_unrelated_or_already_executed_incident_is_not_mutated(change):
    config, spec, task = incident()
    task.update(change)
    original = deepcopy(config)
    def forbidden_api(endpoint):
        raise AssertionError("unrelated incident must not consult recovery proof")
    assert not recovery.recover_incident(config, spec=spec, current_sha=CURRENT, api_get=forbidden_api)
    assert config == original


@pytest.mark.parametrize("part,field,value", [
    ("run", "head_sha", "b" * 40), ("run", "created_at", "2026-10-03T12:00:42Z"),
    ("artifact", "digest", "sha256:" + "b" * 64), ("artifact", "expired", True),
    ("compare", "status", "diverged"), ("preparation", "sha", "b" * 40),
])
def test_changed_external_proof_fails_closed_without_state_mutation(part, field, value):
    config, spec, _ = incident()
    proof = proofs(spec)
    run, artifacts, compare, preparation = list(proof.values())
    targets = {"run": run, "artifact": artifacts["artifacts"][0], "compare": compare, "preparation": preparation}
    targets[part][field] = value
    original = deepcopy(config)
    assert not recovery.recover_incident(config, spec=spec, current_sha=CURRENT, api_get=proof.__getitem__)
    assert config == original


def test_non_main_context_and_unavailable_proof_cannot_requeue(monkeypatch):
    config, spec, _ = incident()
    original = deepcopy(config)
    monkeypatch.setenv("GITHUB_REF", "refs/heads/feature")
    assert not recovery.recover_incident(config, spec=spec, current_sha=CURRENT, api_get=proofs(spec).__getitem__)
    monkeypatch.setenv("GITHUB_REF", "refs/heads/main")
    def unavailable(endpoint):
        raise RuntimeError("network unavailable")
    assert not recovery.recover_incident(config, spec=spec, current_sha=CURRENT, api_get=unavailable)
    assert config == original


def test_manifest_rejects_live_authority_and_unknown_fields(tmp_path):
    spec = recovery.load_spec()
    path = tmp_path / "spec.json"
    for change in ({"live_enabled": True}, {"unknown": "unreviewed"}, {"failed_run_id": True}):
        path.write_text(json.dumps({**spec, **change}))
        with pytest.raises(ValueError, match="contract invalid"):
            recovery.load_spec(path)
