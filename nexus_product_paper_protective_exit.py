"""Protective Stop/Target exit guard for the local NEXUS Product Paper wallet.

Paper-only and risk-reducing by construction.  It consumes one already-normalized
closed Bybit candle and may only fully close an existing ProductRuntime position.
It never opens, increases, reverses, promotes, signs, or routes Live orders.

When both stop and target are touched inside the same candle, STOP_FIRST is used
as the conservative deterministic intrabar policy; no optimistic path is assumed.
"""
from __future__ import annotations

import hashlib
import json
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping

from paper_event_store import build_event, replay
from paper_execution import execute_paper_command
from product_research_runtime import TIMEFRAMES, _utc_ms
from product_runtime import (
    PAPER_CURRENCY,
    PAPER_DEFAULT_FEE_RATE,
    PAPER_DEFAULT_SLIPPAGE_BPS,
    ProductRuntime,
    _risk_reducing_exit,
)

SCHEMA = "nexus.product-paper-protective-exit.v1"
_TIMEFRAME_TO_INTERVAL = {"minute15": "15", "hour1": "60", "hour4": "240"}


class ProductPaperProtectiveExitError(RuntimeError):
    pass


def _decimal(value: Any, field: str) -> Decimal:
    if isinstance(value, bool):
        raise ProductPaperProtectiveExitError(f"{field} must be numeric")
    try:
        out = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ProductPaperProtectiveExitError(f"{field} is invalid") from exc
    if not out.is_finite() or out <= 0:
        raise ProductPaperProtectiveExitError(f"{field} must be positive and finite")
    return out


def _digest(value: Mapping[str, Any]) -> str:
    raw = json.dumps(dict(value), sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _position(state: Any, symbol: str):
    return next((row for row in state.positions if row[0] == symbol), None)


def _protection(state: Any, symbol: str) -> tuple[Decimal, Decimal]:
    stop = next((row[1] for row in state.stops if row[0] == symbol), None)
    target = next((row[1] for row in state.targets if row[0] == symbol), None)
    if stop is None or target is None:
        raise ProductPaperProtectiveExitError("existing Paper position lacks stop/target protection")
    return Decimal(stop), Decimal(target)


def _validate_candle(candle: Mapping[str, Any], *, symbol: str, timeframe: str) -> tuple[Decimal, Decimal, int]:
    if not isinstance(candle, Mapping):
        raise ProductPaperProtectiveExitError("closed candle must be an object")
    if timeframe not in _TIMEFRAME_TO_INTERVAL:
        raise ProductPaperProtectiveExitError("unsupported Paper timeframe")
    if candle.get("source") != "Bybit" or candle.get("market_type") != "spot":
        raise ProductPaperProtectiveExitError("protective exit requires canonical Bybit spot evidence")
    if str(candle.get("symbol", "")).upper() != symbol:
        raise ProductPaperProtectiveExitError("candle symbol does not match Paper position")
    if candle.get("interval") != _TIMEFRAME_TO_INTERVAL[timeframe]:
        raise ProductPaperProtectiveExitError("candle timeframe does not match Paper position")
    if candle.get("closed") is not True:
        raise ProductPaperProtectiveExitError("protective exit requires a closed candle")
    high = _decimal(candle.get("high"), "candle.high")
    low = _decimal(candle.get("low"), "candle.low")
    if high < low:
        raise ProductPaperProtectiveExitError("closed candle high/low range is invalid")
    close_time_ms = candle.get("close_time_ms")
    if isinstance(close_time_ms, bool) or not isinstance(close_time_ms, int) or close_time_ms < 0:
        raise ProductPaperProtectiveExitError("closed candle timestamp is invalid")
    return high, low, close_time_ms


def evaluate_protective_exit(
    *,
    runtime: ProductRuntime,
    candle: Mapping[str, Any],
    symbol: str,
    timeframe: str,
    strategy_version: str,
) -> dict[str, Any]:
    """Hold or fully close an existing Paper position from one verified closed candle."""
    if not isinstance(runtime, ProductRuntime):
        raise ProductPaperProtectiveExitError("runtime is invalid")
    symbol = str(symbol).upper().strip()
    strategy_version = str(strategy_version).strip()
    if not symbol or not strategy_version:
        raise ProductPaperProtectiveExitError("position identity is incomplete")
    high, low, close_time_ms = _validate_candle(candle, symbol=symbol, timeframe=timeframe)

    with runtime._lock:
        events = runtime._ensure_account()
        state = replay(events).state
        current = _position(state, symbol)
        if current is None:
            return {
                "schema_version": SCHEMA, "status": "FLAT", "reason_code": "NO_EXISTING_POSITION",
                "symbol": symbol, "timeframe": timeframe, "paper_only": True,
                "live_trading_authority": False, "exposure_increased": False, "event_count_added": 0,
            }

        _item_symbol, side, quantity, _entry = current
        stop, target = _protection(state, symbol)
        if side == "long":
            stop_hit, target_hit = low <= stop, high >= target
        elif side == "short":
            stop_hit, target_hit = high >= stop, low <= target
        else:
            raise ProductPaperProtectiveExitError("Paper position side is invalid")

        if not stop_hit and not target_hit:
            return {
                "schema_version": SCHEMA, "status": "HELD", "reason_code": "PROTECTION_NOT_TOUCHED",
                "symbol": symbol, "timeframe": timeframe, "candle_close_time_ms": close_time_ms,
                "stop_price": str(stop), "target_price": str(target),
                "paper_only": True, "live_trading_authority": False,
                "exposure_increased": False, "event_count_added": 0,
            }

        if stop_hit:
            trigger = "STOP"
            reason = "STOP_AND_TARGET_TOUCHED_STOP_FIRST" if target_hit else "STOP_TOUCHED"
            reference = stop
        else:
            trigger = "TARGET"
            reason = "TARGET_TOUCHED"
            reference = target

        occurred_at = _utc_ms(close_time_ms)
        binding = {
            "head_event_digest": state.last_event_digest,
            "symbol": symbol, "timeframe": timeframe, "strategy_version": strategy_version,
            "side": side, "quantity": str(quantity), "reference_price": str(reference),
            "candle_open_time_ms": candle.get("open_time_ms"), "candle_close_time_ms": close_time_ms,
            "trigger": trigger, "reason_code": reason,
        }
        token = _digest(binding)
        signal_id = f"protective-exit-{token[:40]}"
        correlation_id = f"protective-exit-{token[:32]}"
        risk = _risk_reducing_exit(
            state=state, signal_id=signal_id, symbol=symbol, side=side,
            quantity=str(quantity), reference_price=str(reference),
        )
        if not risk.allowed:
            raise ProductPaperProtectiveExitError("deterministic risk-reducing exit gate rejected close")

        provenance = {
            "kind": "automatic",
            "source_id": "nexus-product-paper-protective-exit",
            "source_timestamp": occurred_at,
            "received_timestamp": occurred_at,
            "timeframe": timeframe,
            "confidence": "1",
            "strategy_version": strategy_version,
            "policy_version": "nexus-product-paper-risk-v1",
        }
        signal_event = build_event(
            event_id=f"{signal_id}:signal",
            event_type="signal_recorded",
            aggregate_id=state.aggregate_id or "nexus-demo-paper",
            sequence=state.last_sequence + 1,
            occurred_at=occurred_at,
            correlation_id=correlation_id,
            causation_id=f"protective:{token[:40]}",
            provenance=provenance,
            previous_event_digest=state.last_event_digest,
            payload={
                "symbol": symbol, "timeframe": timeframe, "side": side,
                "quantity": str(quantity), "reference_price": str(reference),
            },
        )
        signal_state = replay([signal_event], previous_valid=state).state
        result = execute_paper_command(
            command={
                "operation": "close", "symbol": symbol, "side": side,
                "quantity": str(quantity), "reference_price": str(reference),
                "stop_price": str(reference), "target_price": str(reference),
                "fee_rate": PAPER_DEFAULT_FEE_RATE,
                "slippage_bps": PAPER_DEFAULT_SLIPPAGE_BPS,
                "currency": PAPER_CURRENCY,
            },
            state=signal_state,
            risk_decision=risk,
            occurred_at=occurred_at,
            provenance=provenance,
            correlation_id=correlation_id,
            causation_id=signal_id,
        )
        if _position(result.state, symbol) is not None:
            raise ProductPaperProtectiveExitError("protective close left residual exposure")
        runtime._write_events([*events, signal_event, *result.events])

    return {
        "schema_version": SCHEMA, "status": "CLOSED", "reason_code": reason,
        "trigger": trigger, "symbol": symbol, "timeframe": timeframe,
        "reference_price": str(reference), "fill_price": str(result.fill_price),
        "realized_pnl": str(result.realized_pnl), "risk_reason": risk.reason_code,
        "event_count_added": 1 + len(result.events), "paper_only": True,
        "live_trading_authority": False, "exposure_increased": False,
        "terminal_event_digest": result.state.last_event_digest,
    }
