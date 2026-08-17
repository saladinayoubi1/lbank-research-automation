from __future__ import annotations

import hashlib
import json
import threading
from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping


class FailureClass(str, Enum):
    TRANSIENT = "transient"
    PERSISTENT = "persistent"
    CORRUPT_STATE = "corrupt_state"
    STALE_STATE = "stale_state"
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    NETWORK_UNAVAILABLE = "network_unavailable"
    LOCAL_NODE_OFFLINE = "local_node_offline"
    INVALID_DATA = "invalid_data"
    POLICY_DENIED = "policy_denied"
    BUDGET_RESOURCE_DENIED = "budget_resource_denied"
    HUMAN_REQUIRED = "human_required"


RETRYABLE_FAILURES = {
    FailureClass.TRANSIENT,
    FailureClass.PROVIDER_UNAVAILABLE,
    FailureClass.NETWORK_UNAVAILABLE,
    FailureClass.LOCAL_NODE_OFFLINE,
}


class ConcurrencyControlError(RuntimeError):
    pass


class IdempotencyConflict(ConcurrencyControlError):
    pass


class OwnershipConflict(ConcurrencyControlError):
    pass


class RevisionConflict(ConcurrencyControlError):
    pass


class ResourceDenied(ConcurrencyControlError):
    pass


class RetryDenied(ConcurrencyControlError):
    pass


def canonical_digest(value: Any) -> str:
    try:
        payload = json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ConcurrencyControlError("value is not canonically serializable") from exc
    return hashlib.sha256(payload).hexdigest()


def _bounded(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 256:
        raise ConcurrencyControlError(f"{field} must be a non-empty bounded string")
    return value


@dataclass(frozen=True)
class RetryDecision:
    allowed: bool
    next_attempt: int | None
    reason_code: str


@dataclass(frozen=True)
class ClaimResult:
    status: str
    owner_id: str
    result_digest: str | None


@dataclass(frozen=True)
class RevisionSnapshot:
    namespace: str
    revision: int
    payload: Mapping[str, Any]
    payload_digest: str


class BoundedRetryPolicy:
    def __init__(self, *, max_attempts: int) -> None:
        if isinstance(max_attempts, bool) or not isinstance(max_attempts, int) or max_attempts < 1:
            raise ConcurrencyControlError("max_attempts must be a positive integer")
        self.max_attempts = max_attempts

    def decide(self, *, current_attempt: int, failure_class: FailureClass) -> RetryDecision:
        if isinstance(current_attempt, bool) or not isinstance(current_attempt, int) or current_attempt < 1:
            raise ConcurrencyControlError("current_attempt must be a positive integer")
        if not isinstance(failure_class, FailureClass):
            raise ConcurrencyControlError("failure_class must be classified")
        if failure_class not in RETRYABLE_FAILURES:
            return RetryDecision(False, None, f"non_retryable:{failure_class.value}")
        if current_attempt >= self.max_attempts:
            return RetryDecision(False, None, "retry_budget_exhausted")
        return RetryDecision(True, current_attempt + 1, "bounded_retry_allowed")


class IdempotencyRegistry:
    """Thread-safe deterministic ownership and exactly-once completion fence."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._claims: dict[str, dict[str, str | None]] = {}

    def begin(self, *, key: str, payload: Any, owner_id: str) -> ClaimResult:
        key = _bounded(key, "idempotency key")
        owner_id = _bounded(owner_id, "owner_id")
        digest = canonical_digest(payload)
        with self._lock:
            existing = self._claims.get(key)
            if existing is None:
                self._claims[key] = {
                    "payload_digest": digest,
                    "owner_id": owner_id,
                    "status": "in_progress",
                    "result_digest": None,
                }
                return ClaimResult("acquired", owner_id, None)
            if existing["payload_digest"] != digest:
                raise IdempotencyConflict("idempotency key reused with different payload")
            if existing["status"] == "completed":
                return ClaimResult("replay", str(existing["owner_id"]), str(existing["result_digest"]))
            if existing["owner_id"] == owner_id:
                return ClaimResult("owned", owner_id, None)
            raise OwnershipConflict("idempotent operation already owned")

    def complete(self, *, key: str, owner_id: str, result: Any) -> str:
        key = _bounded(key, "idempotency key")
        owner_id = _bounded(owner_id, "owner_id")
        result_digest = canonical_digest(result)
        with self._lock:
            existing = self._claims.get(key)
            if existing is None:
                raise OwnershipConflict("cannot complete an unclaimed operation")
            if existing["owner_id"] != owner_id:
                raise OwnershipConflict("only deterministic owner may complete operation")
            if existing["status"] == "completed":
                if existing["result_digest"] != result_digest:
                    raise IdempotencyConflict("completed operation cannot change result")
                return result_digest
            existing["status"] = "completed"
            existing["result_digest"] = result_digest
            return result_digest

    def abandon_for_retry(self, *, key: str, owner_id: str, failure_class: FailureClass, policy: BoundedRetryPolicy, current_attempt: int) -> RetryDecision:
        decision = policy.decide(current_attempt=current_attempt, failure_class=failure_class)
        with self._lock:
            existing = self._claims.get(key)
            if existing is None or existing["owner_id"] != owner_id or existing["status"] != "in_progress":
                raise OwnershipConflict("only active owner may abandon operation")
            if decision.allowed:
                self._claims.pop(key)
            return decision


class RevisionedStore:
    """Compare-and-swap state store used to prove no lost concurrent event/config writes."""

    def __init__(self, *, namespace: str, initial: Mapping[str, Any] | None = None) -> None:
        self.namespace = _bounded(namespace, "namespace")
        self._lock = threading.RLock()
        self._revision = 0
        self._payload = dict(initial or {})
        self._digest = canonical_digest(self._payload)
        self._commits: dict[str, tuple[str, int]] = {}

    def snapshot(self) -> RevisionSnapshot:
        with self._lock:
            return RevisionSnapshot(self.namespace, self._revision, dict(self._payload), self._digest)

    def commit(self, *, expected_revision: int, idempotency_key: str, payload: Mapping[str, Any]) -> RevisionSnapshot:
        if isinstance(expected_revision, bool) or not isinstance(expected_revision, int) or expected_revision < 0:
            raise ConcurrencyControlError("expected_revision must be a non-negative integer")
        idempotency_key = _bounded(idempotency_key, "idempotency key")
        if not isinstance(payload, Mapping):
            raise ConcurrencyControlError("payload must be a mapping")
        candidate = dict(payload)
        candidate_digest = canonical_digest(candidate)
        with self._lock:
            prior = self._commits.get(idempotency_key)
            if prior is not None:
                prior_digest, prior_revision = prior
                if prior_digest != candidate_digest:
                    raise IdempotencyConflict("commit idempotency key reused with different payload")
                if prior_revision != self._revision:
                    raise RevisionConflict("idempotent commit is no longer the current revision")
                return self.snapshot()
            if expected_revision != self._revision:
                raise RevisionConflict("compare-and-swap revision mismatch")
            self._revision += 1
            self._payload = candidate
            self._digest = candidate_digest
            self._commits[idempotency_key] = (candidate_digest, self._revision)
            return self.snapshot()


class ExecutionFence:
    """Prevents duplicate signal/event/fill execution for one deterministic key."""

    def __init__(self) -> None:
        self._registry = IdempotencyRegistry()

    def reserve(self, *, execution_key: str, command: Any, owner_id: str) -> ClaimResult:
        return self._registry.begin(key=execution_key, payload=command, owner_id=owner_id)

    def complete(self, *, execution_key: str, owner_id: str, result: Any) -> str:
        return self._registry.complete(key=execution_key, owner_id=owner_id, result=result)


class ResourceSlice:
    """Atomic bounded resource counter; exhaustion denies instead of bypassing policy."""

    def __init__(self, units: int) -> None:
        if isinstance(units, bool) or not isinstance(units, int) or units < 0:
            raise ConcurrencyControlError("resource units must be a non-negative integer")
        self._lock = threading.RLock()
        self._remaining = units

    @property
    def remaining(self) -> int:
        with self._lock:
            return self._remaining

    def consume(self, units: int = 1) -> int:
        if isinstance(units, bool) or not isinstance(units, int) or units < 1:
            raise ConcurrencyControlError("consumed units must be a positive integer")
        with self._lock:
            if units > self._remaining:
                raise ResourceDenied(FailureClass.BUDGET_RESOURCE_DENIED.value)
            self._remaining -= units
            return self._remaining


def classify_failure(reason_code: str) -> FailureClass:
    reason_code = _bounded(reason_code, "reason_code")
    direct = {item.value: item for item in FailureClass}
    aliases = {
        "timeout": FailureClass.TRANSIENT,
        "network_error": FailureClass.NETWORK_UNAVAILABLE,
        "provider_error": FailureClass.PROVIDER_UNAVAILABLE,
        "runner_offline": FailureClass.LOCAL_NODE_OFFLINE,
        "malformed_data": FailureClass.INVALID_DATA,
        "stale_context": FailureClass.STALE_STATE,
        "corrupt_event": FailureClass.CORRUPT_STATE,
        "policy_block": FailureClass.POLICY_DENIED,
        "budget_exhausted": FailureClass.BUDGET_RESOURCE_DENIED,
        "owner_required": FailureClass.HUMAN_REQUIRED,
    }
    if reason_code in direct:
        return direct[reason_code]
    if reason_code in aliases:
        return aliases[reason_code]
    return FailureClass.PERSISTENT
