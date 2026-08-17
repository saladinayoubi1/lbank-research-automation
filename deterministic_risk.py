from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping

SIGNAL_KEYS = {
    "signal_id", "symbol", "timeframe", "strategy_id", "strategy_version",
    "side", "quantity", "reference_price", "stop_price", "target_price",
    "source_timestamp", "correlation_id", "causation_id", "provenance_kind",
}
STATE_KEYS = {
    "equity", "daily_start_equity", "daily_realized_pnl", "current_exposure",
    "position_exposure", "session_open", "signals_today", "seen_signal_ids",
    "kill_switch", "data_circuit_open", "strategy_circuit_open", "provider_circuit_open",
}
POLICY_KEYS = {
    "policy_id", "policy_version", "max_position_fraction", "max_aggregate_fraction",
    "max_daily_loss_fraction", "max_drawdown_fraction", "max_signals_per_session",
    "max_signal_age_seconds", "min_stop_distance_fraction", "max_stop_distance_fraction",
    "min_target_distance_fraction", "supported_symbols", "supported_timeframes",
    "eligible_strategies",
}


class RiskInputError(ValueError):
    pass


@dataclass(frozen=True)
class RiskDecision:
    allowed: bool
    reason_code: str
    policy_id: str
    policy_version: str
    signal_id: str
    proposed_notional: Decimal
    resulting_exposure: Decimal


def _decimal(value: Any, field: str, *, positive: bool = False) -> Decimal:
    if isinstance(value, float):
        raise RiskInputError(f"{field} must not use binary floating point")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise RiskInputError(f"{field} is not a valid decimal") from exc
    if not result.is_finite():
        raise RiskInputError(f"{field} must be finite")
    if positive and result <= 0:
        raise RiskInputError(f"{field} must be positive")
    return result


def _utc(value: Any, field: str) -> datetime:
    if not isinstance(value, str):
        raise RiskInputError(f"{field} must be UTC ISO-8601")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise RiskInputError(f"{field} must be UTC ISO-8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise RiskInputError(f"{field} must be UTC")
    return parsed.astimezone(timezone.utc)


def _exact(value: Any, keys: set[str], name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != keys:
        raise RiskInputError(f"{name} schema mismatch")
    return value


def _deny(signal: Mapping[str, Any], policy: Mapping[str, Any], reason: str, proposed: Decimal = Decimal("0"), resulting: Decimal = Decimal("0")) -> RiskDecision:
    return RiskDecision(
        allowed=False,
        reason_code=reason,
        policy_id=str(policy["policy_id"]),
        policy_version=str(policy["policy_version"]),
        signal_id=str(signal.get("signal_id", "invalid")),
        proposed_notional=proposed,
        resulting_exposure=resulting,
    )


def evaluate_risk(
    signal: Mapping[str, Any],
    state: Mapping[str, Any],
    policy: Mapping[str, Any],
    *,
    evaluated_at: str,
) -> RiskDecision:
    signal = _exact(signal, SIGNAL_KEYS, "signal")
    state = _exact(state, STATE_KEYS, "state")
    policy = _exact(policy, POLICY_KEYS, "policy")
    now = _utc(evaluated_at, "evaluated_at")
    source_time = _utc(signal["source_timestamp"], "signal.source_timestamp")
    if source_time > now:
        return _deny(signal, policy, "signal_timestamp_future")
    age = (now - source_time).total_seconds()
    max_age = int(policy["max_signal_age_seconds"])
    if max_age < 1 or age > max_age:
        return _deny(signal, policy, "signal_stale")

    if not isinstance(state["seen_signal_ids"], (tuple, list, set)):
        raise RiskInputError("seen_signal_ids must be a bounded collection")
    if len(state["seen_signal_ids"]) > 100_000:
        raise RiskInputError("seen_signal_ids exceeds configured bound")
    if signal["signal_id"] in state["seen_signal_ids"]:
        return _deny(signal, policy, "signal_duplicate")

    if signal["provenance_kind"] not in {"automatic", "manual"}:
        return _deny(signal, policy, "provenance_invalid")
    if signal["side"] not in {"long", "short"}:
        return _deny(signal, policy, "side_unsupported")
    if signal["symbol"] not in policy["supported_symbols"]:
        return _deny(signal, policy, "symbol_unsupported")
    if signal["timeframe"] not in policy["supported_timeframes"]:
        return _deny(signal, policy, "timeframe_unsupported")
    eligible = {(item["id"], item["version"]) for item in policy["eligible_strategies"]}
    if (signal["strategy_id"], signal["strategy_version"]) not in eligible:
        return _deny(signal, policy, "strategy_ineligible")

    for field, reason in (
        ("kill_switch", "kill_switch_enabled"),
        ("data_circuit_open", "data_circuit_open"),
        ("strategy_circuit_open", "strategy_circuit_open"),
        ("provider_circuit_open", "provider_circuit_open"),
    ):
        if not isinstance(state[field], bool):
            raise RiskInputError(f"{field} must be boolean")
        if state[field]:
            return _deny(signal, policy, reason)
    if state["session_open"] is not True:
        return _deny(signal, policy, "session_closed")
    if int(state["signals_today"]) >= int(policy["max_signals_per_session"]):
        return _deny(signal, policy, "session_signal_limit")

    equity = _decimal(state["equity"], "state.equity", positive=True)
    daily_start = _decimal(state["daily_start_equity"], "state.daily_start_equity", positive=True)
    daily_pnl = _decimal(state["daily_realized_pnl"], "state.daily_realized_pnl")
    exposure = _decimal(state["current_exposure"], "state.current_exposure")
    position_exposure = _decimal(state["position_exposure"], "state.position_exposure")
    quantity = _decimal(signal["quantity"], "signal.quantity", positive=True)
    price = _decimal(signal["reference_price"], "signal.reference_price", positive=True)
    stop = _decimal(signal["stop_price"], "signal.stop_price", positive=True)
    target = _decimal(signal["target_price"], "signal.target_price", positive=True)
    proposed = quantity * price
    resulting = exposure + proposed

    if daily_pnl < -(daily_start * _decimal(policy["max_daily_loss_fraction"], "policy.max_daily_loss_fraction", positive=True)):
        return _deny(signal, policy, "daily_loss_limit", proposed, resulting)
    drawdown = (daily_start - equity) / daily_start
    if drawdown > _decimal(policy["max_drawdown_fraction"], "policy.max_drawdown_fraction", positive=True):
        return _deny(signal, policy, "drawdown_limit", proposed, resulting)
    if position_exposure + proposed > equity * _decimal(policy["max_position_fraction"], "policy.max_position_fraction", positive=True):
        return _deny(signal, policy, "position_size_limit", proposed, resulting)
    if resulting > equity * _decimal(policy["max_aggregate_fraction"], "policy.max_aggregate_fraction", positive=True):
        return _deny(signal, policy, "aggregate_exposure_limit", proposed, resulting)

    stop_distance = abs(price - stop) / price
    target_distance = abs(target - price) / price
    min_stop = _decimal(policy["min_stop_distance_fraction"], "policy.min_stop_distance_fraction", positive=True)
    max_stop = _decimal(policy["max_stop_distance_fraction"], "policy.max_stop_distance_fraction", positive=True)
    min_target = _decimal(policy["min_target_distance_fraction"], "policy.min_target_distance_fraction", positive=True)
    if stop_distance < min_stop or stop_distance > max_stop:
        return _deny(signal, policy, "stop_distance_invalid", proposed, resulting)
    if target_distance < min_target:
        return _deny(signal, policy, "target_distance_invalid", proposed, resulting)
    if signal["side"] == "long" and not (stop < price < target):
        return _deny(signal, policy, "protective_prices_invalid", proposed, resulting)
    if signal["side"] == "short" and not (target < price < stop):
        return _deny(signal, policy, "protective_prices_invalid", proposed, resulting)

    return RiskDecision(
        allowed=True,
        reason_code="risk_allowed",
        policy_id=str(policy["policy_id"]),
        policy_version=str(policy["policy_version"]),
        signal_id=str(signal["signal_id"]),
        proposed_notional=proposed,
        resulting_exposure=resulting,
    )
