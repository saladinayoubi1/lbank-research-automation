from __future__ import annotations

import base64
import json

import pytest

import agent_transport as at
import deepseek_egress as egress
from scripts import agent_task_executor as executor


def task(worker="developer-agent", lease="lease-producer", attempt=1):
    return {
        "id": "T-G11",
        "title": "bounded Gate 11 review",
        "phase": 4,
        "gate": 11,
        "status": "LEASED",
        "priority": 10,
        "dependencies": [],
        "required_capabilities": [],
        "preferred_resources": [],
        "authority": 1,
        "acceptance": ["bounded"],
        "assigned_worker": worker,
        "producer": worker,
        "lease_id": lease,
        "attempt": attempt,
    }


def config(t):
    return {
        "schema_version": 1,
        "phase": 4,
        "policy": {"max_parallel_tasks": 4},
        "workers": [
            {"id": "developer-agent", "capabilities": [], "resources": ["github-cloud"], "authority_max": 3, "enabled": True, "verifier": False},
            {"id": "qa-verifier-agent", "capabilities": [], "resources": ["github-cloud"], "authority_max": 3, "enabled": True, "verifier": True},
        ],
        "tasks": [t],
    }


def mark_dispatched(t):
    env = at.envelope_for(t)
    t["status"] = "RUNNING"
    t["correlation_id"] = env["correlation_id"]
    t["dispatch_id"] = env["dispatch_id"]
    t["dispatch_transport"] = env["transport"]
    return env


def result_for(t, env, evidence=None):
    return {
        "schema_version": 2,
        "task_id": env["task_id"],
        "lease_id": env["lease_id"],
        "correlation_id": env["correlation_id"],
        "dispatch_id": env["dispatch_id"],
        "worker_id": env["worker_id"],
        "transport": env["transport"],
        "outcome": "success",
        "evidence": evidence or {"tests": "pass"},
    }


def test_independent_verifier_receives_real_new_dispatch_with_same_correlation(monkeypatch):
    t = task()
    producer_env = mark_dispatched(t)
    cfg = config(t)
    at.ingest_result(cfg, t, result_for(t, producer_env))

    assert t["status"] == "VERIFYING"
    assert t["assigned_worker"] == "qa-verifier-agent"
    assert t["lease_id"] != producer_env["lease_id"]
    assert at.correlation_for(t) == producer_env["correlation_id"]

    calls = []
    monkeypatch.setenv("GITHUB_REPOSITORY", "o/r")
    monkeypatch.setattr(at, "_api", lambda method, url, payload=None: calls.append((method, url, payload)))
    assert at.dispatch_pending(cfg, ref="main") == 1
    assert calls and calls[0][0] == "POST"
    assert t["status"] == "VERIFYING"
    assert t["dispatch_id"] == at.dispatch_id_for(t)
    assert t["dispatch_id"] != producer_env["dispatch_id"]
    assert t["correlation_id"] == producer_env["correlation_id"]

    verifier_env = at.envelope_for(t)
    at.ingest_result(cfg, t, result_for(t, verifier_env, {"independent_verification": "pass"}))
    assert t["status"] == "DONE"


def test_executor_requires_exact_v2_dispatch_identity_and_echoes_it():
    env = at.envelope_for(task())
    encoded = base64.urlsafe_b64encode(json.dumps(env, sort_keys=True).encode("utf-8")).decode("ascii")
    decoded = executor.decode_payload(encoded)
    assert decoded == env
    result = executor.execute(decoded, decoded["transport"])
    assert result["schema_version"] == 2
    for field in ("task_id", "lease_id", "correlation_id", "dispatch_id", "worker_id", "transport"):
        assert result[field] == decoded[field]

    malformed = dict(env)
    malformed["unexpected"] = True
    encoded_bad = base64.urlsafe_b64encode(json.dumps(malformed).encode("utf-8")).decode("ascii")
    with pytest.raises(ValueError, match="schema mismatch"):
        executor.decode_payload(encoded_bad)


def test_bounded_agent_review_is_allowlisted_but_sensitive_content_still_fails_closed():
    content = (
        executor.AGENT_REVIEW_PREFIX
        + "\n"
        + json.dumps({"task_id": "T-G11", "note": "review /home/alice/work for analyst@example.com"})
    )
    classification, messages = egress.prepare_egress_messages([{"role": "user", "content": content}])
    assert classification == "agent_review_advisory"
    assert "analyst@example.com" not in messages[0]["content"]
    assert "/home/alice" not in messages[0]["content"]
    assert "[REDACTED_EMAIL]" in messages[0]["content"]
    assert "[REDACTED_USER_PATH]" in messages[0]["content"]

    sensitive = executor.AGENT_REVIEW_PREFIX + "\napi_key=abcdefghijklmnop"
    with pytest.raises(egress.EgressDenied):
        egress.prepare_egress_messages([{"role": "user", "content": sensitive}])


def test_deepseek_budget_gate_fails_without_provider_call(monkeypatch):
    payload = at.envelope_for(task(worker="deepseek-bounded"))
    monkeypatch.delenv("NEXUS_DEEPSEEK_PAID_ROUTING_ALLOWED", raising=False)
    outcome, evidence = executor.deepseek_execution(payload)
    assert outcome == "failure"
    assert evidence["failure_class"] == "provider_budget_gate_closed"
    assert evidence["provider"] == "deepseek"
    assert evidence["correlation_id"] == payload["correlation_id"]


def test_new_lease_supersedes_old_dispatch_identity_without_losing_task_correlation():
    original = task(lease="lease-1", attempt=1)
    old_env = at.envelope_for(original)
    original["correlation_id"] = old_env["correlation_id"]
    original["dispatch_id"] = old_env["dispatch_id"]
    original["lease_id"] = "lease-2"
    original["attempt"] = 2
    new_env = at.envelope_for(original)
    assert new_env["correlation_id"] == old_env["correlation_id"]
    assert new_env["dispatch_id"] != old_env["dispatch_id"]
