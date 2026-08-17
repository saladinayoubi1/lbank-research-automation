from __future__ import annotations

import hashlib
import json
import os
import re
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterable, Mapping

SCHEMA_VERSION = "nexus.observation.v1"
PROJECTION_VERSION = "nexus.observability.read.v1"
GENESIS_DIGEST = "0" * 64
MAX_EVENTS = 200_000
MAX_REFS = 20

CATEGORIES = {
    "queue",
    "agent_provider",
    "ai_usage",
    "data_readiness",
    "strategy_qualification",
    "signal_decision",
    "risk_denial",
    "paper_execution",
    "recovery",
    "context_memory",
    "circuit_policy",
}
FAILURE_CLASSES = {
    "transient",
    "persistent",
    "corrupt-state",
    "stale-state",
    "provider-unavailable",
    "network-unavailable",
    "local-node-offline",
    "invalid-data",
    "policy-denied",
    "budget-resource-denied",
    "human-required",
}
EVENT_KEYS = {
    "schema_version", "event_id", "sequence", "category", "occurred_at",
    "correlation_id", "causation_id", "actor", "inputs", "policy", "decision",
    "action", "result", "evidence", "metrics", "previous_event_digest", "event_digest",
}
ACTOR_KEYS = {"actor_type", "actor_id", "provider_id", "model_id", "model_version", "agent_id"}
INPUT_KEYS = {"input_digest", "provenance_digest", "context_id", "dataset_id", "dataset_revision"}
POLICY_KEYS = {"policy_id", "policy_version", "policy_digest"}
DECISION_KEYS = {"decision", "reason_code", "authority_level"}
ACTION_KEYS = {"tool", "operation", "target", "reversible"}
RESULT_KEYS = {"status", "failure_class", "latency_ms", "retry_count", "cost_usd", "resource_units"}
EVIDENCE_KEYS = {"evidence_digest", "resulting_state_digest", "refs"}
METRIC_KEYS = {
    "queue_latency_ms", "provider_failure", "ai_cost_usd", "data_ready",
    "qualification_state", "signal_accepted", "risk_denied", "fill_count",
    "open_positions", "pnl", "drawdown", "exposure", "recovery_event",
    "stale_memory", "circuit_break", "policy_denial",
}
SECRET_PATTERNS = (
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----", re.IGNORECASE),
    re.compile(r"authorization\s*:\s*bearer\s+\S+", re.IGNORECASE),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"(?:api[_ -]?key|api[_ -]?secret|password|access[_ -]?token|refresh[_ -]?token|seed[_ -]?phrase)\s*[:=]\s*[^\s]{8,}", re.IGNORECASE),
)


class ObservabilityError(ValueError):
    pass


@dataclass(frozen=True)
class ObservabilityState:
    event_count: int = 0
    last_sequence: int = 0
    last_event_digest: str = GENESIS_DIGEST
    last_occurred_at: str | None = None
    queue_events: int = 0
    queue_latency_total_ms: int = 0
    provider_failures: int = 0
    ai_cost_usd: Decimal = Decimal("0")
    resource_units: int = 0
    data_ready_events: int = 0
    data_blocked_events: int = 0
    qualification_events: int = 0
    accepted_signals: int = 0
    rejected_signals: int = 0
    risk_denials: int = 0
    fill_count: int = 0
    open_positions: int = 0
    pnl: Decimal = Decimal("0")
    drawdown: Decimal = Decimal("0")
    exposure: Decimal = Decimal("0")
    recoveries: int = 0
    stale_memory_events: int = 0
    circuit_breaks: int = 0
    policy_denials: int = 0
    retries: int = 0
    failures: int = 0
    latency_total_ms: int = 0


def _canonical(value: Any) -> bytes:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ObservabilityError("observation is not canonically serializable") from exc


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _exact(value: Any, keys: set[str], name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != keys:
        raise ObservabilityError(f"{name} schema mismatch")
    return dict(value)


def _identifier(value: Any, field: str, *, optional: bool = False) -> str | None:
    if value is None and optional:
        return None
    if not isinstance(value, str) or not value.strip() or len(value) > 180:
        raise ObservabilityError(f"{field} must be a non-empty bounded string")
    _reject_sensitive(value, field)
    return value


def _utc(value: Any, field: str) -> str:
    if not isinstance(value, str):
        raise ObservabilityError(f"{field} must be UTC ISO-8601")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ObservabilityError(f"{field} must be UTC ISO-8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise ObservabilityError(f"{field} must be UTC")
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _sha256(value: Any, field: str) -> str:
    if not isinstance(value, str) or len(value) != 64:
        raise ObservabilityError(f"{field} must be SHA-256")
    try:
        int(value, 16)
    except ValueError as exc:
        raise ObservabilityError(f"{field} must be hexadecimal") from exc
    return value.lower()


def _integer(value: Any, field: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ObservabilityError(f"{field} must be an integer >= {minimum}")
    return value


def _decimal(value: Any, field: str, *, nonnegative: bool = False) -> str:
    if isinstance(value, float):
        raise ObservabilityError(f"{field} must not use binary floating point")
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ObservabilityError(f"{field} must be decimal") from exc
    if not parsed.is_finite():
        raise ObservabilityError(f"{field} must be finite")
    if nonnegative and parsed < 0:
        raise ObservabilityError(f"{field} must be nonnegative")
    return str(parsed)


def _reject_sensitive(value: Any, path: str = "observation") -> None:
    if isinstance(value, str):
        if any(pattern.search(value) for pattern in SECRET_PATTERNS):
            raise ObservabilityError(f"{path} contains sensitive authorization material")
        return
    if isinstance(value, Mapping):
        for key, child in value.items():
            normalized = str(key).casefold().replace("-", "_").replace(" ", "_")
            if normalized in {
                "api_key", "api_secret", "private_key", "password", "access_token",
                "refresh_token", "authorization", "seed_phrase", "raw_chat", "raw_transcript",
            }:
                raise ObservabilityError(f"{path}.{key} is forbidden")
            _reject_sensitive(child, f"{path}.{key}")
        return
    if isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            _reject_sensitive(child, f"{path}[{index}]")


def _validate_actor(value: Any) -> dict[str, Any]:
    actor = _exact(value, ACTOR_KEYS, "actor")
    if actor["actor_type"] not in {"operator", "system", "model", "agent", "runner", "provider"}:
        raise ObservabilityError("actor type is unsupported")
    _identifier(actor["actor_id"], "actor.actor_id")
    for field in ("provider_id", "model_id", "model_version", "agent_id"):
        _identifier(actor[field], f"actor.{field}", optional=True)
    if actor["actor_type"] == "model" and (actor["provider_id"] is None or actor["model_id"] is None):
        raise ObservabilityError("model actor requires provider/model identity")
    if actor["actor_type"] == "agent" and actor["agent_id"] is None:
        raise ObservabilityError("agent actor requires agent_id")
    return actor


def _validate_inputs(value: Any) -> dict[str, Any]:
    inputs = _exact(value, INPUT_KEYS, "inputs")
    _sha256(inputs["input_digest"], "inputs.input_digest")
    _sha256(inputs["provenance_digest"], "inputs.provenance_digest")
    for field in ("context_id", "dataset_id", "dataset_revision"):
        _identifier(inputs[field], f"inputs.{field}", optional=True)
    return inputs


def _validate_policy(value: Any) -> dict[str, Any]:
    policy = _exact(value, POLICY_KEYS, "policy")
    _identifier(policy["policy_id"], "policy.policy_id")
    _identifier(policy["policy_version"], "policy.policy_version")
    _sha256(policy["policy_digest"], "policy.policy_digest")
    return policy


def _validate_decision(value: Any) -> dict[str, Any]:
    decision = _exact(value, DECISION_KEYS, "decision")
    if decision["decision"] not in {"allow", "deny", "observe", "propose", "start", "complete", "fail", "recover", "block"}:
        raise ObservabilityError("unsupported decision")
    _identifier(decision["reason_code"], "decision.reason_code")
    authority = _integer(decision["authority_level"], "decision.authority_level")
    if authority > 4:
        raise ObservabilityError("authority level is invalid")
    return decision


def _validate_action(value: Any) -> dict[str, Any]:
    action = _exact(value, ACTION_KEYS, "action")
    for field in ("tool", "operation", "target"):
        _identifier(action[field], f"action.{field}", optional=True)
    if not isinstance(action["reversible"], bool):
        raise ObservabilityError("action.reversible must be boolean")
    return action


def _validate_result(value: Any) -> dict[str, Any]:
    result = _exact(value, RESULT_KEYS, "result")
    if result["status"] not in {"success", "failure", "blocked", "cancelled", "pending", "recovered"}:
        raise ObservabilityError("unsupported result status")
    if result["failure_class"] is not None:
        if result["failure_class"] not in FAILURE_CLASSES:
            raise ObservabilityError("unknown failure class")
    result["latency_ms"] = _integer(result["latency_ms"], "result.latency_ms")
    result["retry_count"] = _integer(result["retry_count"], "result.retry_count")
    result["cost_usd"] = _decimal(result["cost_usd"], "result.cost_usd", nonnegative=True)
    result["resource_units"] = _integer(result["resource_units"], "result.resource_units")
    return result


def _validate_evidence(value: Any) -> dict[str, Any]:
    evidence = _exact(value, EVIDENCE_KEYS, "evidence")
    _sha256(evidence["evidence_digest"], "evidence.evidence_digest")
    _sha256(evidence["resulting_state_digest"], "evidence.resulting_state_digest")
    if not isinstance(evidence["refs"], list) or len(evidence["refs"]) > MAX_REFS:
        raise ObservabilityError("evidence refs must be bounded")
    for index, ref in enumerate(evidence["refs"]):
        _identifier(ref, f"evidence.refs[{index}]")
    if len(evidence["refs"]) != len(set(evidence["refs"])):
        raise ObservabilityError("evidence refs contain duplicates")
    return evidence


def _validate_metrics(value: Any) -> dict[str, Any]:
    metrics = _exact(value, METRIC_KEYS, "metrics")
    if metrics["queue_latency_ms"] is not None:
        metrics["queue_latency_ms"] = _integer(metrics["queue_latency_ms"], "metrics.queue_latency_ms")
    for field in ("fill_count", "open_positions"):
        if metrics[field] is not None:
            metrics[field] = _integer(metrics[field], f"metrics.{field}")
    for field in ("provider_failure", "data_ready", "signal_accepted", "risk_denied", "recovery_event", "stale_memory", "circuit_break", "policy_denial"):
        if metrics[field] is not None and not isinstance(metrics[field], bool):
            raise ObservabilityError(f"metrics.{field} must be boolean or null")
    for field in ("ai_cost_usd", "pnl", "drawdown", "exposure"):
        if metrics[field] is not None:
            metrics[field] = _decimal(metrics[field], f"metrics.{field}", nonnegative=field in {"ai_cost_usd", "drawdown", "exposure"})
    if metrics["qualification_state"] is not None:
        _identifier(metrics["qualification_state"], "metrics.qualification_state")
    return metrics


def build_observation(
    *,
    event_id: str,
    sequence: int,
    category: str,
    occurred_at: str,
    correlation_id: str,
    causation_id: str,
    actor: Mapping[str, Any],
    inputs: Mapping[str, Any],
    policy: Mapping[str, Any],
    decision: Mapping[str, Any],
    action: Mapping[str, Any],
    result: Mapping[str, Any],
    evidence: Mapping[str, Any],
    metrics: Mapping[str, Any],
    previous_event_digest: str,
) -> dict[str, Any]:
    _identifier(event_id, "event_id")
    _identifier(correlation_id, "correlation_id")
    _identifier(causation_id, "causation_id")
    sequence = _integer(sequence, "sequence", minimum=1)
    if category not in CATEGORIES:
        raise ObservabilityError("unknown observation category")
    occurred_at = _utc(occurred_at, "occurred_at")
    previous_event_digest = _sha256(previous_event_digest, "previous_event_digest")
    core = {
        "schema_version": SCHEMA_VERSION,
        "event_id": event_id,
        "sequence": sequence,
        "category": category,
        "occurred_at": occurred_at,
        "correlation_id": correlation_id,
        "causation_id": causation_id,
        "actor": _validate_actor(actor),
        "inputs": _validate_inputs(inputs),
        "policy": _validate_policy(policy),
        "decision": _validate_decision(decision),
        "action": _validate_action(action),
        "result": _validate_result(result),
        "evidence": _validate_evidence(evidence),
        "metrics": _validate_metrics(metrics),
        "previous_event_digest": previous_event_digest,
    }
    _reject_sensitive(core)
    return {**core, "event_digest": _digest(core)}


def validate_observation(event: Any) -> dict[str, Any]:
    event = _exact(event, EVENT_KEYS, "observation envelope")
    if event["schema_version"] != SCHEMA_VERSION:
        raise ObservabilityError("unsupported observation schema")
    rebuilt = build_observation(
        event_id=event["event_id"],
        sequence=event["sequence"],
        category=event["category"],
        occurred_at=event["occurred_at"],
        correlation_id=event["correlation_id"],
        causation_id=event["causation_id"],
        actor=event["actor"],
        inputs=event["inputs"],
        policy=event["policy"],
        decision=event["decision"],
        action=event["action"],
        result=event["result"],
        evidence=event["evidence"],
        metrics=event["metrics"],
        previous_event_digest=event["previous_event_digest"],
    )
    if rebuilt != event:
        raise ObservabilityError("observation digest or canonical content mismatch")
    return rebuilt


def _apply(state: ObservabilityState, event: Mapping[str, Any]) -> ObservabilityState:
    metrics = event["metrics"]
    result = event["result"]
    accepted = metrics["signal_accepted"]
    return ObservabilityState(
        event_count=state.event_count + 1,
        last_sequence=event["sequence"],
        last_event_digest=event["event_digest"],
        last_occurred_at=event["occurred_at"],
        queue_events=state.queue_events + (1 if event["category"] == "queue" else 0),
        queue_latency_total_ms=state.queue_latency_total_ms + int(metrics["queue_latency_ms"] or 0),
        provider_failures=state.provider_failures + (1 if metrics["provider_failure"] is True else 0),
        ai_cost_usd=state.ai_cost_usd + Decimal(str(metrics["ai_cost_usd"] if metrics["ai_cost_usd"] is not None else result["cost_usd"])),
        resource_units=state.resource_units + int(result["resource_units"]),
        data_ready_events=state.data_ready_events + (1 if metrics["data_ready"] is True else 0),
        data_blocked_events=state.data_blocked_events + (1 if metrics["data_ready"] is False else 0),
        qualification_events=state.qualification_events + (1 if metrics["qualification_state"] is not None else 0),
        accepted_signals=state.accepted_signals + (1 if accepted is True else 0),
        rejected_signals=state.rejected_signals + (1 if accepted is False else 0),
        risk_denials=state.risk_denials + (1 if metrics["risk_denied"] is True else 0),
        fill_count=state.fill_count + int(metrics["fill_count"] or 0),
        open_positions=int(metrics["open_positions"]) if metrics["open_positions"] is not None else state.open_positions,
        pnl=Decimal(str(metrics["pnl"])) if metrics["pnl"] is not None else state.pnl,
        drawdown=Decimal(str(metrics["drawdown"])) if metrics["drawdown"] is not None else state.drawdown,
        exposure=Decimal(str(metrics["exposure"])) if metrics["exposure"] is not None else state.exposure,
        recoveries=state.recoveries + (1 if metrics["recovery_event"] is True else 0),
        stale_memory_events=state.stale_memory_events + (1 if metrics["stale_memory"] is True else 0),
        circuit_breaks=state.circuit_breaks + (1 if metrics["circuit_break"] is True else 0),
        policy_denials=state.policy_denials + (1 if metrics["policy_denial"] is True else 0),
        retries=state.retries + int(result["retry_count"]),
        failures=state.failures + (1 if result["status"] in {"failure", "blocked"} else 0),
        latency_total_ms=state.latency_total_ms + int(result["latency_ms"]),
    )


def replay(events: Iterable[Mapping[str, Any]], previous: ObservabilityState | None = None) -> ObservabilityState:
    raw_events = list(events)
    if len(raw_events) > MAX_EVENTS:
        raise ObservabilityError("observation replay exceeds bounded event count")
    state = previous or ObservabilityState()
    seen_ids: set[str] = set()
    for raw in raw_events:
        event = validate_observation(raw)
        if event["event_id"] in seen_ids:
            raise ObservabilityError("duplicate observation event_id")
        seen_ids.add(event["event_id"])
        if event["sequence"] != state.last_sequence + 1:
            raise ObservabilityError("observation sequence gap, duplicate, or reordering")
        if event["previous_event_digest"] != state.last_event_digest:
            raise ObservabilityError("observation digest chain mismatch")
        if state.last_occurred_at and _utc(event["occurred_at"], "occurred_at") < _utc(state.last_occurred_at, "last_occurred_at"):
            raise ObservabilityError("observations must be UTC-time ordered")
        state = _apply(state, event)
    return state


def state_projection(state: ObservabilityState) -> dict[str, Any]:
    average_latency = state.latency_total_ms // state.event_count if state.event_count else 0
    average_queue = state.queue_latency_total_ms // state.queue_events if state.queue_events else 0
    return {
        "contract_version": PROJECTION_VERSION,
        "event_count": state.event_count,
        "last_sequence": state.last_sequence,
        "last_event_digest": state.last_event_digest,
        "queue": {"events": state.queue_events, "average_latency_ms": average_queue, "retries": state.retries},
        "agent_provider": {"failures": state.provider_failures},
        "ai": {"cost_usd": str(state.ai_cost_usd), "resource_units": state.resource_units},
        "data": {"ready_events": state.data_ready_events, "blocked_events": state.data_blocked_events},
        "strategy": {"qualification_events": state.qualification_events},
        "signals": {"accepted": state.accepted_signals, "rejected": state.rejected_signals},
        "risk": {"denials": state.risk_denials},
        "paper": {
            "fills": state.fill_count,
            "open_positions": state.open_positions,
            "pnl": str(state.pnl),
            "drawdown": str(state.drawdown),
            "exposure": str(state.exposure),
        },
        "recovery": {"events": state.recoveries},
        "context_memory": {"stale_incidents": state.stale_memory_events},
        "policy_circuits": {"circuit_breaks": state.circuit_breaks, "policy_denials": state.policy_denials},
        "overall": {"failures": state.failures, "average_latency_ms": average_latency},
    }


def load_ledger(path: str | Path) -> list[dict[str, Any]]:
    target = Path(path)
    try:
        lines = target.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return []
    except OSError as exc:
        raise ObservabilityError("observability ledger could not be read") from exc
    if len(lines) > MAX_EVENTS:
        raise ObservabilityError("observability ledger exceeds bounded event count")
    events: list[dict[str, Any]] = []
    for index, line in enumerate(lines, start=1):
        if not line:
            raise ObservabilityError(f"observability ledger contains blank line {index}")
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ObservabilityError(f"observability ledger line {index} is corrupt") from exc
        events.append(validate_observation(parsed))
    replay(events)
    return events


def append_observation(path: str | Path, event: Mapping[str, Any]) -> ObservabilityState:
    target = Path(path)
    existing = load_ledger(target)
    prior = replay(existing)
    validated = validate_observation(event)
    if validated["sequence"] != prior.last_sequence + 1:
        raise ObservabilityError("append sequence is not the next durable sequence")
    if validated["previous_event_digest"] != prior.last_event_digest:
        raise ObservabilityError("append previous digest does not match durable tail")
    next_state = _apply(prior, validated)
    target.parent.mkdir(parents=True, exist_ok=True)
    line = _canonical(validated) + b"\n"
    try:
        with target.open("ab") as handle:
            handle.write(line)
            handle.flush()
            os.fsync(handle.fileno())
    except OSError as exc:
        raise ObservabilityError("observability append failed") from exc
    return next_state


def save_projection(path: str | Path, state: ObservabilityState) -> None:
    payload = state_projection(state)
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    try:
        with tmp.open("w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, sort_keys=True, indent=2, ensure_ascii=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, target)
    except OSError as exc:
        raise ObservabilityError("observability projection commit failed") from exc


def clone_state(state: ObservabilityState) -> ObservabilityState:
    return deepcopy(state)
