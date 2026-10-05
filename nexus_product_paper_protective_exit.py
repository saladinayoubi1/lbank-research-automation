"""Protective Stop/Target exit guard for the local NEXUS Product Paper wallet.

Paper-only and risk-reducing by construction.  It consumes one already-normalized
closed Bybit candle and may only fully close an existing ProductRuntime position.
It never opens, increases, reverses, promotes, signs, or routes Live orders.

When both stop and target are touched inside the same candle, STOP_FIRST is used
as the conservative deterministic intrabar policy; no optimistic path is assumed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Callable, Mapping

from bybit_public_klines import INTERVAL_MS, fetch_closed_klines
from paper_event_store import build_event, replay
from paper_execution import execute_paper_command
from product_research_runtime import _utc_ms
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


def _iso_utc_ms(value: Any) -> int:
    text = str(value or "").strip()
    if not text:
        raise ProductPaperProtectiveExitError("position open timestamp is unavailable")
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ProductPaperProtectiveExitError("position open timestamp is invalid") from exc
    if parsed.tzinfo is None:
        raise ProductPaperProtectiveExitError("position open timestamp lacks timezone")
    return int(parsed.astimezone(timezone.utc).timestamp() * 1000)


def _active_position_metadata(events: list[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    active: dict[str, dict[str, Any]] = {}
    for event in events:
        payload = event.get("payload", {})
        if not isinstance(payload, Mapping):
            continue
        symbol = str(payload.get("symbol", "")).upper().strip()
        if not symbol:
            continue
        event_type = event.get("event_type")
        if event_type in {"position_opened", "position_reversed"}:
            provenance = event.get("provenance", {})
            if not isinstance(provenance, Mapping):
                raise ProductPaperProtectiveExitError("position provenance is invalid")
            active[symbol] = {
                "opened_at": event.get("occurred_at"),
                "timeframe": provenance.get("timeframe"),
                "strategy_version": provenance.get("strategy_version"),
                "source_id": provenance.get("source_id"),
                "kind": provenance.get("kind"),
            }
        elif event_type == "position_closed":
            active.pop(symbol, None)
    return active


def evaluate_protective_exit(
    *,
    runtime: ProductRuntime,
    candle: Mapping[str, Any],
    symbol: str,
    timeframe: str,
    strategy_version: str,
    opened_at_utc: str | None = None,
) -> dict[str, Any]:
    """Hold or fully close an existing Paper position from one verified closed candle."""
    if not isinstance(runtime, ProductRuntime):
        raise ProductPaperProtectiveExitError("runtime is invalid")
    symbol = str(symbol).upper().strip()
    strategy_version = str(strategy_version).strip()
    if not symbol or not strategy_version:
        raise ProductPaperProtectiveExitError("position identity is incomplete")
    high, low, close_time_ms = _validate_candle(candle, symbol=symbol, timeframe=timeframe)
    if opened_at_utc is not None and close_time_ms < _iso_utc_ms(opened_at_utc):
        raise ProductPaperProtectiveExitError("closed candle predates the active Paper position")

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


def run_once(
    *,
    runtime: ProductRuntime,
    now_ms: int | None = None,
    fetcher: Callable[..., list[dict[str, Any]]] = fetch_closed_klines,
) -> dict[str, Any]:
    """Check each open Product Paper position against the latest verified closed Bybit candle."""
    if not isinstance(runtime, ProductRuntime):
        raise ProductPaperProtectiveExitError("runtime is invalid")
    if now_ms is None:
        now_ms = int(time.time() * 1000)
    if isinstance(now_ms, bool) or not isinstance(now_ms, int) or now_ms <= 0:
        raise ProductPaperProtectiveExitError("runner clock is invalid")

    with runtime._lock:
        events = runtime._ensure_account()
        state = replay(events).state
        positions = list(state.positions)
        metadata = _active_position_metadata(events)

    results: list[dict[str, Any]] = []
    for symbol, side, quantity, entry in positions:
        meta = metadata.get(symbol)
        if not meta:
            results.append({
                "symbol": symbol, "status": "BLOCKED", "reason_code": "POSITION_METADATA_MISSING",
                "paper_only": True, "live_trading_authority": False, "exposure_increased": False,
            })
            continue

        timeframe = str(meta.get("timeframe") or "")
        strategy_version = str(meta.get("strategy_version") or "")
        opened_at = str(meta.get("opened_at") or "")
        if timeframe not in _TIMEFRAME_TO_INTERVAL or not strategy_version or not opened_at:
            results.append({
                "symbol": symbol, "status": "BLOCKED", "reason_code": "POSITION_METADATA_INVALID",
                "paper_only": True, "live_trading_authority": False, "exposure_increased": False,
            })
            continue

        interval = _TIMEFRAME_TO_INTERVAL[timeframe]
        step_ms = INTERVAL_MS[interval]
        latest_open_ms = (now_ms // step_ms - 1) * step_ms
        latest_close_ms = latest_open_ms + step_ms - 1
        opened_at_ms = _iso_utc_ms(opened_at)
        if latest_close_ms < opened_at_ms:
            results.append({
                "symbol": symbol, "timeframe": timeframe, "strategy_version": strategy_version,
                "status": "WAITING_FOR_CLOSED_BAR", "reason_code": "NO_POST_OPEN_CLOSED_CANDLE",
                "paper_only": True, "live_trading_authority": False, "exposure_increased": False,
            })
            continue

        try:
            candles = fetcher(
                symbol,
                interval,
                now_ms=now_ms,
                start_time_ms=latest_open_ms,
                end_time_ms=latest_open_ms,
                limit=1,
                timeout_seconds=10.0,
            )
            if not isinstance(candles, list) or len(candles) != 1:
                raise ProductPaperProtectiveExitError("protective runner requires exactly one closed candle")
            outcome = evaluate_protective_exit(
                runtime=runtime,
                candle=candles[0],
                symbol=symbol,
                timeframe=timeframe,
                strategy_version=strategy_version,
                opened_at_utc=opened_at,
            )
            outcome["strategy_version"] = strategy_version
            outcome["position_side"] = side
            outcome["position_quantity_before"] = str(quantity)
            outcome["position_entry_price"] = str(entry)
            outcome["position_source_id"] = meta.get("source_id")
            outcome["position_provenance_kind"] = meta.get("kind")
            results.append(outcome)
        except Exception as exc:
            results.append({
                "symbol": symbol, "timeframe": timeframe, "strategy_version": strategy_version,
                "status": "BLOCKED", "reason_code": "VERIFIED_MARKET_DATA_UNAVAILABLE_OR_INVALID",
                "error_type": type(exc).__name__, "error": str(exc),
                "paper_only": True, "live_trading_authority": False, "exposure_increased": False,
            })

    return {
        "schema_version": SCHEMA,
        "status": "OK" if all(row.get("status") != "BLOCKED" for row in results) else "DEGRADED",
        "checked_at_utc": _utc_ms(now_ms),
        "position_count": len(positions),
        "results": results,
        "paper_only": True,
        "live_trading_authority": False,
        "exposure_increased": False,
        "automatic_live_promotion": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="NEXUS Product Paper protective Stop/Target guard")
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--opening-cash", default="500")
    parser.add_argument("--loop", action="store_true")
    parser.add_argument("--interval-seconds", type=int, default=60)
    args = parser.parse_args()
    if args.interval_seconds < 15:
        raise SystemExit("--interval-seconds must be at least 15")

    runtime = ProductRuntime(args.root, opening_cash=args.opening_cash)
    while True:
        result = run_once(runtime=runtime)
        print(json.dumps(result, sort_keys=True, ensure_ascii=False), flush=True)
        if not args.loop:
            return 0 if result["status"] == "OK" else 2
        time.sleep(args.interval_seconds)


if __name__ == "__main__":
    raise SystemExit(main())
