from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

SCHEMA_VERSION = 1
GENESIS_DIGEST = None
SUPPORTED_EVENT_TYPES = {"state_replace"}


class EventStoreError(ValueError):
    """Raised when event-store evidence cannot be trusted."""


def canonical_json(value: Any) -> str:
    """Return the deterministic JSON representation used for all digests."""
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise EventStoreError(f"value is not canonical-json serializable: {exc}") from exc


def sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _parse_utc(value: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise EventStoreError("recorded_at_utc must be a non-empty string")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise EventStoreError("recorded_at_utc is not valid ISO-8601") from exc
    if parsed.tzinfo is None:
        raise EventStoreError("recorded_at_utc must be timezone-aware")
    return parsed.astimezone(timezone.utc)


def _utc_iso(value: datetime | None = None) -> str:
    current = value or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise EventStoreError("recorded_at must be timezone-aware")
    return current.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _is_digest(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _event_body(event: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": event.get("schema_version"),
        "sequence": event.get("sequence"),
        "event_type": event.get("event_type"),
        "source_sha": event.get("source_sha"),
        "recorded_at_utc": event.get("recorded_at_utc"),
        "payload": event.get("payload"),
        "previous_event_digest": event.get("previous_event_digest"),
    }


def compute_event_digest(event: dict[str, Any]) -> str:
    return sha256_json(_event_body(event))


def build_event(
    *,
    sequence: int,
    event_type: str,
    source_sha: str,
    payload: dict[str, Any],
    previous_event_digest: str | None,
    recorded_at: datetime | None = None,
) -> dict[str, Any]:
    event = {
        "schema_version": SCHEMA_VERSION,
        "sequence": sequence,
        "event_type": event_type,
        "source_sha": source_sha,
        "recorded_at_utc": _utc_iso(recorded_at),
        "payload": payload,
        "previous_event_digest": previous_event_digest,
    }
    _validate_event_shape(event, require_digest=False)
    event["event_digest"] = compute_event_digest(event)
    return event


def _validate_event_shape(event: dict[str, Any], *, require_digest: bool = True) -> None:
    if not isinstance(event, dict):
        raise EventStoreError("event must be an object")
    expected = {
        "schema_version",
        "sequence",
        "event_type",
        "source_sha",
        "recorded_at_utc",
        "payload",
        "previous_event_digest",
    }
    if require_digest:
        expected.add("event_digest")
    if set(event) != expected:
        raise EventStoreError("event fields do not match the canonical schema")
    if event.get("schema_version") != SCHEMA_VERSION:
        raise EventStoreError("unsupported event schema_version")
    sequence = event.get("sequence")
    if isinstance(sequence, bool) or not isinstance(sequence, int) or sequence < 1:
        raise EventStoreError("sequence must be a positive integer")
    event_type = event.get("event_type")
    if not isinstance(event_type, str) or not event_type:
        raise EventStoreError("event_type must be a non-empty string")
    if event_type not in SUPPORTED_EVENT_TYPES:
        raise EventStoreError(f"unsupported event_type: {event_type}")
    source_sha = event.get("source_sha")
    if not isinstance(source_sha, str) or not source_sha.strip():
        raise EventStoreError("source_sha must be a non-empty string")
    _parse_utc(event.get("recorded_at_utc"))
    payload = event.get("payload")
    if not isinstance(payload, dict):
        raise EventStoreError("payload must be an object")
    if event_type == "state_replace":
        if set(payload) != {"state"} or not isinstance(payload.get("state"), dict):
            raise EventStoreError("state_replace payload must contain exactly one object field: state")
    previous = event.get("previous_event_digest")
    if previous is not None and not _is_digest(previous):
        raise EventStoreError("previous_event_digest must be null or lowercase SHA-256")
    if require_digest and not _is_digest(event.get("event_digest")):
        raise EventStoreError("event_digest must be lowercase SHA-256")
    canonical_json(payload)


def validate_chain(
    events: Iterable[dict[str, Any]],
    *,
    expected_source_sha: str | None = None,
) -> list[dict[str, Any]]:
    """Validate the complete chain before returning any trusted event."""
    rows = list(events)
    if not rows:
        raise EventStoreError("event store is empty")
    if expected_source_sha is not None and not expected_source_sha.strip():
        raise EventStoreError("expected_source_sha must be non-empty when provided")

    chain_source: str | None = None
    previous_digest: str | None = GENESIS_DIGEST
    for index, event in enumerate(rows, start=1):
        _validate_event_shape(event)
        if event["sequence"] != index:
            raise EventStoreError("event sequence is not contiguous from 1")
        if index == 1 and event["previous_event_digest"] is not GENESIS_DIGEST:
            raise EventStoreError("first event must use the genesis digest")
        if index > 1 and event["previous_event_digest"] != previous_digest:
            raise EventStoreError("event digest chain link is invalid")
        actual_digest = compute_event_digest(event)
        if event["event_digest"] != actual_digest:
            raise EventStoreError("event digest does not match canonical content")
        if chain_source is None:
            chain_source = event["source_sha"]
        elif event["source_sha"] != chain_source:
            raise EventStoreError("mixed source_sha values are not allowed in one event chain")
        if expected_source_sha is not None and event["source_sha"] != expected_source_sha:
            raise EventStoreError("event source_sha does not match expected source")
        previous_digest = event["event_digest"]
    return rows


def load_events(
    path: Path | str,
    *,
    expected_source_sha: str | None = None,
) -> list[dict[str, Any]]:
    store_path = Path(path)
    if not store_path.is_file():
        raise EventStoreError(f"event store is missing: {store_path}")
    try:
        text = store_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise EventStoreError(f"event store cannot be read: {exc}") from exc
    if not text.strip():
        raise EventStoreError("event store is empty")

    events: list[dict[str, Any]] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            raise EventStoreError(f"blank event record at line {line_number}")
        try:
            event = json.loads(line)
        except json.JSONDecodeError as exc:
            raise EventStoreError(f"malformed event JSON at line {line_number}") from exc
        if not isinstance(event, dict):
            raise EventStoreError(f"event at line {line_number} must be an object")
        events.append(event)
    return validate_chain(events, expected_source_sha=expected_source_sha)


def _atomic_write_events(path: Path, events: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    serialized = "\n".join(canonical_json(event) for event in events) + "\n"
    temp = path.with_name(f".{path.name}.tmp")
    try:
        temp.write_text(serialized, encoding="utf-8")
        os.replace(temp, path)
    except OSError as exc:
        try:
            temp.unlink(missing_ok=True)
        except OSError:
            pass
        raise EventStoreError(f"event store atomic write failed: {exc}") from exc


def append_state(
    path: Path | str,
    *,
    source_sha: str,
    state: dict[str, Any],
    recorded_at: datetime | None = None,
) -> dict[str, Any]:
    """Append one full state snapshot after validating all prior evidence."""
    if not isinstance(source_sha, str) or not source_sha.strip():
        raise EventStoreError("source_sha must be a non-empty string")
    if not isinstance(state, dict):
        raise EventStoreError("state must be an object")
    canonical_json(state)

    store_path = Path(path)
    if store_path.exists():
        events = load_events(store_path, expected_source_sha=source_sha)
        previous_digest = events[-1]["event_digest"]
        sequence = events[-1]["sequence"] + 1
    else:
        events = []
        previous_digest = GENESIS_DIGEST
        sequence = 1

    event = build_event(
        sequence=sequence,
        event_type="state_replace",
        source_sha=source_sha,
        payload={"state": state},
        previous_event_digest=previous_digest,
        recorded_at=recorded_at,
    )
    candidate = [*events, event]
    validate_chain(candidate, expected_source_sha=source_sha)
    _atomic_write_events(store_path, candidate)
    return event


def replay_state(
    path: Path | str,
    *,
    expected_source_sha: str,
    upto_sequence: int | None = None,
) -> dict[str, Any]:
    """Replay only after the entire on-disk chain has passed validation."""
    events = load_events(path, expected_source_sha=expected_source_sha)
    if upto_sequence is not None:
        if isinstance(upto_sequence, bool) or not isinstance(upto_sequence, int):
            raise EventStoreError("upto_sequence must be an integer")
        if upto_sequence < 1 or upto_sequence > len(events):
            raise EventStoreError("upto_sequence is outside the validated chain")
        replay_rows = events[:upto_sequence]
    else:
        replay_rows = events

    state: dict[str, Any] | None = None
    for event in replay_rows:
        if event["event_type"] != "state_replace":
            raise EventStoreError(f"unsupported replay event_type: {event['event_type']}")
        state = json.loads(canonical_json(event["payload"]["state"]))
    if state is None:
        raise EventStoreError("validated chain produced no replayable state")
    return state
