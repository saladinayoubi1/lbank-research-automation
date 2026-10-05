from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest

import agent_manager as am
import agent_transport as at
from nexus_research_missions import EIGHTH
from nexus_strategy_independent_qa import digest


def task(worker="developer-agent", authority=1, lease_id="lease-1", attempt=1):
    return {
        "id": "T1",
        "title": "bounded task",
        "phase": 4,
        "gate": 11,
        "status": "LEASED",
        "priority": 10,
        "dependencies": [],
        "required_capabilities": [],
        "preferred_resources": [],
        "authority": authority,
        "acceptance": ["verified"],
        "assigned_worker": worker,
        "producer": worker,
        "lease_id": lease_id,
        "attempt": attempt,
    }


def strategy_qa_task():
    core = {
        "schema_version":"nexus.strategy-review-qa-task.v1",
        "id":"STRATEGY-QA-"+"a"*64,
        "task_kind":"strategy_review_independent_qa","system_map_node":"QA-41",
        "status":"READY_FOR_QA_DISPATCH","source_sha":"b"*40,
        "proposal_digest":"a"*64,"proposal_result_digest":"c"*64,
        "requalification_digest":"d"*64,"requalification_verification_digest":"e"*64,
        "family":"momentum","timeframe":"hour4","variant_id":"v1",
        "strategy_config":{"lookback":16},"strategy_config_digest":"",
        "runtime_evidence":[
            {
                "symbol":"BTCUSDT","dataset_binding_sha256":"f"*64,
                "pipeline_digest":"1"*64,"qualification_digest":"2"*64,
                "last_open_time_ms":1800000000000,
            },
            {
                "symbol":"ETHUSDT","dataset_binding_sha256":"3"*64,
                "pipeline_digest":"4"*64,"qualification_digest":"5"*64,
                "last_open_time_ms":1800000000000,
            },
        ],
        "producer_role":"strategy-runtime-requalification","required_verifier":"qa-verifier-agent",
        "research_only":True,"paper_only":True,"candidate_creation_authority":False,
        "qualification_authority":False,"promotion_authority":False,
        "paper_execution_authority":False,"automatic_strategy_promotion":False,
        "live_trading_authority":False,
    }
    core["strategy_config_digest"] = digest(core["strategy_config"])
    handoff = {**core, "task_digest": digest(core)}
    return {
        "id":handoff["id"],"title":"independent Strategy QA","phase":7,"gate":17,
        "status":"VERIFYING","priority":92,"dependencies":[],
        "required_capabilities":["data_validation"],"required_resources":["github-cloud"],
        "preferred_resources":["github-cloud"],"authority":2,"acceptance":["exact replay"],
        "assigned_worker":"qa-verifier-agent","verifier":"qa-verifier-agent",
        "required_verifier":"qa-verifier-agent","qa_verifier_only":True,
        "qa_dispatch_enabled":True,"qa_handoff_task":handoff,
        "lease_id":"qa-strategy-lease","attempt":1,
    }


def config(t):
    return {
        "schema_version": 1,
        "phase": 4,
        "policy": {"max_parallel_tasks": 4},
        "workers": [
            {"id": "developer-agent", "capabilities": [], "resources": ["github-cloud"], "authority_max": 3, "enabled": True, "verifier": False},
            {"id": "qa-verifier-agent", "capabilities": [], "resources": ["github-cloud"], "authority_max": 3, "enabled": True, "verifier": True},
            {"id": "deepseek-bounded", "capabilities": [], "resources": ["deepseek"], "authority_max": 2, "enabled": True, "verifier": False},
            {"id": "windows-runner", "capabilities": [], "resources": ["windows-local"], "authority_max": 3, "enabled": True, "verifier": True},
        ],
        "tasks": [t],
    }


def result_for(t, *, worker=None, lease=None, correlation=None, dispatch=None, transport=None, outcome="success", evidence=None):
    return {
        "schema_version": 2,
        "task_id": t["id"],
        "lease_id": lease or t["lease_id"],
        "correlation_id": correlation or t.get("correlation_id") or at.correlation_for(t),
        "dispatch_id": dispatch or t.get("dispatch_id") or at.dispatch_id_for(t),
        "worker_id": worker or t["assigned_worker"],
        "transport": transport or t.get("dispatch_transport") or at.transport_for(t["assigned_worker"]),
        "outcome": outcome,
        "evidence": {} if evidence is None else evidence,
    }


def mark_running(t):
    env = at.envelope_for(t)
    t["status"] = "RUNNING"
    t["correlation_id"] = env["correlation_id"]
    t["dispatch_id"] = env["dispatch_id"]
    t["dispatch_transport"] = env["transport"]
    return env


def test_transport_routing_is_explicit():
    assert at.transport_for("developer-agent") == "github-cloud"
    assert at.transport_for("deepseek-bounded") == "deepseek"
    assert at.transport_for("windows-runner") == "windows"


def test_l4_payload_never_dispatches():
    with pytest.raises(ValueError):
        at.envelope_for(task(authority=4))


def test_envelope_binds_stable_task_correlation_and_lease_scoped_dispatch():
    first = task()
    second = task(lease_id="lease-2", attempt=2)
    first_env = at.envelope_for(first)
    second_env = at.envelope_for(second)
    assert first_env["schema_version"] == 2
    assert first_env["correlation_id"] == second_env["correlation_id"]
    assert first_env["dispatch_id"] != second_env["dispatch_id"]
    assert len(first_env["correlation_id"]) == 32
    assert len(first_env["dispatch_id"]) == 32

def test_strategy_qa_transport_embeds_exact_verifier_only_handoff():
    t = strategy_qa_task()
    env = at.envelope_for(t)
    assert env["worker_id"] == "qa-verifier-agent"
    assert env["phase"] == 7
    assert env["transport"] == "github-cloud"
    assert env["strategy_qa_task"] == t["qa_handoff_task"]
    assert env["strategy_qa_task"]["source_sha"] == "b" * 40


def test_strategy_qa_transport_rejects_tampered_or_disabled_handoff():
    t = strategy_qa_task()
    t["qa_handoff_task"]["strategy_config"]["lookback"] = 99
    with pytest.raises(Exception):
        at.envelope_for(t)

    disabled = strategy_qa_task()
    disabled["qa_dispatch_enabled"] = False
    with pytest.raises(ValueError, match="verifier-only and enabled"):
        at.envelope_for(disabled)



def test_dispatch_marks_running_only_after_api_accepts(monkeypatch):
    t = task()
    monkeypatch.setenv("GITHUB_REPOSITORY", "o/r")
    calls = []
    monkeypatch.setattr(at, "_api", lambda method, url, payload=None: calls.append((method, url, payload)))
    at.dispatch_task(t, ref="main")
    assert calls and calls[0][0] == "POST"
    assert t["status"] == "RUNNING"
    assert t["dispatch_transport"] == "github-cloud"
    assert t["correlation_id"] == at.correlation_for(t)
    assert t["dispatch_id"] == at.dispatch_id_for(t)


def test_api_failure_does_not_fake_running(monkeypatch):
    t = task()
    monkeypatch.setenv("GITHUB_REPOSITORY", "o/r")

    def fail(*args, **kwargs):
        raise RuntimeError("dispatch failed")

    monkeypatch.setattr(at, "_api", fail)
    with pytest.raises(RuntimeError):
        at.dispatch_task(t, ref="main")
    assert t["status"] == "LEASED"
    assert "dispatch_id" not in t
    assert "correlation_id" not in t


def test_stale_result_cannot_complete_new_lease():
    t = task()
    mark_running(t)
    cfg = config(t)
    with pytest.raises(ValueError):
        at.ingest_result(cfg, t, result_for(t, lease="old-lease"))
    assert t["status"] == "RUNNING"


def test_worker_spoof_result_is_rejected():
    t = task()
    mark_running(t)
    cfg = config(t)
    with pytest.raises(ValueError):
        at.ingest_result(cfg, t, result_for(t, worker="qa-verifier-agent"))


def test_correlation_spoof_result_is_rejected():
    t = task()
    mark_running(t)
    cfg = config(t)
    with pytest.raises(ValueError, match="correlation"):
        at.ingest_result(cfg, t, result_for(t, correlation="f" * 32))


def test_dispatch_identity_spoof_result_is_rejected():
    t = task()
    mark_running(t)
    cfg = config(t)
    with pytest.raises(ValueError, match="dispatch identity"):
        at.ingest_result(cfg, t, result_for(t, dispatch="e" * 32))


def test_transport_spoof_result_is_rejected():
    t = task()
    mark_running(t)
    cfg = config(t)
    with pytest.raises(ValueError, match="transport"):
        at.ingest_result(cfg, t, result_for(t, transport="windows"))


def test_unknown_result_fields_fail_closed():
    t = task()
    mark_running(t)
    cfg = config(t)
    result = result_for(t)
    result["extra"] = "not-allowed"
    with pytest.raises(ValueError, match="schema mismatch"):
        at.ingest_result(cfg, t, result)


def test_valid_result_enters_independent_verification_and_preserves_correlation():
    t = task()
    mark_running(t)
    correlation = t["correlation_id"]
    cfg = config(t)
    at.ingest_result(cfg, t, result_for(t, evidence={"tests": "pass"}))
    assert t["status"] == "VERIFYING"
    assert t["assigned_worker"] == "qa-verifier-agent"
    assert t["verifier"] != t["producer"]
    assert t["correlation_id"] == correlation
    assert at.correlation_for(t) == correlation


def test_result_poll_can_finish_before_stale_lease_triage(monkeypatch):
    t = task()
    mark_running(t)
    cfg = config(t)
    result = result_for(t, evidence={"tests": "pass"})
    monkeypatch.setattr(at, "find_result", lambda lease_id: deepcopy(result))
    assert at.poll_results(cfg) == 1
    assert t["status"] == "VERIFYING"


def test_runtime_worker_preflight_allows_only_bounded_internal_bot_dispatch():
    workflow = Path(".github/workflows/nexus-runtime-worker.yml").read_text(encoding="utf-8")
    preflight = workflow.split("  preflight:\n", 1)[1].split("    runs-on:", 1)[0]
    assert "github.actor == github.repository_owner" in preflight
    assert "github.actor == 'github-actions[bot]'" in preflight
    assert "github.event.inputs.payload_b64 != ''" in preflight
    assert "github.event.inputs.lease_id != ''" in preflight
    assert "github.event.inputs.transport != ''" in preflight

    laptop = workflow.split("  laptop-worker:\n", 1)[1].split("    needs:", 1)[0]
    assert "github.actor == github.repository_owner" in laptop
    assert "github-actions[bot]" not in laptop


def _source_epoch_qa_task():
    from nexus_research_missions import FIFTH
    t = task(worker="qa-verifier-agent", lease_id="qa-epoch-one")
    t["id"] = FIFTH
    t["phase"] = 7
    t["status"] = "VERIFYING"
    t["producer"] = "research-agent"
    t["verifier"] = "qa-verifier-agent"
    t["research_producer_lease_id"] = "immutable-producer"
    t.update({
        "research_predecessor_source_sha": "d" * 40,
        "research_predecessor_receipt_digest": "e" * 64,
        "research_predecessor_qa_digest": "f" * 64,
        "research_predecessor_ledger_digest": "1" * 64,
        "research_predecessor_mechanism": "failed_range_break_reversal",
    })
    t["result_evidence"] = {
        "source_sha": "a" * 40,
        "receipt_digest": "b" * 64,
        "independent_qa_complete": False,
        "auto_demo_promotion": False,
        "live_enabled": False,
    }
    return t


def test_research_qa_never_dispatches_at_different_source_epoch(monkeypatch):
    t = _source_epoch_qa_task()
    cfg = config(t)
    monkeypatch.setenv("GITHUB_SHA", "c" * 40)
    calls = []
    monkeypatch.setattr(at, "_api", lambda *args: calls.append(args))
    at.dispatch_pending(cfg, ref="main")
    assert not calls
    assert t["status"] == "BLOCKED"
    assert t["blocked_reason"] == "research_qa_source_epoch_drift_requires_fresh_producer"
    assert t["research_qa_epoch_drift"]["producer_source_sha"] == "a" * 40
    assert t["research_qa_epoch_drift"]["producer_receipt_digest"] == "b" * 64
    assert t["result_evidence"]["receipt_digest"] == "b" * 64
    assert t["research_qa_epoch_drift"]["old_producer_not_qualified"] is True
    assert t.get("dispatch_id") is None


def test_research_qa_same_source_epoch_can_dispatch(monkeypatch):
    t = _source_epoch_qa_task()
    cfg = config(t)
    calls = []
    monkeypatch.setenv("GITHUB_SHA", "a" * 40)
    monkeypatch.setenv("GITHUB_REPOSITORY", "example/repo")
    monkeypatch.setattr(at, "_api", lambda *args: calls.append(args))
    assert at.dispatch_pending(cfg, ref="main") == 1
    assert len(calls) == 1
    assert t["status"] == "VERIFYING"
    assert t.get("blocked_reason") is None


def test_research_qa_unknown_source_fails_closed_without_dispatch(monkeypatch):
    t = _source_epoch_qa_task()
    cfg = config(t)
    monkeypatch.delenv("GITHUB_SHA", raising=False)
    monkeypatch.setattr(at, "_api", lambda *args: (_ for _ in ()).throw(
        AssertionError("QA must not dispatch with missing source identity")
    ))
    with pytest.raises(ValueError, match="source identity"):
        at.dispatch_pending(cfg, ref="main")
    assert t["status"] == "VERIFYING"
    assert not t.get("dispatch_id")


def test_research_qa_inflight_existing_dispatch_is_not_mutated_by_epoch_gate(monkeypatch):
    t = _source_epoch_qa_task()
    t["dispatch_id"] = at.dispatch_id_for(t)
    cfg = config(t)
    monkeypatch.setenv("GITHUB_SHA", "c" * 40)
    monkeypatch.setattr(at, "_api", lambda *args: (_ for _ in ()).throw(
        AssertionError("existing QA dispatch must not be resent")
    ))
    assert at.dispatch_pending(cfg, ref="main") == 0
    assert t["status"] == "VERIFYING"
    assert t.get("research_qa_epoch_drift") is None


def test_research_rca_transport_mismatch_preserves_original_cache_failure():
    t = task(worker="architect-agent", authority=2, lease_id="rca-lease", attempt=1)
    original = {
        "executor": "nexus-real-composite-backtest",
        "failure_class": "verified_research_execution_failed",
        "reason": at.RESEARCH_CACHE_MISS_REASON,
        "auto_demo_promotion": False,
        "live_enabled": False,
        "qualification_authority": False,
    }
    t.update({
        "id": EIGHTH,
        "phase": 7,
        "gate": 17,
        "status": "RUNNING",
        "producer": "research-agent",
        "triage_mode": "root_cause_first",
        "failure_class": "verified_research_execution_failed",
        "failure_evidence": deepcopy(original),
        "external_wait_state": "WAITING_EXTERNAL",
    })
    t["correlation_id"] = at.correlation_for(t)
    t["dispatch_id"] = at.dispatch_id_for(t)
    t["dispatch_transport"] = "github-cloud"
    cfg = config(t)

    result = result_for(
        t,
        outcome="failure",
        evidence={
            "executor": "nexus-real-composite-backtest",
            "failure_class": at.RESEARCH_RCA_TRANSPORT_MISMATCH,
            "auto_demo_promotion": False,
            "live_enabled": False,
            "qualification_authority": False,
        },
    )
    at.ingest_result(cfg, t, result)

    assert t["status"] == "TRIAGE"
    assert t["failure_class"] == "verified_research_execution_failed"
    assert t["failure_evidence"] == original
    assert t["triage_evidence"]["preserved_original_failure"] is True
    assert t["triage_evidence"]["evidence"]["failure_class"] == at.RESEARCH_RCA_TRANSPORT_MISMATCH
    assert t["result_artifact_ingested"] is True
    assert t["external_wait_state"] == "COMPLETED"
