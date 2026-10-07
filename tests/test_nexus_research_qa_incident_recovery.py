"""Adversarial one-shot fifth Research QA recovery and ancestor dispatch tests."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest

import agent_manager as am
import agent_transport as at
from nexus_research_missions import FIFTH, FOURTH, ANCESTRY
from scripts import nexus_research_qa_incident_recovery as recovery


def failed_qa_metadata(spec, *, source=None):
    return {
        "id": spec["failed_qa_run_id"], "name": "NEXUS Runtime Worker",
        "path": ".github/workflows/nexus-runtime-worker.yml",
        "head_branch": "main", "head_sha": source or spec["failed_qa_head_sha"],
        "status": "completed", "conclusion": "failure",
        "event": "workflow_dispatch",
        "repository": {"full_name": recovery.REPO},
        "head_repository": {"full_name": recovery.REPO},
        "actor": {"login": "github-actions[bot]"},
        "created_at": "2026-09-29T18:00:17Z",
    }


def failed_qa_jobs():
    return {"jobs": [{
        "name": "preflight", "conclusion": "failure",
        "steps": [{
            "name": "Inspect authorized real Research Agent lease before expensive cache restores",
            "conclusion": "failure",
        }],
    }]}


def authorized_config():
    spec = recovery.load_spec()
    config = am.load_config(Path("config/nexus-agent-manager.json"))
    tasks = {task["id"]: task for task in config["tasks"]}
    fourth, fifth = tasks[FOURTH], tasks[FIFTH]
    old_source = "c" * 40
    predecessor_evidence = {
        "executor": "nexus-real-composite-backtest", "source_sha": old_source,
        "receipt_digest": "1" * 64, "ledger_digest": "2" * 64,
        "prior_ledger_digest": "3" * 64, "config_fingerprint": "4" * 64,
        "mechanism": "lagged_peer_impulse_confirmation",
        "independent_qa_complete": False, "auto_demo_promotion": False,
        "live_enabled": False,
    }
    fourth.update(
        status="DONE", producer="research-agent", verifier="qa-verifier-agent",
        research_producer_lease_id="signed-fourth-producer",
        result_evidence=predecessor_evidence,
        verification_evidence={
            "executor": "nexus-independent-composite-numeric-qa",
            "source_sha": old_source,
            "producer_lease_id": "signed-fourth-producer",
            "producer_receipt_digest": predecessor_evidence["receipt_digest"],
            "qa_digest": "5" * 64, "independent_qa_complete": True,
            "auto_demo_promotion": False, "live_enabled": False,
        },
    )
    fifth.update({
        "status": "RUNNING", "attempt": 1,
        "assigned_worker": "architect-agent", "producer": "research-agent",
        "verifier": "qa-verifier-agent", "triage_mode": "root_cause_first",
        "lease_id": "architect-new-lease", "dispatch_id": "f" * 32,
        "research_producer_lease_id": spec["producer_lease_id"],
        "result_evidence": {
            "executor": "nexus-real-composite-backtest",
            "lease_id": spec["producer_lease_id"],
            "source_sha": spec["producer_source_sha"],
            "receipt_digest": spec["producer_receipt_digest"],
            "independent_qa_complete": False, "qualification_authority": False,
            "auto_demo_promotion": False, "live_enabled": False,
        },
        "verification_evidence": None,
        "external_wait_timeline": [{
            "worker_id": "qa-verifier-agent",
            "dispatch_id": spec["failed_qa_dispatch_id"],
            "started_at": "2026-09-29T18:00:17.900748+00:00",
        }],
    })
    from nexus_research_missions import attested_predecessor
    proof = attested_predecessor(fourth)
    fifth.update({key: proof[key] for key in ANCESTRY})
    original = deepcopy(fifth)
    original.update(status="VERIFYING", assigned_worker="qa-verifier-agent",
                    lease_id=spec["failed_qa_lease_id"])
    assert at.dispatch_id_for(original) == spec["failed_qa_dispatch_id"], (
        "recovered incident signature no longer matches reviewed task contract"
    )
    return config, spec, fifth


def fake_api(spec, *, bad_run=None, bad_jobs=None):
    def api(url):
        if url.endswith(f"/{spec['failed_qa_run_id']}"):
            return bad_run or failed_qa_metadata(spec)
        if url.endswith(f"/{spec['failed_qa_run_id']}/jobs?per_page=100"):
            return bad_jobs or failed_qa_jobs()
        raise AssertionError("unapproved incident proof URL " + url)
    return api


def test_actual_incident_spec_is_exact_and_non_promoting():
    spec = recovery.load_spec()
    assert spec["producer_source_sha"] != spec["failed_qa_head_sha"]
    assert spec["allow_original_source_qa_only"] is True
    assert spec["automatic_demo_promotion"] is False
    assert spec["live_enabled"] is False


def test_valid_exact_failed_old_qa_releases_only_a_new_independent_lease(monkeypatch):
    config, spec, task = authorized_config()
    monkeypatch.setenv("GITHUB_REPOSITORY", recovery.REPO)
    monkeypatch.setenv("GITHUB_REF", "refs/heads/main")
    monkeypatch.setattr(am, "emit", lambda *a, **k: None)
    assert recovery.recover_incident(
        config, spec=spec, api_get=fake_api(spec), current_sha="b" * 40
    )
    proof = task["research_qa_incident_recovery"]
    assert task["status"] == "VERIFYING"
    assert task["assigned_worker"] == "qa-verifier-agent"
    assert task["producer"] == "research-agent"
    assert task["research_producer_lease_id"] == spec["producer_lease_id"]
    assert task["result_evidence"]["receipt_digest"] == spec["producer_receipt_digest"]
    assert task["verification_evidence"] is None
    assert task["lease_id"] != spec["failed_qa_lease_id"]
    assert proof["new_qa_lease_id"] == task["lease_id"]
    assert proof["independent_qa_complete"] is False
    assert not recovery.recover_incident(
        config, spec=spec, api_get=fake_api(spec), current_sha="b" * 40
    )


@pytest.mark.parametrize("changed", [
    "source", "receipt", "old_dispatch", "qualified", "prior_attestation", "wrong_worker",
])
def test_wrong_or_qualified_predecessor_cannot_recover(monkeypatch, changed):
    config, spec, task = authorized_config()
    monkeypatch.setenv("GITHUB_REPOSITORY", recovery.REPO)
    monkeypatch.setenv("GITHUB_REF", "refs/heads/main")
    if changed == "source":
        task["result_evidence"]["source_sha"] = "e" * 40
    elif changed == "receipt":
        task["result_evidence"]["receipt_digest"] = "e" * 64
    elif changed == "old_dispatch":
        task["external_wait_timeline"][0]["dispatch_id"] = "e" * 32
    elif changed == "qualified":
        task["verification_evidence"] = {"independent_qa_complete": True}
    elif changed == "prior_attestation":
        task["research_predecessor_qa_digest"] = "e" * 64
    else:
        task["assigned_worker"] = "research-agent"
    assert not recovery.recover_incident(
        config, spec=spec, api_get=lambda _: (_ for _ in ()).throw(
            AssertionError("unverified recovery attempted network")
        ), current_sha="b" * 40
    )
    assert task["status"] == "RUNNING"


@pytest.mark.parametrize("tamper", ["head", "successful", "wrong_step", "time"])
def test_failed_old_qa_run_must_really_bind_to_source_worker_and_dispatch(monkeypatch, tamper):
    config, spec, task = authorized_config()
    monkeypatch.setenv("GITHUB_REPOSITORY", recovery.REPO)
    monkeypatch.setenv("GITHUB_REF", "refs/heads/main")
    run = failed_qa_metadata(spec)
    jobs = failed_qa_jobs()
    if tamper == "head":
        run["head_sha"] = spec["producer_source_sha"]
    elif tamper == "successful":
        run["conclusion"] = "success"
    elif tamper == "wrong_step":
        jobs["jobs"][0]["steps"][0]["name"] = "Some unrelated failure"
    else:
        task["external_wait_timeline"][0]["started_at"] = "2026-09-28T01:00:00Z"
    with pytest.raises(recovery.ResearchQaIncidentError):
        recovery.recover_incident(
            config, spec=spec, api_get=fake_api(spec, bad_run=run, bad_jobs=jobs),
            current_sha="b" * 40,
        )
    assert task["status"] == "RUNNING"


def test_only_source_ancestor_recovered_qa_may_dispatch(monkeypatch):
    config, spec, task = authorized_config()
    monkeypatch.setenv("GITHUB_REPOSITORY", recovery.REPO)
    monkeypatch.setenv("GITHUB_REF", "refs/heads/main")
    monkeypatch.setenv("GITHUB_SHA", "b" * 40)
    monkeypatch.setattr(am, "emit", lambda *a, **k: None)
    assert recovery.recover_incident(
        config, spec=spec, api_get=fake_api(spec), current_sha="b" * 40
    )
    calls = []
    comparison = {
        "status": "ahead", "ahead_by": 4, "behind_by": 0,
        "base_commit": {"sha": spec["producer_source_sha"]},
        "merge_base_commit": {"sha": spec["producer_source_sha"]},
    }

    def api(method, endpoint, body=None):
        calls.append((method, endpoint, body))
        return comparison if method == "GET" else {}

    monkeypatch.setattr(at, "_api", api)
    assert at.dispatch_pending(config, ref="main") == 1
    assert [x[0] for x in calls] == ["GET", "POST"]
    assert task["status"] == "VERIFYING"
    assert task["dispatch_id"] == at.dispatch_id_for(task)
    assert task["verification_evidence"] is None


def test_diverged_or_unavailable_ancestor_never_dispatches(monkeypatch):
    config, spec, task = authorized_config()
    monkeypatch.setenv("GITHUB_REPOSITORY", recovery.REPO)
    monkeypatch.setenv("GITHUB_REF", "refs/heads/main")
    monkeypatch.setenv("GITHUB_SHA", "b" * 40)
    monkeypatch.setattr(am, "emit", lambda *a, **k: None)
    assert recovery.recover_incident(
        config, spec=spec, api_get=fake_api(spec), current_sha="b" * 40
    )
    calls = []

    def api(method, endpoint, body=None):
        calls.append(method)
        return {"status": "diverged", "ahead_by": 1, "behind_by": 1,
                "base_commit": {"sha": spec["producer_source_sha"]},
                "merge_base_commit": {"sha": "0" * 40}}

    monkeypatch.setattr(at, "_api", api)
    with pytest.raises(ValueError, match="not exact main ancestry"):
        at.dispatch_pending(config, ref="main")
    assert calls == ["GET"]
    assert task["verification_evidence"] is None
    assert task.get("dispatch_id") is None
