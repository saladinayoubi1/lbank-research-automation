from __future__ import annotations

from copy import deepcopy

import pytest

import phase5_attempts as attempts
import phase5_mission_contract as mc


SOURCE_SHA = "a" * 64
SPEC_SHA = "b" * 64


def task():
    return {
        "mission_id": "m1",
        "id": "T1",
        "spec_digest": SPEC_SHA,
        "authority": 1,
        "status": "RUNNING",
    }


def test_new_lease_monotonically_fences_old_attempt():
    t = task()
    first = attempts.begin_attempt(
        t, worker_id="worker-a", lease_id="lease-a", source_sha=SOURCE_SHA, state_generation=3
    )
    second = attempts.begin_attempt(
        t, worker_id="worker-b", lease_id="lease-b", source_sha=SOURCE_SHA, state_generation=4
    )

    assert first["fence_generation"] == 1
    assert second["fence_generation"] == 2
    assert second["attempt_number"] == 2
    assert t["attempt_history"][0]["status"] == "SUPERSEDED"
    assert t["active_attempt_id"] == second["attempt_id"]

    stale = attempts.build_result(first, outcome="success", evidence={"old": True})
    with pytest.raises(attempts.StaleAttempt, match="stale"):
        attempts.accept_result(t, stale)


def test_same_lease_issue_is_idempotent_and_does_not_increment_fence():
    t = task()
    first = attempts.begin_attempt(
        t, worker_id="worker-a", lease_id="lease-a", source_sha=SOURCE_SHA, state_generation=3
    )
    again = attempts.begin_attempt(
        t, worker_id="worker-a", lease_id="lease-a", source_sha=SOURCE_SHA, state_generation=99
    )
    assert again == first
    assert t["fence_generation"] == 1
    assert len(t["attempt_history"]) == 1


def test_exact_duplicate_result_is_idempotent_but_conflicting_replay_fails():
    t = task()
    attempt = attempts.begin_attempt(
        t, worker_id="worker-a", lease_id="lease-a", source_sha=SOURCE_SHA, state_generation=0
    )
    result = attempts.build_result(attempt, outcome="success", evidence={"proof": "same"})
    assert attempts.accept_result(t, result) is True
    assert attempts.accept_result(t, deepcopy(result)) is False

    conflicting = attempts.build_result(attempt, outcome="success", evidence={"proof": "different"})
    with pytest.raises(attempts.AttemptConflict, match="different ingested result"):
        attempts.accept_result(t, conflicting)


def test_worker_lease_source_spec_and_attempt_identity_are_bound():
    t = task()
    attempt = attempts.begin_attempt(
        t, worker_id="worker-a", lease_id="lease-a", source_sha=SOURCE_SHA, state_generation=2
    )
    base = attempts.build_result(attempt, outcome="success", evidence={"ok": True})

    for field, replacement in (
        ("worker_id", "worker-b"),
        ("lease_id", "lease-b"),
        ("source_sha", "c" * 64),
        ("spec_digest", "d" * 64),
        ("attempt_number", 99),
    ):
        candidate = deepcopy(base)
        candidate[field] = replacement
        with pytest.raises(attempts.StaleAttempt):
            attempts.accept_result(t, candidate)


def test_l4_and_malformed_digests_fail_closed():
    t = task()
    t["authority"] = 4
    with pytest.raises(attempts.AttemptError, match="L4"):
        attempts.begin_attempt(t, worker_id="w", lease_id="l", source_sha=SOURCE_SHA, state_generation=0)

    t = task()
    t["spec_digest"] = "short"
    with pytest.raises(attempts.AttemptError, match="spec_digest"):
        attempts.begin_attempt(t, worker_id="w", lease_id="l", source_sha=SOURCE_SHA, state_generation=0)


def test_nonfinite_and_oversized_result_evidence_fails_closed():
    t = task()
    attempt = attempts.begin_attempt(
        t, worker_id="worker-a", lease_id="lease-a", source_sha=SOURCE_SHA, state_generation=0
    )
    with pytest.raises(attempts.AttemptError, match="canonical JSON"):
        attempts.build_result(attempt, outcome="success", evidence={"bad": float("nan")})
    with pytest.raises(attempts.AttemptError, match="bounded size"):
        attempts.build_result(attempt, outcome="success", evidence={"blob": "x" * attempts.MAX_RESULT_BYTES})


def test_attempt_history_is_bounded_without_overwriting_prior_attempts(monkeypatch):
    monkeypatch.setattr(attempts, "MAX_TASK_ATTEMPTS", 2)
    t = task()
    first = attempts.begin_attempt(t, worker_id="a", lease_id="l1", source_sha=SOURCE_SHA, state_generation=0)
    second = attempts.begin_attempt(t, worker_id="b", lease_id="l2", source_sha=SOURCE_SHA, state_generation=1)
    before = deepcopy(t["attempt_history"])

    with pytest.raises(attempts.AttemptError, match="bounded attempt limit"):
        attempts.begin_attempt(t, worker_id="c", lease_id="l3", source_sha=SOURCE_SHA, state_generation=2)

    assert t["attempt_history"] == before
    assert [item["attempt_id"] for item in before] == [first["attempt_id"], second["attempt_id"]]


def test_gate1_runtime_merge_preserves_attempt_fencing_state():
    template = {
        "schema_version": 1,
        "phase": 5,
        "phase5_runtime_schema": mc.RUNTIME_SCHEMA,
        "mission_id": "m1",
        "mission_revision": 1,
        "policy_version": "p1",
        "policy": {},
        "workers": [],
        "tasks": [task()],
    }
    runtime = deepcopy(template)
    issued = attempts.begin_attempt(
        runtime["tasks"][0], worker_id="worker-a", lease_id="lease-a", source_sha=SOURCE_SHA, state_generation=7
    )
    runtime["tasks"][0]["last_attempt_result"] = {"attempt_id": issued["attempt_id"]}

    merged = mc.merge_compatible_runtime(template, runtime)
    assert merged["tasks"][0]["fence_generation"] == 1
    assert merged["tasks"][0]["active_attempt_id"] == issued["attempt_id"]
    assert merged["tasks"][0]["attempt_history"][0]["attempt_id"] == issued["attempt_id"]
