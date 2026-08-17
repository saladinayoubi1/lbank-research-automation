from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from failure_concurrency import (
    BoundedRetryPolicy,
    ConcurrencyControlError,
    ExecutionFence,
    FailureClass,
    IdempotencyConflict,
    IdempotencyRegistry,
    OwnershipConflict,
    ResourceDenied,
    ResourceSlice,
    RevisionConflict,
    RevisionedStore,
    classify_failure,
)


def test_failure_taxonomy_matches_frozen_gate16_classes():
    assert {item.value for item in FailureClass} == {
        "transient",
        "persistent",
        "corrupt_state",
        "stale_state",
        "provider_unavailable",
        "network_unavailable",
        "local_node_offline",
        "invalid_data",
        "policy_denied",
        "budget_resource_denied",
        "human_required",
    }


def test_duplicate_task_is_owned_then_replayed_without_second_completion():
    registry = IdempotencyRegistry()
    task = {"task_id": "task-1", "payload": "same"}

    assert registry.begin(key="task:1", payload=task, owner_id="worker-a").status == "acquired"
    assert registry.begin(key="task:1", payload=task, owner_id="worker-a").status == "owned"
    result_digest = registry.complete(key="task:1", owner_id="worker-a", result={"ok": True})
    replay = registry.begin(key="task:1", payload=task, owner_id="worker-b")

    assert replay.status == "replay"
    assert replay.result_digest == result_digest


def test_same_idempotency_key_with_different_signal_or_event_fails_closed():
    registry = IdempotencyRegistry()
    registry.begin(key="signal:1", payload={"side": "long"}, owner_id="worker-a")

    with pytest.raises(IdempotencyConflict, match="different payload"):
        registry.begin(key="signal:1", payload={"side": "short"}, owner_id="worker-a")


def test_double_fill_or_double_execution_cannot_gain_second_owner():
    fence = ExecutionFence()
    command = {"signal_id": "sig-1", "operation": "open", "paper_only": True}
    first = fence.reserve(execution_key="fill:sig-1", command=command, owner_id="paper-a")
    assert first.status == "acquired"

    with pytest.raises(OwnershipConflict, match="already owned"):
        fence.reserve(execution_key="fill:sig-1", command=command, owner_id="paper-b")

    fence.complete(execution_key="fill:sig-1", owner_id="paper-a", result={"fill_id": "fill-1"})
    replay = fence.reserve(execution_key="fill:sig-1", command=command, owner_id="paper-b")
    assert replay.status == "replay"


def test_concurrent_event_write_compare_and_swap_has_one_winner_and_no_lost_update():
    store = RevisionedStore(namespace="event_store", initial={"sequence": 10})
    start = threading.Barrier(2)

    def writer(name: str):
        start.wait()
        try:
            snapshot = store.commit(
                expected_revision=0,
                idempotency_key=f"commit:{name}",
                payload={"sequence": 11, "writer": name},
            )
            return ("success", snapshot.payload["writer"])
        except RevisionConflict:
            return ("conflict", name)

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(writer, ("a", "b")))

    assert sorted(status for status, _ in results) == ["conflict", "success"]
    snapshot = store.snapshot()
    assert snapshot.revision == 1
    assert snapshot.payload["writer"] in {"a", "b"}
    assert snapshot.payload["sequence"] == 11


def test_concurrent_config_write_uses_same_revision_and_idempotency_rules():
    store = RevisionedStore(namespace="config", initial={"policy": "v1"})
    first = store.commit(expected_revision=0, idempotency_key="cfg-1", payload={"policy": "v2"})
    replay = store.commit(expected_revision=0, idempotency_key="cfg-1", payload={"policy": "v2"})

    assert first == replay
    with pytest.raises(IdempotencyConflict):
        store.commit(expected_revision=1, idempotency_key="cfg-1", payload={"policy": "v3"})


def test_failed_candidate_commit_preserves_previous_valid_state():
    store = RevisionedStore(namespace="ledger", initial={"cash": "100"})
    before = store.snapshot()

    with pytest.raises(ConcurrencyControlError, match="canonically serializable"):
        store.commit(expected_revision=0, idempotency_key="bad", payload={"cash": {"not-json"}})

    assert store.snapshot() == before


def test_last_resource_slice_race_allows_exactly_one_consumer():
    resource = ResourceSlice(1)
    start = threading.Barrier(2)

    def consume():
        start.wait()
        try:
            return ("allowed", resource.consume())
        except ResourceDenied as exc:
            return ("denied", str(exc))

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: consume(), range(2)))

    assert sorted(status for status, _ in results) == ["allowed", "denied"]
    assert resource.remaining == 0
    assert any(value == "budget_resource_denied" for status, value in results if status == "denied")


def test_retry_is_bounded_and_non_retryable_failures_never_loop():
    policy = BoundedRetryPolicy(max_attempts=3)

    assert policy.decide(current_attempt=1, failure_class=FailureClass.NETWORK_UNAVAILABLE).next_attempt == 2
    assert policy.decide(current_attempt=2, failure_class=FailureClass.TRANSIENT).next_attempt == 3
    exhausted = policy.decide(current_attempt=3, failure_class=FailureClass.TRANSIENT)
    assert exhausted.allowed is False
    assert exhausted.reason_code == "retry_budget_exhausted"

    denied = policy.decide(current_attempt=1, failure_class=FailureClass.POLICY_DENIED)
    assert denied.allowed is False
    assert denied.next_attempt is None
    assert denied.reason_code == "non_retryable:policy_denied"


def test_retry_release_requires_current_owner_and_retryable_class():
    policy = BoundedRetryPolicy(max_attempts=2)
    registry = IdempotencyRegistry()
    registry.begin(key="task:retry", payload={"work": 1}, owner_id="worker-a")

    with pytest.raises(OwnershipConflict):
        registry.abandon_for_retry(
            key="task:retry",
            owner_id="worker-b",
            failure_class=FailureClass.NETWORK_UNAVAILABLE,
            policy=policy,
            current_attempt=1,
        )

    decision = registry.abandon_for_retry(
        key="task:retry",
        owner_id="worker-a",
        failure_class=FailureClass.NETWORK_UNAVAILABLE,
        policy=policy,
        current_attempt=1,
    )
    assert decision.allowed is True
    assert registry.begin(key="task:retry", payload={"work": 1}, owner_id="worker-b").status == "acquired"


def test_failure_aliases_are_deterministic_and_unknown_defaults_persistent():
    assert classify_failure("timeout") is FailureClass.TRANSIENT
    assert classify_failure("runner_offline") is FailureClass.LOCAL_NODE_OFFLINE
    assert classify_failure("malformed_data") is FailureClass.INVALID_DATA
    assert classify_failure("owner_required") is FailureClass.HUMAN_REQUIRED
    assert classify_failure("something_new") is FailureClass.PERSISTENT
