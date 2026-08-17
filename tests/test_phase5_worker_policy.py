from __future__ import annotations

from copy import deepcopy

import pytest

import phase5_worker_policy as policy


def config():
    return {
        "workers": [
            {
                "id": "cloud",
                "trust_domain": "github-cloud",
                "capabilities": ["implementation", "diagnostics"],
                "resources": ["github-cloud"],
                "authority_max": 3,
                "enabled": True,
                "verifier": False,
                "max_concurrent_tasks": 2,
            },
            {
                "id": "windows",
                "trust_domain": "windows-local",
                "capabilities": ["implementation", "diagnostics", "windows_runtime"],
                "resources": ["windows-local"],
                "authority_max": 3,
                "enabled": True,
                "verifier": True,
                "max_concurrent_tasks": 1,
            },
            {
                "id": "deepseek",
                "trust_domain": "deepseek-external",
                "capabilities": ["diagnostics", "code_review"],
                "resources": ["deepseek"],
                "authority_max": 2,
                "enabled": True,
                "verifier": False,
                "max_concurrent_tasks": 1,
            },
        ]
    }


def task(caps=None, preferred=None, authority=1):
    return {
        "id": "T",
        "required_capabilities": caps or ["implementation"],
        "preferred_resources": preferred or ["github-cloud"],
        "authority": authority,
    }


def snapshot(*workers):
    return {"schema_version": policy.WORKER_RUNTIME_SCHEMA, "workers": list(workers)}


def state(worker_id, health="online", active=0, cost=0.0, paid=False):
    return {
        "worker_id": worker_id,
        "health": health,
        "active": active,
        "estimated_cost_usd": cost,
        "paid_budget_authorized": paid,
    }


def test_online_preferred_worker_wins_over_other_eligible_worker():
    result = policy.route_task(
        config(),
        task(),
        snapshot(state("cloud"), state("windows"), state("deepseek", paid=False)),
    )
    assert result["status"] == "routed"
    assert result["worker_id"] == "cloud"


def test_offline_windows_is_excluded_without_blocking_cloud_progress():
    result = policy.route_task(
        config(),
        task(preferred=["windows-local"]),
        snapshot(state("cloud"), state("windows", health="offline"), state("deepseek")),
    )
    assert result["worker_id"] == "cloud"
    assert result["rejections"]["windows"] == "worker_offline"


def test_degraded_worker_loses_to_online_even_if_resource_preferred():
    result = policy.route_task(
        config(),
        task(preferred=["windows-local"]),
        snapshot(state("cloud"), state("windows", health="degraded"), state("deepseek")),
    )
    assert result["worker_id"] == "cloud"


def test_capacity_exhaustion_fails_over_and_is_bounded():
    result = policy.route_task(
        config(),
        task(),
        snapshot(state("cloud", active=2), state("windows", active=0), state("deepseek")),
    )
    assert result["worker_id"] == "windows"
    assert result["rejections"]["cloud"] == "capacity_exhausted"


def test_missing_runtime_health_is_fail_closed_not_assumed_online():
    result = policy.route_task(config(), task(), snapshot(state("windows")))
    assert result["worker_id"] == "windows"
    assert result["rejections"]["cloud"] == "runtime_unknown"


def test_paid_provider_requires_explicit_budget_authorization_and_cost_bound():
    review_task = task(caps=["code_review"], preferred=["deepseek"])
    denied = policy.route_task(
        config(),
        review_task,
        snapshot(state("cloud"), state("windows"), state("deepseek", cost=0.01, paid=False)),
        max_cost_usd=0.05,
    )
    assert denied["status"] == "blocked"
    assert denied["rejections"]["deepseek"] == "paid_budget_not_authorized"

    too_expensive = policy.route_task(
        config(),
        review_task,
        snapshot(state("deepseek", cost=0.06, paid=True)),
        max_cost_usd=0.05,
    )
    assert too_expensive["status"] == "blocked"
    assert too_expensive["rejections"]["deepseek"] == "cost_budget_exceeded"

    allowed = policy.route_task(
        config(),
        review_task,
        snapshot(state("deepseek", cost=0.01, paid=True)),
        max_cost_usd=0.05,
    )
    assert allowed["status"] == "routed"
    assert allowed["worker_id"] == "deepseek"


def test_runtime_cannot_self_promote_capability_or_authority():
    bad = state("cloud")
    bad["authority_max"] = 4
    with pytest.raises(policy.WorkerPolicyError, match="forbidden"):
        policy.validate_runtime_snapshot(config(), snapshot(bad))

    bad = state("cloud")
    bad["capabilities"] = ["anything"]
    with pytest.raises(policy.WorkerPolicyError, match="forbidden"):
        policy.validate_runtime_snapshot(config(), snapshot(bad))


def test_unknown_worker_and_malformed_health_fail_closed():
    with pytest.raises(policy.WorkerPolicyError, match="unknown runtime worker"):
        policy.validate_runtime_snapshot(config(), snapshot(state("rogue")))
    with pytest.raises(policy.WorkerPolicyError, match="invalid health"):
        policy.validate_runtime_snapshot(config(), snapshot(state("cloud", health="magically-good")))


def test_l4_is_never_routed_even_when_workers_claim_capacity():
    result = policy.route_task(
        config(),
        task(authority=4),
        snapshot(state("cloud"), state("windows"), state("deepseek", paid=True)),
        max_cost_usd=10,
    )
    assert result == {
        "schema_version": policy.ROUTING_DECISION_SCHEMA,
        "task_id": "T",
        "status": "owner_required",
        "worker_id": None,
        "reason": "L4_owner_required",
    }


def test_static_registry_is_authority_source_not_runtime_snapshot():
    cfg = config()
    cfg["workers"][0]["authority_max"] = 0
    result = policy.route_task(cfg, task(authority=1), snapshot(state("cloud"), state("windows")))
    assert result["worker_id"] == "windows"
    assert result["rejections"]["cloud"] == "authority_insufficient"


def test_disabled_worker_is_not_revived_by_runtime_online_state():
    cfg = deepcopy(config())
    cfg["workers"][0]["enabled"] = False
    result = policy.route_task(cfg, task(), snapshot(state("cloud"), state("windows")))
    assert result["worker_id"] == "windows"
    assert result["rejections"]["cloud"] == "disabled"
