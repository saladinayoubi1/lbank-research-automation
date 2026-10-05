"""Bounded closed-candle loop for Product Paper protective exits.

The loop is Paper-only. It discovers the active position's own timeframe and
strategy provenance from the event journal, replays only full closed Bybit
candles after the position opened, and delegates all close authority to the
risk-reducing protective-exit guard.

No Live credentials, private endpoints, exposure increases, reverse operations,
or automatic strategy promotions exist in this module.
"""
from __future__ import annotations

import argparse
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

from bybit_public_klines import INTERVAL_MS, fetch_closed_klines
from nexus_product_paper_protective_exit import evaluate_protective_exit
from paper_event_store import replay
from product_runtime import ProductRuntime

SCHEMA = "nexus.product-paper-protective-exit-loop.v1"
CURSOR_SCHEMA = "nexus.product-paper-protective-exit-cursor.v1"
_TIMEFRAME_TO_INTERVAL = {"minute15": "15", "hour1": "60", "hour4": "240"}


class ProductPaperProtectiveExitLoopError(RuntimeError):
    pass


def _utc_ms(value: str) -> int:
    if not isinstance(value, str) or not value:
        raise ProductPaperProtectiveExitLoopError("position open timestamp is unavailable")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ProductPaperProtectiveExitLoopError("position open timestamp is invalid") from exc
    if parsed.tzinfo is None:
        raise ProductPaperProtectiveExitLoopError("position open timestamp must include timezone")
    return int(parsed.astimezone(timezone.utc).timestamp() * 1000)


def _active_metadata(events: list[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    active: dict[str, dict[str, Any]] = {}
    for event in events:
        payload = event.get("payload", {})
        symbol = payload.get("symbol") if isinstance(payload, Mapping) else None
        if not isinstance(symbol, str) or not symbol:
            continue
        kind = event.get("event_type")
        if kind in {"position_opened", "position_reversed"}:
            provenance = event.get("provenance", {})
            if not isinstance(provenance, Mapping):
                provenance = {}
            active[symbol] = {
                "position_event_digest": event.get("event_digest"),
                "opened_at": event.get("occurred_at"),
                "timeframe": provenance.get("timeframe"),
                "strategy_version": provenance.get("strategy_version"),
                "provenance_kind": provenance.get("kind"),
                "source_id": provenance.get("source_id"),
            }
        elif kind == "position_closed":
            active.pop(symbol, None)
    return active


def _load_cursor(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"schema_version": CURSOR_SCHEMA, "positions": {}}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ProductPaperProtectiveExitLoopError("protective-exit cursor is unreadable") from exc
    if not isinstance(value, dict) or value.get("schema_version") != CURSOR_SCHEMA:
        raise ProductPaperProtectiveExitLoopError("protective-exit cursor schema mismatch")
    positions = value.get("positions")
    if not isinstance(positions, dict):
        raise ProductPaperProtectiveExitLoopError("protective-exit cursor positions are invalid")
    return value


def _atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(dict(value), handle, indent=2, sort_keys=True, ensure_ascii=False)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)


def run_cycle(
    *,
    root: str | Path,
    cursor_path: str | Path,
    now_ms: int | None = None,
    fetcher: Callable[..., list[dict[str, Any]]] = fetch_closed_klines,
) -> dict[str, Any]:
    root = Path(root).resolve()
    cursor_path = Path(cursor_path).resolve()
    current_ms = int(time.time() * 1000) if now_ms is None else now_ms
    if isinstance(current_ms, bool) or not isinstance(current_ms, int) or current_ms <= 0:
        raise ProductPaperProtectiveExitLoopError("loop clock is invalid")

    runtime = ProductRuntime(root, opening_cash="500")
    with runtime._lock:
        events = runtime._ensure_account()
        state = replay(events).state
        positions = list(state.positions)
        metadata = _active_metadata(events)

    cursor = _load_cursor(cursor_path)
    position_cursor = cursor["positions"]
    results: list[dict[str, Any]] = []

    if not positions:
        snapshot = {
            "schema_version": SCHEMA, "status": "FLAT", "checked_position_count": 0,
            "results": [], "paper_only": True, "live_trading_authority": False,
            "exposure_increased": False,
        }
        _atomic_json(cursor_path, cursor)
        return snapshot

    for symbol, side, quantity, entry in positions:
        meta = metadata.get(symbol)
        if not isinstance(meta, Mapping):
            raise ProductPaperProtectiveExitLoopError(f"active position provenance missing for {symbol}")
        timeframe = meta.get("timeframe")
        strategy_version = meta.get("strategy_version")
        position_digest = meta.get("position_event_digest")
        if timeframe not in _TIMEFRAME_TO_INTERVAL:
            raise ProductPaperProtectiveExitLoopError(f"unsupported active timeframe for {symbol}")
        if not isinstance(strategy_version, str) or not strategy_version:
            raise ProductPaperProtectiveExitLoopError(f"strategy version missing for {symbol}")
        if not isinstance(position_digest, str) or len(position_digest) != 64:
            raise ProductPaperProtectiveExitLoopError(f"position event digest missing for {symbol}")

        interval = _TIMEFRAME_TO_INTERVAL[timeframe]
        step_ms = INTERVAL_MS[interval]
        opened_ms = _utc_ms(str(meta.get("opened_at")))
        # Do not use the partial candle that was already in progress at execution.
        first_full_open = ((opened_ms + step_ms - 1) // step_ms) * step_ms
        last_closed_open = (current_ms // step_ms - 1) * step_ms

        saved = position_cursor.get(symbol, {})
        if isinstance(saved, Mapping) and saved.get("position_event_digest") == position_digest:
            last_seen_open = saved.get("last_open_time_ms")
            if isinstance(last_seen_open, int) and not isinstance(last_seen_open, bool):
                first_full_open = max(first_full_open, last_seen_open + step_ms)

        if first_full_open > last_closed_open:
            results.append({
                "symbol": symbol, "timeframe": timeframe, "status": "WAITING_FOR_FULL_CLOSED_CANDLE",
                "position_event_digest": position_digest, "paper_only": True,
                "live_trading_authority": False, "exposure_increased": False,
            })
            continue

        count = ((last_closed_open - first_full_open) // step_ms) + 1
        if count < 1 or count > 1000:
            raise ProductPaperProtectiveExitLoopError(
                f"closed-candle replay window outside bounded limit for {symbol}"
            )
        candles = fetcher(
            symbol, interval, now_ms=current_ms, start_time_ms=first_full_open,
            end_time_ms=last_closed_open, limit=count, timeout_seconds=15.0,
        )
        if len(candles) != count:
            raise ProductPaperProtectiveExitLoopError(f"closed-candle replay incomplete for {symbol}")

        expected_open = first_full_open
        for candle in candles:
            if candle.get("open_time_ms") != expected_open:
                raise ProductPaperProtectiveExitLoopError(f"closed-candle replay discontinuity for {symbol}")
            result = evaluate_protective_exit(
                runtime=runtime, candle=candle, symbol=symbol, timeframe=timeframe,
                strategy_version=strategy_version, opened_at_utc=str(meta.get("opened_at")),
            )
            position_cursor[symbol] = {
                "position_event_digest": position_digest,
                "last_open_time_ms": expected_open,
                "last_close_time_ms": candle.get("close_time_ms"),
                "last_status": result["status"],
            }
            results.append({
                "symbol": symbol, "timeframe": timeframe, "strategy_version": strategy_version,
                "candle_open_time_ms": expected_open, **result,
            })
            expected_open += step_ms
            if result["status"] == "CLOSED":
                break

    cursor["positions"] = position_cursor
    _atomic_json(cursor_path, cursor)
    return {
        "schema_version": SCHEMA,
        "status": "CLOSED" if any(row.get("status") == "CLOSED" for row in results) else "ACTIVE",
        "checked_position_count": len(positions),
        "results": results,
        "paper_only": True,
        "live_trading_authority": False,
        "exposure_increased": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="NEXUS Product Paper protective-exit loop")
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--cursor", type=Path, required=True)
    parser.add_argument("--status-out", type=Path)
    parser.add_argument("--loop", action="store_true")
    parser.add_argument("--sleep-seconds", type=int, default=60)
    args = parser.parse_args()
    if args.sleep_seconds < 30 or args.sleep_seconds > 3600:
        raise ProductPaperProtectiveExitLoopError("sleep interval outside bounded range")

    while True:
        try:
            result = run_cycle(root=args.root, cursor_path=args.cursor)
            if args.status_out:
                _atomic_json(args.status_out.resolve(), result)
            print(json.dumps(result, sort_keys=True), flush=True)
        except Exception as exc:
            failure = {
                "schema_version": SCHEMA, "status": "FAILED_CLOSED",
                "reason": f"{type(exc).__name__}: {exc}",
                "paper_only": True, "live_trading_authority": False,
                "exposure_increased": False,
            }
            if args.status_out:
                _atomic_json(args.status_out.resolve(), failure)
            print(json.dumps(failure, sort_keys=True), flush=True)
            if not args.loop:
                raise
        if not args.loop:
            return 0
        time.sleep(args.sleep_seconds)


if __name__ == "__main__":
    raise SystemExit(main())
