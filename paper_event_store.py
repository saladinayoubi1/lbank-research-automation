from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable, Mapping

SCHEMA_VERSION = "nexus.paper-event.v1"
GENESIS_DIGEST = "0" * 64
PAPER_ONLY = True
MAX_EVENTS = 100_000
MAX_SIGNAL_AGE_SECONDS = {
    "minute15": 3_600,
    "hour1": 14_400,
    "hour4": 57_600,
    "session": 86_400,
}

EVENT_PAYLOAD_KEYS = {
    "demo_account_opened": {"currency", "opening_cash"},
    "signal_recorded": {"symbol", "timeframe", "side", "quantity", "reference_price"},
    "order_intent_recorded": {"symbol", "side", "quantity", "order_type"},
    "risk_decision_recorded": {"decision", "reason_code"},
    "risk_rejection_recorded": {"reason_code"},
    "simulated_fill_recorded": {"symbol", "side", "quantity", "price"},
    "position_opened": {"symbol", "side", "quantity", "entry_price"},
    "position_reduced": {"symbol", "quantity", "exit_price", "realized_pnl"},
    "position_closed": {"symbol", "exit_price", "realized_pnl"},
    "position_reversed": {"symbol", "side", "quantity", "entry_price", "realized_pnl"},
    "stop_set": {"symbol", "price"},
    "target_set": {"symbol", "price"},
    "fee_recorded": {"amount", "currency"},
    "slippage_recorded": {"amount", "currency"},
    "equity_snapshot_recorded": {"cash", "equity", "unrealized_pnl"},
    "kill_switch_transitioned": {"enabled", "reason_code"},
    "session_boundary_recorded": {"boundary"},
}
DECIMAL_FIELDS = {
    "opening_cash", "quantity", "reference_price", "price", "entry_price",
    "exit_price", "realized_pnl", "amount", "cash", "equity", "unrealized_pnl",
}
POSITIVE_DECIMALS = {"opening_cash", "quantity", "reference_price", "price", "entry_price", "exit_price"}
PROVENANCE_KEYS = {
    "kind", "source_id", "source_timestamp", "received_timestamp", "timeframe",
    "confidence", "strategy_version", "policy_version",
}
FORBIDDEN_TERMS = {
    "api_key", "api_secret", "credential", "private_key", "withdrawal",
    "exchange_order_id", "live_order", "production", "billing", "signing",
}
ENVELOPE_KEYS = {
    "schema_version", "event_id", "event_type", "aggregate_id", "sequence",
    "occurred_at", "correlation_id", "causation_id", "provenance",
    "previous_event_digest", "payload_digest", "event_digest",
    "paper_trading_only", "payload",
}


class PaperEventError(ValueError):
    pass


@dataclass(frozen=True)
class PortfolioState:
    aggregate_id: str | None = None
    currency: str | None = None
    cash: Decimal = Decimal("0")
    equity: Decimal = Decimal("0")
    realized_pnl: Decimal = Decimal("0")
    unrealized_pnl: Decimal = Decimal("0")
    positions: tuple[tuple[str, str, Decimal, Decimal], ...] = ()
    stops: tuple[tuple[str, Decimal], ...] = ()
    targets: tuple[tuple[str, Decimal], ...] = ()
    kill_switch_enabled: bool = False
    session_open: bool = False
    last_sequence: int = 0
    last_event_digest: str = GENESIS_DIGEST


@dataclass(frozen=True)
class ReplayResult:
    state: PortfolioState
    applied_events: int


def _canonical(value: Any) -> bytes:
    try:
        return json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise PaperEventError("event is not canonically serializable") from exc


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _utc(value: Any, field: str) -> str:
    if not isinstance(value, str):
        raise PaperEventError(f"{field} must be an ISO-8601 UTC string")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise PaperEventError(f"{field} must be an ISO-8601 UTC string") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise PaperEventError(f"{field} must be UTC")
    return parsed.astimezone(timezone.utc).isoformat()


def _decimal(value: Any, field: str, *, positive: bool = False) -> Decimal:
    if isinstance(value, float):
        raise PaperEventError(f"{field} must not use binary floating point")
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise PaperEventError(f"{field} is not a valid decimal") from exc
    if not parsed.is_finite():
        raise PaperEventError(f"{field} must be finite")
    if positive and parsed <= 0:
        raise PaperEventError(f"{field} must be positive")
    return parsed


def _validate_identifier(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 128:
        raise PaperEventError(f"{field} must be a non-empty bounded string")
    return value


def _reject_forbidden(value: Any, path: str = "event") -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            normalized = str(key).lower()
            if normalized in FORBIDDEN_TERMS or any(term in normalized for term in FORBIDDEN_TERMS):
                raise PaperEventError(f"{path}.{key} is forbidden in paper-trading events")
            _reject_forbidden(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _reject_forbidden(child, f"{path}[{index}]")


def validate_provenance(provenance: Any) -> dict[str, Any]:
    if not isinstance(provenance, dict) or set(provenance) != PROVENANCE_KEYS:
        raise PaperEventError("provenance schema mismatch")
    if provenance["kind"] not in {"automatic", "manual"}:
        raise PaperEventError("provenance.kind must be automatic or manual")
    for field in ("source_id", "strategy_version", "policy_version"):
        _validate_identifier(provenance[field], f"provenance.{field}")
    _utc(provenance["source_timestamp"], "provenance.source_timestamp")
    _utc(provenance["received_timestamp"], "provenance.received_timestamp")
    if provenance["timeframe"] not in {"minute15", "hour1", "hour4", "session"}:
        raise PaperEventError("unsupported provenance timeframe")
    confidence = _decimal(provenance["confidence"], "provenance.confidence")
    if confidence < 0 or confidence > 1:
        raise PaperEventError("provenance.confidence must be between 0 and 1")
    return dict(provenance)


def validate_payload(event_type: str, payload: Any) -> dict[str, Any]:
    if event_type not in EVENT_PAYLOAD_KEYS:
        raise PaperEventError("unknown event type")
    if not isinstance(payload, dict) or set(payload) != EVENT_PAYLOAD_KEYS[event_type]:
        raise PaperEventError("payload schema mismatch")
    _reject_forbidden(payload, "payload")
    normalized = dict(payload)
    for field in set(payload) & DECIMAL_FIELDS:
        normalized[field] = str(_decimal(payload[field], field, positive=field in POSITIVE_DECIMALS))
    if "symbol" in payload:
        _validate_identifier(payload["symbol"], "symbol")
    if payload.get("side") not in {None, "long", "short", "buy", "sell"}:
        raise PaperEventError("unsupported side")
    if event_type == "risk_decision_recorded" and payload["decision"] not in {"allow", "reject"}:
        raise PaperEventError("unsupported risk decision")
    if event_type == "session_boundary_recorded" and payload["boundary"] not in {"open", "close"}:
        raise PaperEventError("unsupported session boundary")
    if "enabled" in payload and not isinstance(payload["enabled"], bool):
        raise PaperEventError("enabled must be boolean")
    return normalized


def build_event(
    *,
    event_id: str,
    event_type: str,
    aggregate_id: str,
    sequence: int,
    occurred_at: str,
    correlation_id: str,
    causation_id: str,
    provenance: dict[str, Any],
    previous_event_digest: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    for field, value in {
        "event_id": event_id, "aggregate_id": aggregate_id,
        "correlation_id": correlation_id, "causation_id": causation_id,
    }.items():
        _validate_identifier(value, field)
    if isinstance(sequence, bool) or not isinstance(sequence, int) or sequence < 1:
        raise PaperEventError("sequence must be a positive integer")
    if not isinstance(previous_event_digest, str) or len(previous_event_digest) != 64:
        raise PaperEventError("previous_event_digest must be a SHA-256 hex digest")
    try:
        int(previous_event_digest, 16)
    except ValueError as exc:
        raise PaperEventError("previous_event_digest must be hexadecimal") from exc
    normalized_payload = validate_payload(event_type, payload)
    normalized_provenance = validate_provenance(provenance)
    normalized_occurred_at = _utc(occurred_at, "occurred_at")
    source_time = datetime.fromisoformat(normalized_provenance["source_timestamp"].replace("Z", "+00:00"))
    received_time = datetime.fromisoformat(normalized_provenance["received_timestamp"].replace("Z", "+00:00"))
    occurred_time = datetime.fromisoformat(normalized_occurred_at)
    if source_time > received_time or received_time > occurred_time:
        raise PaperEventError("provenance timestamps must be causally ordered")
    max_age = MAX_SIGNAL_AGE_SECONDS[normalized_provenance["timeframe"]]
    if event_type in {"signal_recorded", "order_intent_recorded"} and (occurred_time - source_time).total_seconds() > max_age:
        raise PaperEventError("stale signal provenance")
    core = {
        "schema_version": SCHEMA_VERSION,
        "event_id": event_id,
        "event_type": event_type,
        "aggregate_id": aggregate_id,
        "sequence": sequence,
        "occurred_at": normalized_occurred_at,
        "correlation_id": correlation_id,
        "causation_id": causation_id,
        "provenance": normalized_provenance,
        "previous_event_digest": previous_event_digest,
        "payload_digest": _digest(normalized_payload),
        "paper_trading_only": PAPER_ONLY,
        "payload": normalized_payload,
    }
    return {**core, "event_digest": _digest(core)}


def validate_event(event: Any) -> dict[str, Any]:
    if not isinstance(event, dict) or set(event) != ENVELOPE_KEYS:
        raise PaperEventError("event envelope schema mismatch")
    if event["schema_version"] != SCHEMA_VERSION or event["paper_trading_only"] is not True:
        raise PaperEventError("unsupported schema or non-paper authority")
    rebuilt = build_event(
        event_id=event["event_id"], event_type=event["event_type"],
        aggregate_id=event["aggregate_id"], sequence=event["sequence"],
        occurred_at=event["occurred_at"], correlation_id=event["correlation_id"],
        causation_id=event["causation_id"], provenance=event["provenance"],
        previous_event_digest=event["previous_event_digest"], payload=event["payload"],
    )
    if rebuilt != event:
        raise PaperEventError("event digest or canonical content mismatch")
    return rebuilt


def _as_map(entries: tuple[tuple[Any, ...], ...]) -> dict[str, tuple[Any, ...]]:
    return {str(entry[0]): tuple(entry[1:]) for entry in entries}


def _ordered(mapping: Mapping[str, tuple[Any, ...]]) -> tuple[tuple[Any, ...], ...]:
    return tuple((key, *mapping[key]) for key in sorted(mapping))


def reduce_event(state: PortfolioState, event: dict[str, Any]) -> PortfolioState:
    event = validate_event(event)
    if state.aggregate_id not in {None, event["aggregate_id"]}:
        raise PaperEventError("aggregate mismatch")
    if event["sequence"] != state.last_sequence + 1:
        raise PaperEventError("sequence gap, duplicate, or reordering")
    if event["previous_event_digest"] != state.last_event_digest:
        raise PaperEventError("event digest chain mismatch")
    payload, kind = event["payload"], event["event_type"]
    positions = _as_map(state.positions)
    stops = _as_map(state.stops)
    targets = _as_map(state.targets)
    cash, equity = state.cash, state.equity
    realized, unrealized = state.realized_pnl, state.unrealized_pnl
    currency, kill_switch, session_open = state.currency, state.kill_switch_enabled, state.session_open

    if kind == "demo_account_opened":
        if state.last_sequence:
            raise PaperEventError("demo account can only be opened once")
        currency = str(payload["currency"])
        cash = equity = _decimal(payload["opening_cash"], "opening_cash")
    elif kind in {"position_opened", "position_reversed"}:
        if kind == "position_reversed":
            realized += _decimal(payload["realized_pnl"], "realized_pnl")
        positions[str(payload["symbol"])] = (
            str(payload["side"]), _decimal(payload["quantity"], "quantity", positive=True),
            _decimal(payload["entry_price"], "entry_price", positive=True),
        )
    elif kind == "position_reduced":
        symbol = str(payload["symbol"])
        if symbol not in positions:
            raise PaperEventError("cannot reduce missing position")
        side, quantity, entry = positions[symbol]
        remaining = quantity - _decimal(payload["quantity"], "quantity", positive=True)
        if remaining <= 0:
            raise PaperEventError("position reduction must leave positive quantity")
        positions[symbol] = (side, remaining, entry)
        realized += _decimal(payload["realized_pnl"], "realized_pnl")
    elif kind == "position_closed":
        symbol = str(payload["symbol"])
        if symbol not in positions:
            raise PaperEventError("cannot close missing position")
        del positions[symbol]
        stops.pop(symbol, None); targets.pop(symbol, None)
        realized += _decimal(payload["realized_pnl"], "realized_pnl")
    elif kind == "stop_set":
        if str(payload["symbol"]) not in positions:
            raise PaperEventError("cannot set stop without position")
        stops[str(payload["symbol"])] = (_decimal(payload["price"], "price", positive=True),)
    elif kind == "target_set":
        if str(payload["symbol"]) not in positions:
            raise PaperEventError("cannot set target without position")
        targets[str(payload["symbol"])] = (_decimal(payload["price"], "price", positive=True),)
    elif kind in {"fee_recorded", "slippage_recorded"}:
        amount = _decimal(payload["amount"], "amount")
        if amount < 0 or (currency is not None and payload["currency"] != currency):
            raise PaperEventError("invalid accounting charge")
        cash -= amount
    elif kind == "equity_snapshot_recorded":
        cash = _decimal(payload["cash"], "cash")
        equity = _decimal(payload["equity"], "equity")
        unrealized = _decimal(payload["unrealized_pnl"], "unrealized_pnl")
    elif kind == "kill_switch_transitioned":
        kill_switch = payload["enabled"]
    elif kind == "session_boundary_recorded":
        session_open = payload["boundary"] == "open"

    return PortfolioState(
        aggregate_id=event["aggregate_id"], currency=currency, cash=cash, equity=equity,
        realized_pnl=realized, unrealized_pnl=unrealized,
        positions=_ordered(positions), stops=_ordered(stops), targets=_ordered(targets),
        kill_switch_enabled=kill_switch, session_open=session_open,
        last_sequence=event["sequence"], last_event_digest=event["event_digest"],
    )


def replay(events: Iterable[dict[str, Any]], previous_valid: PortfolioState | None = None) -> ReplayResult:
    state = previous_valid or PortfolioState()
    candidate = state
    seen_ids: set[str] = set()
    last_occurred: str | None = None
    applied = 0
    for event in events:
        if applied >= MAX_EVENTS:
            raise PaperEventError("event replay exceeds configured bound")
        validated = validate_event(event)
        if validated["event_id"] in seen_ids:
            raise PaperEventError("duplicate event_id")
        if last_occurred is not None and validated["occurred_at"] < last_occurred:
            raise PaperEventError("events are not UTC-time ordered")
        seen_ids.add(validated["event_id"])
        last_occurred = validated["occurred_at"]
        candidate = reduce_event(candidate, validated)
        applied += 1
    return ReplayResult(state=candidate, applied_events=applied)


def replay_or_previous(
    events: Iterable[dict[str, Any]], previous_valid: PortfolioState
) -> ReplayResult:
    try:
        return replay(events, previous_valid)
    except PaperEventError:
        return ReplayResult(state=previous_valid, applied_events=0)
