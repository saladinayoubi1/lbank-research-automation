from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterable, Mapping

SCHEMA_VERSION = 1
GENESIS_DIGEST = "0" * 64
MAX_STRING = 256
MAX_EVENTS_PER_READ = 100_000

TRACKED_CATEGORIES = {
    "queue",
    "agent_provider",
    "ai_budget",
    "data_readiness",
    "strategy_qualification",
    "signal",
    "risk",
    "paper_execution",
    "recovery_replay",
    "memory_context",
    "circuit_policy",
}

CRITICAL_DECISION_STAGES = {
    "market_data",
    "strategy_regime",
    "signal",
    "decision",
    "risk",
    "dispatch",
    "paper_execution",
}

AUDIT_EVENT_KEYS = {
    "schema_version",
    "event_id",
    "event_kind",
    "category",
    "stage",
    "occurred_at",
    "correlation_id",
    "causation_id",
    "actor",
    "model_id",
    "agent_id",
    "inputs_provenance",
    "policy_version",
    "decision",
    "reason_code",
    "action",
    "result",
    "evidence",
    "resulting_state",
    "metrics",
    "previous_event_digest",
    "payload_digest",
    "event_digest",
}


class ObservabilityAuditError(ValueError):
    pass


class MissingCriticalAuditEvidence(ObservabilityAuditError):
    pass


@dataclass(frozen=True)
class AuditCoverage:
    complete: bool
    missing_categories: tuple[str, ...]
    missing_stages: tuple[str, ...]
    event_count: int
    incident_count: int


def _canonical(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ObservabilityAuditError("audit value is not canonically serializable") from exc


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _bounded(value: Any, field: str, *, optional: bool = False) -> str | None:
    if value is None and optional:
        return None
    if not isinstance(value, str) or not value.strip() or len(value) > MAX_STRING:
        raise ObservabilityAuditError(f"{field} must be a non-empty bounded string")
    return value


def _utc(value: Any, field: str) -> str:
    if not isinstance(value, str):
        raise ObservabilityAuditError(f"{field} must be UTC ISO-8601")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ObservabilityAuditError(f"{field} must be UTC ISO-8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise ObservabilityAuditError(f"{field} must be UTC")
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _mapping(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ObservabilityAuditError(f"{field} must be a mapping")
    result = dict(value)
    _canonical(result)
    return result


def _metric_value(value: Any, field: str) -> str | int:
    if isinstance(value, bool):
        raise ObservabilityAuditError(f"{field} must not be boolean")
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        raise ObservabilityAuditError(f"{field} must not use binary floating point")
    try:
        decimal = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ObservabilityAuditError(f"{field} must be numeric") from exc
    if not decimal.is_finite():
        raise ObservabilityAuditError(f"{field} must be finite")
    return str(decimal)


def _validate_digest(value: Any, field: str) -> str:
    if not isinstance(value, str) or len(value) != 64:
        raise ObservabilityAuditError(f"{field} must be SHA-256")
    try:
        int(value, 16)
    except ValueError as exc:
        raise ObservabilityAuditError(f"{field} must be hexadecimal") from exc
    return value.lower()


def build_audit_event(
    *,
    event_id: str,
    event_kind: str,
    category: str,
    stage: str,
    occurred_at: str,
    correlation_id: str,
    causation_id: str | None,
    actor: str,
    inputs_provenance: Mapping[str, Any],
    policy_version: str,
    decision: str,
    reason_code: str,
    action: str,
    result: str,
    evidence: Mapping[str, Any],
    resulting_state: Mapping[str, Any],
    previous_event_digest: str = GENESIS_DIGEST,
    model_id: str | None = None,
    agent_id: str | None = None,
    metrics: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    _bounded(event_id, "event_id")
    _bounded(event_kind, "event_kind")
    if category not in TRACKED_CATEGORIES:
        raise ObservabilityAuditError("unsupported audit category")
    _bounded(stage, "stage")
    occurred_at = _utc(occurred_at, "occurred_at")
    _bounded(correlation_id, "correlation_id")
    _bounded(causation_id, "causation_id", optional=True)
    _bounded(actor, "actor")
    _bounded(model_id, "model_id", optional=True)
    _bounded(agent_id, "agent_id", optional=True)
    _bounded(policy_version, "policy_version")
    _bounded(decision, "decision")
    _bounded(reason_code, "reason_code")
    _bounded(action, "action")
    _bounded(result, "result")
    previous_event_digest = _validate_digest(previous_event_digest, "previous_event_digest")

    metric_values: dict[str, str | int] = {}
    if metrics is not None:
        if not isinstance(metrics, Mapping):
            raise ObservabilityAuditError("metrics must be a mapping")
        for key, value in metrics.items():
            _bounded(key, "metric key")
            metric_values[key] = _metric_value(value, f"metrics.{key}")

    payload = {
        "schema_version": SCHEMA_VERSION,
        "event_id": event_id,
        "event_kind": event_kind,
        "category": category,
        "stage": stage,
        "occurred_at": occurred_at,
        "correlation_id": correlation_id,
        "causation_id": causation_id,
        "actor": actor,
        "model_id": model_id,
        "agent_id": agent_id,
        "inputs_provenance": _mapping(inputs_provenance, "inputs_provenance"),
        "policy_version": policy_version,
        "decision": decision,
        "reason_code": reason_code,
        "action": action,
        "result": result,
        "evidence": _mapping(evidence, "evidence"),
        "resulting_state": _mapping(resulting_state, "resulting_state"),
        "metrics": metric_values,
        "previous_event_digest": previous_event_digest,
    }
    payload_digest = _digest(payload)
    event = {**payload, "payload_digest": payload_digest}
    event_digest = _digest(event)
    return {**event, "event_digest": event_digest}


def validate_audit_event(event: Mapping[str, Any], *, expected_previous: str | None = None) -> dict[str, Any]:
    if not isinstance(event, Mapping) or set(event) != AUDIT_EVENT_KEYS:
        raise ObservabilityAuditError("audit event schema mismatch")
    candidate = dict(event)
    if candidate["schema_version"] != SCHEMA_VERSION:
        raise ObservabilityAuditError("unsupported audit schema version")
    if candidate["category"] not in TRACKED_CATEGORIES:
        raise ObservabilityAuditError("unsupported audit category")
    _utc(candidate["occurred_at"], "occurred_at")
    for field in ("event_id", "event_kind", "stage", "correlation_id", "actor", "policy_version", "decision", "reason_code", "action", "result"):
        _bounded(candidate[field], field)
    for field in ("causation_id", "model_id", "agent_id"):
        _bounded(candidate[field], field, optional=True)
    for field in ("inputs_provenance", "evidence", "resulting_state"):
        _mapping(candidate[field], field)
    if not isinstance(candidate["metrics"], Mapping):
        raise ObservabilityAuditError("metrics must be a mapping")
    for key, value in candidate["metrics"].items():
        _bounded(key, "metric key")
        _metric_value(value, f"metrics.{key}")

    previous = _validate_digest(candidate["previous_event_digest"], "previous_event_digest")
    if expected_previous is not None and previous != expected_previous:
        raise ObservabilityAuditError("audit chain previous digest mismatch")
    payload_digest = _validate_digest(candidate["payload_digest"], "payload_digest")
    event_digest = _validate_digest(candidate["event_digest"], "event_digest")

    payload = {key: value for key, value in candidate.items() if key not in {"payload_digest", "event_digest"}}
    if _digest(payload) != payload_digest:
        raise ObservabilityAuditError("audit payload digest mismatch")
    if _digest({**payload, "payload_digest": payload_digest}) != event_digest:
        raise ObservabilityAuditError("audit event digest mismatch")
    return candidate


class AuditJournal:
    """Append-only, tamper-evident audit evidence with no domain authority."""

    def __init__(self, events: Iterable[Mapping[str, Any]] = ()) -> None:
        self._events: list[dict[str, Any]] = []
        previous = GENESIS_DIGEST
        ids: set[str] = set()
        for raw in events:
            event = validate_audit_event(raw, expected_previous=previous)
            if event["event_id"] in ids:
                raise ObservabilityAuditError("duplicate audit event_id")
            ids.add(event["event_id"])
            self._events.append(event)
            previous = event["event_digest"]

    @property
    def previous_event_digest(self) -> str:
        return self._events[-1]["event_digest"] if self._events else GENESIS_DIGEST

    @property
    def events(self) -> tuple[dict[str, Any], ...]:
        return tuple(dict(event) for event in self._events)

    def append(self, **fields: Any) -> dict[str, Any]:
        if any(event["event_id"] == fields.get("event_id") for event in self._events):
            raise ObservabilityAuditError("duplicate audit event_id")
        event = build_audit_event(previous_event_digest=self.previous_event_digest, **fields)
        self._events.append(event)
        return dict(event)

    def trace(self, correlation_id: str) -> tuple[dict[str, Any], ...]:
        _bounded(correlation_id, "correlation_id")
        return tuple(dict(event) for event in self._events if event["correlation_id"] == correlation_id)

    def verify(self) -> None:
        previous = GENESIS_DIGEST
        ids: set[str] = set()
        for event in self._events:
            validate_audit_event(event, expected_previous=previous)
            if event["event_id"] in ids:
                raise ObservabilityAuditError("duplicate audit event_id")
            ids.add(event["event_id"])
            previous = event["event_digest"]

    def write_jsonl(self, path: str | Path) -> None:
        self.verify()
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        content = b"".join(_canonical(event) + b"\n" for event in self._events)
        target.write_bytes(content)

    @classmethod
    def read_jsonl(cls, path: str | Path) -> "AuditJournal":
        target = Path(path)
        if not target.exists():
            return cls()
        events: list[dict[str, Any]] = []
        with target.open("r", encoding="utf-8") as handle:
            for index, line in enumerate(handle, start=1):
                if index > MAX_EVENTS_PER_READ:
                    raise ObservabilityAuditError("audit journal exceeds bounded read limit")
                if not line.strip():
                    raise ObservabilityAuditError("audit journal contains blank records")
                try:
                    value = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ObservabilityAuditError("audit journal contains malformed JSON") from exc
                if not isinstance(value, dict):
                    raise ObservabilityAuditError("audit journal record must be an object")
                events.append(value)
        return cls(events)


def audit_coverage(events: Iterable[Mapping[str, Any]], *, require_full_decision_path: bool = True) -> AuditCoverage:
    validated: list[dict[str, Any]] = []
    previous = GENESIS_DIGEST
    for raw in events:
        event = validate_audit_event(raw, expected_previous=previous)
        validated.append(event)
        previous = event["event_digest"]
    categories = {event["category"] for event in validated}
    stages = {event["stage"] for event in validated}
    missing_categories = tuple(sorted(TRACKED_CATEGORIES - categories))
    missing_stages = tuple(sorted(CRITICAL_DECISION_STAGES - stages)) if require_full_decision_path else ()
    incidents = sum(1 for event in validated if event["event_kind"] == "incident")
    return AuditCoverage(
        complete=not missing_categories and not missing_stages,
        missing_categories=missing_categories,
        missing_stages=missing_stages,
        event_count=len(validated),
        incident_count=incidents,
    )


def require_gate15_evidence(events: Iterable[Mapping[str, Any]]) -> AuditCoverage:
    coverage = audit_coverage(events)
    if not coverage.complete:
        missing = ",".join((*coverage.missing_categories, *coverage.missing_stages))
        raise MissingCriticalAuditEvidence(f"Gate 15 evidence incomplete: {missing}")
    return coverage


def operator_snapshot(events: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Build a bounded read-only dashboard summary; this function cannot authorize actions."""
    validated: list[dict[str, Any]] = []
    previous = GENESIS_DIGEST
    for raw in events:
        event = validate_audit_event(raw, expected_previous=previous)
        validated.append(event)
        previous = event["event_digest"]

    by_category = {category: 0 for category in sorted(TRACKED_CATEGORIES)}
    last_reason_codes: list[str] = []
    incidents = 0
    for event in validated:
        by_category[event["category"]] += 1
        if event["event_kind"] == "incident":
            incidents += 1
        if event["reason_code"] not in {"ok", "none"}:
            last_reason_codes.append(event["reason_code"])
    coverage = audit_coverage(validated)
    return {
        "contract_version": "nexus.observability.read.v1",
        "read_only": True,
        "event_count": len(validated),
        "incident_count": incidents,
        "category_counts": by_category,
        "coverage_complete": coverage.complete,
        "missing_categories": list(coverage.missing_categories),
        "missing_stages": list(coverage.missing_stages),
        "last_reason_codes": last_reason_codes[-20:],
        "head_event_digest": validated[-1]["event_digest"] if validated else GENESIS_DIGEST,
    }
