"""Closed Paper trade projection into the NEXUS performance read model."""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Mapping, Sequence

from nexus_paper_performance_drift import evaluate_paper_drift
from nexus_strategy_paper_supervisor import verify_ledger
from paper_event_store import replay, validate_event

SCHEMA = "nexus.mission-control.paper-performance.v1"


class PaperPerformancePipelineError(RuntimeError):
    pass


def _canonical(value: Any) -> bytes:
    try:
        return json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise PaperPerformancePipelineError("Paper projection is not canonical JSON") from exc


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _decimal_text(value: Decimal) -> str:
    return format(value, "f")


def _epoch_ms(value: str) -> int:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise PaperPerformancePipelineError("Paper event timestamp is not UTC")
    return int(parsed.timestamp() * 1000)


def extract_closed_paper_trades(events: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Reconstruct complete closed trades from one validated Paper event journal."""
    if not isinstance(events, Sequence) or isinstance(events, (str, bytes)):
        raise PaperPerformancePipelineError("Paper journal must be a sequence")
    try:
        validated = [validate_event(dict(event)) for event in events]
        replay(validated)
    except (TypeError, ValueError) as exc:
        raise PaperPerformancePipelineError(f"Paper journal failed replay: {exc}") from exc

    charges: dict[str, Decimal] = {}
    for event in validated:
        if event["event_type"] in {"fee_recorded", "slippage_recorded"}:
            correlation = event["correlation_id"]
            charges[correlation] = charges.get(correlation, Decimal("0")) + Decimal(
                event["payload"]["amount"]
            )

    open_positions: dict[str, dict[str, Any]] = {}
    trades: list[dict[str, Any]] = []
    for event in validated:
        kind = event["event_type"]
        payload = event["payload"]
        if kind in {"position_reduced", "position_reversed"}:
            raise PaperPerformancePipelineError(
                "partial reductions and reversals require a separate attribution contract"
            )
        if kind == "position_opened":
            symbol = payload["symbol"]
            if symbol in open_positions:
                raise PaperPerformancePipelineError("overlapping Paper position history")
            open_positions[symbol] = {
                "event": event,
                "side": payload["side"],
                "quantity": Decimal(payload["quantity"]),
                "entry_price": Decimal(payload["entry_price"]),
                "open_cost": charges.get(event["correlation_id"], Decimal("0")),
            }
        elif kind == "position_closed":
            symbol = payload["symbol"]
            opened = open_positions.pop(symbol, None)
            if opened is None:
                raise PaperPerformancePipelineError("Paper close has no matching open")
            quantity = opened["quantity"]
            exit_price = Decimal(payload["exit_price"])
            total_cost = opened["open_cost"] + charges.get(
                event["correlation_id"], Decimal("0")
            )
            trade_id = _digest({
                "aggregate_id": event["aggregate_id"],
                "symbol": symbol,
                "open_event": opened["event"]["event_digest"],
                "close_event": event["event_digest"],
            })
            trades.append({
                "trade_id": trade_id,
                "opened_at_ms": _epoch_ms(opened["event"]["occurred_at"]),
                "closed_at_ms": _epoch_ms(event["occurred_at"]),
                "gross_pnl": payload["realized_pnl"],
                "fees": _decimal_text(total_cost),
                "entry_notional": _decimal_text(quantity * opened["entry_price"]),
                "exit_notional": _decimal_text(quantity * exit_price),
                "regime": "UNKNOWN",
            })
    return trades


def build_paper_performance_projection(
    *,
    supervisor_ledger: Mapping[str, Any],
    journals_by_family: Mapping[str, Sequence[Mapping[str, Any]]],
    baselines_by_family: Mapping[str, Mapping[str, Any]],
    initial_equity: Any = "10000",
) -> dict[str, Any]:
    """Project verified multi-strategy Paper health into Mission Control."""
    verification = verify_ledger(supervisor_ledger)
    if verification["decision"] != "pass":
        raise PaperPerformancePipelineError("Supervisor ledger is not verified")
    if not isinstance(journals_by_family, Mapping) or not isinstance(baselines_by_family, Mapping):
        raise PaperPerformancePipelineError("Paper journals and baselines must be mappings")

    strategies: list[dict[str, Any]] = []
    for task in supervisor_ledger["tasks"]:
        if task["status"] not in {"paper_executed", "position_exists"}:
            continue
        family = task["family"]
        if family not in journals_by_family or family not in baselines_by_family:
            raise PaperPerformancePipelineError(f"missing Paper inputs for {family}")
        baseline = baselines_by_family[family]
        if not isinstance(baseline, Mapping) or set(baseline) != {
            "expectancy", "fee_per_trade"
        }:
            raise PaperPerformancePipelineError(f"invalid baseline for {family}")
        trades = extract_closed_paper_trades(journals_by_family[family])
        monitor = evaluate_paper_drift(
            supervisor_ledger=supervisor_ledger,
            task_id=task["task_id"],
            closed_trades=trades,
            baseline_expectancy=baseline["expectancy"],
            baseline_fee_per_trade=baseline["fee_per_trade"],
            initial_equity=initial_equity,
        )
        analytics = monitor.get("analytics", {})
        strategies.append({
            "family": family,
            "strategy_id": monitor["strategy_id"],
            "status": monitor["status"],
            "lifecycle_state": monitor["lifecycle_state"],
            "closed_trade_count": monitor["closed_trade_count"],
            "expectancy": analytics.get("expectancy"),
            "max_drawdown_pct": analytics.get("max_drawdown_pct"),
            "net_pnl": analytics.get("net_pnl"),
            "monitor_digest": monitor["monitor_digest"],
        })

    counts: dict[str, int] = {}
    for row in strategies:
        counts[row["status"]] = counts.get(row["status"], 0) + 1
    core = {
        "contract_version": SCHEMA,
        "supervisor_verification_digest": verification["verification_digest"],
        "paper_only": True,
        "live_trading_authority": False,
        "strategy_count": len(strategies),
        "status_counts": dict(sorted(counts.items())),
        "strategies": sorted(strategies, key=lambda row: row["family"]),
    }
    return {**core, "projection_digest": _digest(core)}


def save_paper_performance_projection(path: str | Path, projection: Mapping[str, Any]) -> None:
    core = dict(projection)
    claimed = core.pop("projection_digest", None)
    if (
        core.get("contract_version") != SCHEMA
        or core.get("paper_only") is not True
        or core.get("live_trading_authority") is not False
        or claimed != _digest(core)
    ):
        raise PaperPerformancePipelineError("Mission Control Paper projection is invalid")
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".tmp")
    try:
        temporary.write_text(
            json.dumps(dict(projection), sort_keys=True, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, target)
    except OSError as exc:
        raise PaperPerformancePipelineError("Paper projection commit failed") from exc
