from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from typing import Any

from strategy_registry import HEALTH_SCHEMA, REGISTRY_SCHEMA


LIFECYCLE_SCHEMA = "nexus.phase7-strategy-lifecycle.v1"
GENESIS_DIGEST = "0" * 64
LIFECYCLE_STATES = {
    "IDEA",
    "RESEARCHED",
    "BACKTESTED",
    "VALIDATED",
    "CANDIDATE",
    "PAPER",
    "QUARANTINED",
    "REJECTED",
}
PAPER_ACCEPTANCE_KEYS = {
    "risk_gate_allowed",
    "replay_verified",
    "paper_execution_evidence_sha256",
    "independent_verifier_evidence_sha256",
    "producer_id",
    "verifier_id",
}
_HEX64 = re.compile(r"^[0-9a-f]{64}$")


class StrategyLifecycleError(ValueError):
    pass


def _canonical_json(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise StrategyLifecycleError("lifecycle artifact is not canonical JSON") from exc


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def _sha256(value: Any, field: str) -> str:
    if not isinstance(value, str) or not _HEX64.fullmatch(value.lower()):
        raise StrategyLifecycleError(f"{field} must be a SHA-256 digest")
    return value.lower()


def _bounded_text(value: Any, field: str, *, limit: int = 128) -> str:
    if not isinstance(value, str) or not value or len(value) > limit:
        raise StrategyLifecycleError(f"{field} must be a bounded non-empty string")
    return value


def _validate_record(record: Any) -> dict[str, Any]:
    if not isinstance(record, Mapping) or record.get("schema_version") != REGISTRY_SCHEMA:
        raise StrategyLifecycleError("registry record schema mismatch")
    claimed = _sha256(record.get("record_digest"), "record_digest")
    core = dict(record)
    core.pop("record_digest", None)
    if _digest(core) != claimed:
        raise StrategyLifecycleError("registry record digest mismatch")
    if record.get("paper_only") is not True or record.get("live_execution_allowed") is not False:
        raise StrategyLifecycleError("registry record exceeds Paper authority")
    if record.get("deterministic_risk_final_authority") is not True:
        raise StrategyLifecycleError("deterministic Risk authority is required")
    if record.get("lifecycle_state") not in {"CANDIDATE", "REJECTED"}:
        raise StrategyLifecycleError("unsupported immutable registry lifecycle state")
    _sha256(record.get("strategy_id"), "strategy_id")
    _bounded_text(record.get("strategy_version"), "strategy_version")
    for field in ("experiment_id", "qualification_digest", "evidence_digest"):
        _sha256(record.get(field), field)
    return dict(record)


def _transition(
    *,
    record: Mapping[str, Any],
    sequence: int,
    from_state: str,
    to_state: str,
    reason_code: str,
    evidence_ref: str,
    previous_transition_digest: str,
) -> dict[str, Any]:
    if from_state not in LIFECYCLE_STATES or to_state not in LIFECYCLE_STATES:
        raise StrategyLifecycleError("unsupported lifecycle state")
    if isinstance(sequence, bool) or not isinstance(sequence, int) or sequence < 1:
        raise StrategyLifecycleError("sequence must be a positive integer")
    _bounded_text(reason_code, "reason_code")
    _sha256(evidence_ref, "evidence_ref")
    _sha256(previous_transition_digest, "previous_transition_digest")
    core = {
        "schema_version": LIFECYCLE_SCHEMA,
        "strategy_id": record["strategy_id"],
        "strategy_version": record["strategy_version"],
        "record_digest": record["record_digest"],
        "sequence": sequence,
        "from_state": from_state,
        "to_state": to_state,
        "reason_code": reason_code,
        "evidence_ref": evidence_ref,
        "previous_transition_digest": previous_transition_digest,
        "paper_only": True,
        "promotion_authority": False,
        "deterministic_risk_final_authority": True,
    }
    return {**core, "transition_digest": _digest(core)}


def validate_transition(event: Any) -> dict[str, Any]:
    if not isinstance(event, Mapping):
        raise StrategyLifecycleError("lifecycle transition must be a mapping")
    expected = {
        "schema_version",
        "strategy_id",
        "strategy_version",
        "record_digest",
        "sequence",
        "from_state",
        "to_state",
        "reason_code",
        "evidence_ref",
        "previous_transition_digest",
        "paper_only",
        "promotion_authority",
        "deterministic_risk_final_authority",
        "transition_digest",
    }
    if set(event) != expected or event.get("schema_version") != LIFECYCLE_SCHEMA:
        raise StrategyLifecycleError("lifecycle transition schema mismatch")
    if event.get("paper_only") is not True or event.get("promotion_authority") is not False:
        raise StrategyLifecycleError("lifecycle transition exceeds bounded authority")
    if event.get("deterministic_risk_final_authority") is not True:
        raise StrategyLifecycleError("deterministic Risk authority is required")
    core = dict(event)
    claimed = _sha256(core.pop("transition_digest", None), "transition_digest")
    _sha256(core.get("strategy_id"), "strategy_id")
    _sha256(core.get("record_digest"), "record_digest")
    _sha256(core.get("evidence_ref"), "evidence_ref")
    _sha256(core.get("previous_transition_digest"), "previous_transition_digest")
    _bounded_text(core.get("strategy_version"), "strategy_version")
    _bounded_text(core.get("reason_code"), "reason_code")
    if core.get("from_state") not in LIFECYCLE_STATES or core.get("to_state") not in LIFECYCLE_STATES:
        raise StrategyLifecycleError("unsupported lifecycle state")
    sequence = core.get("sequence")
    if isinstance(sequence, bool) or not isinstance(sequence, int) or sequence < 1:
        raise StrategyLifecycleError("sequence must be a positive integer")
    if _digest(core) != claimed:
        raise StrategyLifecycleError("lifecycle transition digest mismatch")
    return dict(event)


def replay_lifecycle(transitions: Sequence[Mapping[str, Any]]) -> str:
    if not isinstance(transitions, Sequence) or isinstance(transitions, (str, bytes)) or not transitions:
        raise StrategyLifecycleError("lifecycle transitions must be a non-empty sequence")
    previous_digest = GENESIS_DIGEST
    previous_state = "IDEA"
    strategy_id: str | None = None
    strategy_version: str | None = None
    record_digest: str | None = None
    for index, raw in enumerate(transitions, start=1):
        event = validate_transition(raw)
        if event["sequence"] != index:
            raise StrategyLifecycleError("lifecycle sequence gap, duplicate, or reordering")
        if event["previous_transition_digest"] != previous_digest:
            raise StrategyLifecycleError("lifecycle digest chain mismatch")
        if event["from_state"] != previous_state:
            raise StrategyLifecycleError("lifecycle state transition mismatch")
        if strategy_id is None:
            strategy_id = event["strategy_id"]
            strategy_version = event["strategy_version"]
            record_digest = event["record_digest"]
        elif (
            event["strategy_id"] != strategy_id
            or event["strategy_version"] != strategy_version
            or event["record_digest"] != record_digest
        ):
            raise StrategyLifecycleError("lifecycle identity changed within stream")
        if previous_state in {"REJECTED", "QUARANTINED"}:
            raise StrategyLifecycleError("terminal lifecycle state cannot transition")
        previous_state = event["to_state"]
        previous_digest = event["transition_digest"]
    return previous_state


def build_research_lifecycle(record: Mapping[str, Any]) -> tuple[dict[str, Any], ...]:
    """Materialize deterministic research stages already bound by one immutable record."""
    record = _validate_record(record)
    stages = [
        ("IDEA", "RESEARCHED", "HYPOTHESIS_AND_DATA_BOUND", record["experiment_id"]),
        ("RESEARCHED", "BACKTESTED", "BACKTEST_EVIDENCE_BOUND", record["evidence_digest"]),
        ("BACKTESTED", "VALIDATED", "VALIDATION_EVIDENCE_BOUND", record["qualification_digest"]),
    ]
    if record["lifecycle_state"] == "CANDIDATE":
        stages.append(("VALIDATED", "CANDIDATE", "QUALIFICATION_PASSED", record["qualification_digest"]))
    else:
        stages.append(("VALIDATED", "REJECTED", "QUALIFICATION_REJECTED", record["qualification_digest"]))

    events: list[dict[str, Any]] = []
    previous = GENESIS_DIGEST
    for sequence, (from_state, to_state, reason_code, evidence_ref) in enumerate(stages, start=1):
        event = _transition(
            record=record,
            sequence=sequence,
            from_state=from_state,
            to_state=to_state,
            reason_code=reason_code,
            evidence_ref=evidence_ref,
            previous_transition_digest=previous,
        )
        events.append(event)
        previous = event["transition_digest"]
    replay_lifecycle(events)
    return tuple(events)


def _validate_paper_acceptance(acceptance: Any) -> dict[str, Any]:
    if not isinstance(acceptance, Mapping) or set(acceptance) != PAPER_ACCEPTANCE_KEYS:
        raise StrategyLifecycleError("Paper acceptance schema mismatch")
    if not isinstance(acceptance["risk_gate_allowed"], bool) or acceptance["risk_gate_allowed"] is not True:
        raise StrategyLifecycleError("deterministic Risk gate approval is required")
    if not isinstance(acceptance["replay_verified"], bool) or acceptance["replay_verified"] is not True:
        raise StrategyLifecycleError("replay verification is required")
    execution_evidence = _sha256(
        acceptance["paper_execution_evidence_sha256"], "paper_execution_evidence_sha256"
    )
    verifier_evidence = _sha256(
        acceptance["independent_verifier_evidence_sha256"],
        "independent_verifier_evidence_sha256",
    )
    if execution_evidence == verifier_evidence:
        raise StrategyLifecycleError("Paper execution and verifier evidence must be distinct")
    producer = _bounded_text(acceptance["producer_id"], "producer_id")
    verifier = _bounded_text(acceptance["verifier_id"], "verifier_id")
    if producer == verifier:
        raise StrategyLifecycleError("Paper producer and verifier must be distinct")
    return dict(acceptance)


def promote_candidate_to_paper(
    record: Mapping[str, Any],
    transitions: Sequence[Mapping[str, Any]],
    acceptance: Mapping[str, Any],
) -> tuple[dict[str, Any], ...]:
    record = _validate_record(record)
    if record["lifecycle_state"] != "CANDIDATE":
        raise StrategyLifecycleError("only an immutable CANDIDATE record can enter Paper")
    events = tuple(dict(event) for event in transitions)
    if replay_lifecycle(events) != "CANDIDATE":
        raise StrategyLifecycleError("lifecycle must currently be CANDIDATE")
    if any(event["record_digest"] != record["record_digest"] for event in events):
        raise StrategyLifecycleError("lifecycle is bound to a different registry record")
    acceptance = _validate_paper_acceptance(acceptance)
    acceptance_digest = _digest(acceptance)
    event = _transition(
        record=record,
        sequence=len(events) + 1,
        from_state="CANDIDATE",
        to_state="PAPER",
        reason_code="PAPER_ACCEPTANCE_VERIFIED",
        evidence_ref=acceptance_digest,
        previous_transition_digest=events[-1]["transition_digest"],
    )
    result = (*events, event)
    replay_lifecycle(result)
    return result


def _validate_health(record: Mapping[str, Any], health: Any) -> dict[str, Any]:
    if not isinstance(health, Mapping) or health.get("schema_version") != HEALTH_SCHEMA:
        raise StrategyLifecycleError("strategy health schema mismatch")
    core = dict(health)
    claimed = _sha256(core.pop("health_digest", None), "health_digest")
    if _digest(core) != claimed:
        raise StrategyLifecycleError("strategy health digest mismatch")
    if health.get("strategy_id") != record["strategy_id"] or health.get("strategy_version") != record["strategy_version"]:
        raise StrategyLifecycleError("strategy health identity mismatch")
    if health.get("record_digest") != record["record_digest"]:
        raise StrategyLifecycleError("strategy health record binding mismatch")
    if health.get("paper_only") is not True or health.get("promotion_authority") is not False:
        raise StrategyLifecycleError("strategy health exceeds bounded authority")
    if health.get("deterministic_risk_final_authority") is not True:
        raise StrategyLifecycleError("deterministic Risk authority is required")
    if health.get("health_state") not in {"HEALTHY", "WATCH", "DEGRADED", "QUARANTINED"}:
        raise StrategyLifecycleError("unsupported strategy health state")
    return dict(health)


def apply_health_lifecycle(
    record: Mapping[str, Any],
    transitions: Sequence[Mapping[str, Any]],
    health: Mapping[str, Any],
) -> tuple[dict[str, Any], ...]:
    """Append quarantine only for deterministic QUARANTINED health; otherwise preserve state."""
    record = _validate_record(record)
    events = tuple(dict(event) for event in transitions)
    current = replay_lifecycle(events)
    if any(event["record_digest"] != record["record_digest"] for event in events):
        raise StrategyLifecycleError("lifecycle is bound to a different registry record")
    health = _validate_health(record, health)
    if health["health_state"] != "QUARANTINED":
        return events
    if current not in {"CANDIDATE", "PAPER"}:
        raise StrategyLifecycleError("only active candidate or Paper state can be quarantined")
    event = _transition(
        record=record,
        sequence=len(events) + 1,
        from_state=current,
        to_state="QUARANTINED",
        reason_code="HEALTH_QUARANTINE",
        evidence_ref=health["health_digest"],
        previous_transition_digest=events[-1]["transition_digest"],
    )
    result = (*events, event)
    replay_lifecycle(result)
    return result
