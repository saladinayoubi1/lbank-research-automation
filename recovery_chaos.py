from __future__ import annotations

import hashlib
import json
import threading
from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping, Sequence


class RecoveryScenario(str, Enum):
    PROCESS_CRASH = "process_crash"
    RUNNER_RESTART = "runner_restart"
    LOCAL_LAPTOP_OFFLINE = "local_laptop_offline"
    PROVIDER_OUTAGE = "provider_outage"
    PARTIAL_WRITE = "partial_write"
    CORRUPT_STALE_CONFLICTING_STATE = "corrupt_stale_conflicting_state"
    DUPLICATE_REORDERED_EVENTS = "duplicate_reordered_events"
    INTERRUPTED_PAPER_OPERATION = "interrupted_paper_operation"
    MALFORMED_AI_OUTPUT = "malformed_ai_output"
    UNAVAILABLE_STALE_MARKET_DATA = "unavailable_stale_market_data"
    PARTIAL_ARTIFACT_EVIDENCE_FAILURE = "partial_artifact_evidence_failure"


class RecoveryError(RuntimeError):
    pass


class CandidateRejected(RecoveryError):
    pass


class SimulatedCrash(RecoveryError):
    pass


@dataclass(frozen=True)
class RecoverySnapshot:
    revision: int
    state: Mapping[str, Any]
    state_digest: str


@dataclass(frozen=True)
class RecoveryDecision:
    scenario: RecoveryScenario
    action: str
    reason_code: str
    state_changed: bool
    degraded: bool
    resulting_revision: int
    resulting_digest: str


def _canonical(value: Any) -> bytes:
    try:
        return json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise CandidateRejected("candidate state is not canonically serializable") from exc


def digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _validate_snapshot(snapshot: RecoverySnapshot) -> RecoverySnapshot:
    if isinstance(snapshot.revision, bool) or not isinstance(snapshot.revision, int) or snapshot.revision < 0:
        raise CandidateRejected("snapshot revision is invalid")
    if not isinstance(snapshot.state, Mapping):
        raise CandidateRejected("snapshot state must be a mapping")
    expected = digest(dict(snapshot.state))
    if snapshot.state_digest != expected:
        raise CandidateRejected("snapshot digest mismatch")
    return RecoverySnapshot(snapshot.revision, dict(snapshot.state), snapshot.state_digest)


def validate_event_window(event_ids: Sequence[str], sequences: Sequence[int]) -> None:
    if len(event_ids) != len(sequences):
        raise CandidateRejected("event identity/sequence length mismatch")
    if len(event_ids) != len(set(event_ids)):
        raise CandidateRejected("duplicate event detected")
    if any(not isinstance(item, str) or not item for item in event_ids):
        raise CandidateRejected("event id is invalid")
    if any(isinstance(item, bool) or not isinstance(item, int) or item < 1 for item in sequences):
        raise CandidateRejected("event sequence is invalid")
    if list(sequences) != sorted(sequences) or any(b != a + 1 for a, b in zip(sequences, sequences[1:])):
        raise CandidateRejected("event sequence is reordered or contains a gap")


class AtomicRecoveryStore:
    """Publishes only fully validated candidate snapshots; failed candidates preserve previous-valid state."""

    def __init__(self, initial_state: Mapping[str, Any]) -> None:
        if not isinstance(initial_state, Mapping):
            raise CandidateRejected("initial state must be a mapping")
        state = dict(initial_state)
        self._lock = threading.RLock()
        self._snapshot = RecoverySnapshot(0, state, digest(state))

    def snapshot(self) -> RecoverySnapshot:
        with self._lock:
            return RecoverySnapshot(
                self._snapshot.revision,
                dict(self._snapshot.state),
                self._snapshot.state_digest,
            )

    def restore(self, snapshot: RecoverySnapshot) -> RecoverySnapshot:
        validated = _validate_snapshot(snapshot)
        with self._lock:
            self._snapshot = validated
            return self.snapshot()

    def commit_candidate(
        self,
        *,
        expected_revision: int,
        candidate_state: Mapping[str, Any],
        fault_at: str | None = None,
    ) -> RecoverySnapshot:
        if not isinstance(candidate_state, Mapping):
            raise CandidateRejected("candidate state must be a mapping")
        candidate = dict(candidate_state)
        candidate_digest = digest(candidate)
        if fault_at == "after_validate":
            raise SimulatedCrash("simulated crash after validation")
        with self._lock:
            if expected_revision != self._snapshot.revision:
                raise CandidateRejected("stale or conflicting candidate revision")
            if fault_at == "before_publish":
                raise SimulatedCrash("simulated crash before publish")
            published = RecoverySnapshot(self._snapshot.revision + 1, candidate, candidate_digest)
            self._snapshot = published
            if fault_at == "after_publish":
                raise SimulatedCrash("simulated crash after durable publish")
            return self.snapshot()


class RecoverySupervisor:
    """Deterministic Gate 17 recovery policy. No recovery branch may expand authority."""

    def __init__(self, store: AtomicRecoveryStore) -> None:
        self.store = store

    def decide(
        self,
        *,
        scenario: RecoveryScenario,
        previous_valid: RecoverySnapshot,
        candidate_state: Mapping[str, Any] | None = None,
        event_ids: Sequence[str] = (),
        event_sequences: Sequence[int] = (),
        ai_output_valid: bool = True,
        market_data_status: str = "ready",
        artifact_complete: bool = True,
        provider_available: bool = True,
        local_node_online: bool = True,
        paper_operation_committed: bool = True,
    ) -> RecoveryDecision:
        if not isinstance(scenario, RecoveryScenario):
            raise CandidateRejected("recovery scenario must be classified")
        previous_valid = _validate_snapshot(previous_valid)
        current = self.store.snapshot()

        def preserve(reason: str, *, degraded: bool = False) -> RecoveryDecision:
            restored = self.store.restore(previous_valid)
            return RecoveryDecision(
                scenario, "restore_previous_valid", reason, current != restored, degraded,
                restored.revision, restored.state_digest,
            )

        if scenario in {RecoveryScenario.PROCESS_CRASH, RecoveryScenario.RUNNER_RESTART}:
            return preserve("restart_from_durable_checkpoint")

        if scenario is RecoveryScenario.LOCAL_LAPTOP_OFFLINE:
            if local_node_online:
                raise CandidateRejected("local-node-offline scenario requires offline evidence")
            return preserve("local_node_offline_fail_closed", degraded=True)

        if scenario is RecoveryScenario.PROVIDER_OUTAGE:
            if provider_available:
                raise CandidateRejected("provider-outage scenario requires outage evidence")
            return preserve("provider_unavailable_fail_closed", degraded=True)

        if scenario is RecoveryScenario.PARTIAL_WRITE:
            return preserve("partial_write_rejected")

        if scenario is RecoveryScenario.CORRUPT_STALE_CONFLICTING_STATE:
            if candidate_state is None:
                return preserve("candidate_state_unavailable")
            try:
                digest(dict(candidate_state))
            except CandidateRejected:
                return preserve("corrupt_candidate_rejected")
            return preserve("stale_or_conflicting_candidate_rejected")

        if scenario is RecoveryScenario.DUPLICATE_REORDERED_EVENTS:
            try:
                validate_event_window(event_ids, event_sequences)
            except CandidateRejected:
                return preserve("event_window_invalid")
            raise CandidateRejected("duplicate/reordered scenario requires invalid event evidence")

        if scenario is RecoveryScenario.INTERRUPTED_PAPER_OPERATION:
            if paper_operation_committed:
                raise CandidateRejected("interrupted-paper scenario requires uncommitted evidence")
            return preserve("interrupted_paper_operation_replayed_from_checkpoint")

        if scenario is RecoveryScenario.MALFORMED_AI_OUTPUT:
            if ai_output_valid:
                raise CandidateRejected("malformed-AI scenario requires invalid output evidence")
            return preserve("malformed_ai_output_rejected")

        if scenario is RecoveryScenario.UNAVAILABLE_STALE_MARKET_DATA:
            if market_data_status not in {"unavailable", "stale", "ambiguous"}:
                raise CandidateRejected("market-data scenario requires unavailable/stale evidence")
            return preserve(f"market_data_{market_data_status}_fail_closed", degraded=True)

        if scenario is RecoveryScenario.PARTIAL_ARTIFACT_EVIDENCE_FAILURE:
            if artifact_complete:
                raise CandidateRejected("artifact scenario requires incomplete evidence")
            return preserve("partial_evidence_rejected")

        raise CandidateRejected("unsupported recovery scenario")


def matrix_coverage() -> tuple[str, ...]:
    return tuple(item.value for item in RecoveryScenario)
