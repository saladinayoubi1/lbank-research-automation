"""Risk-reducing maintenance for persistent NEXUS Demo Paper positions.

This module never opens, adds to, reduces for leverage, reverses, promotes, or
routes Live orders. It consumes a verified Strategy Paper Supervisor ledger and
may only fully close an existing isolated Paper position when the latest verified
strategy target is flat or the current research qualification is no longer Paper
eligible. The close is authorized by the existing deterministic risk-reducing
exit gate and executed by the existing Paper simulator/accounting engine.
Performance projection is intentionally owned by the separate refresh pass.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Mapping

from nexus_demo_strategy_matrix import load_manifest
from nexus_strategy_paper_supervisor import verify_ledger
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

SCHEMA = "nexus.demo-paper-position-maintenance.v1"
CELL_SCHEMA = "nexus.demo-paper-position-maintenance-cell.v1"


class DemoPaperPositionMaintenanceError(RuntimeError):
    pass


def _canonical(value: Any) -> bytes:
    try:
        return json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise DemoPaperPositionMaintenanceError("maintenance evidence is not canonical JSON") from exc


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(dict(value), indent=2, sort_keys=True, ensure_ascii=False))
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def _position(state: Any, symbol: str) -> tuple[str, Any, Any] | None:
    for item_symbol, side, quantity, entry in state.positions:
        if item_symbol == symbol:
            return side, quantity, entry
    return None


def _exit_reason(research: Mapping[str, Any]) -> str | None:
    qualification = research.get("qualification", {})
    if not isinstance(qualification, Mapping) or qualification.get("status") != "paper_candidate":
        return "CURRENT_QUALIFICATION_NOT_PAPER_ELIGIBLE"
    target = research.get("latest_target")
    if isinstance(target, bool) or not isinstance(target, (int, float)):
        raise DemoPaperPositionMaintenanceError("latest strategy target is unavailable")
    if float(target) <= 0.0:
        return "LATEST_TARGET_FLAT"
    return None


def maintain_task_position(
    *,
    runtime: ProductRuntime,
    task: Mapping[str, Any],
) -> dict[str, Any]:
    """Hold or fully close one existing Paper position; never create exposure."""
    if not isinstance(runtime, ProductRuntime) or not isinstance(task, Mapping):
        raise DemoPaperPositionMaintenanceError("maintenance inputs are invalid")
    research = task.get("research_result")
    if not isinstance(research, Mapping):
        raise DemoPaperPositionMaintenanceError("task research evidence is missing")
    request = research.get("request")
    dataset = research.get("dataset")
    qualification = research.get("qualification")
    record = research.get("strategy_record")
    if not all(isinstance(value, Mapping) for value in (request, dataset, qualification, record)):
        raise DemoPaperPositionMaintenanceError("task lineage evidence is incomplete")
    symbol = str(request.get("symbol", "")).upper()
    timeframe = str(request.get("timeframe", ""))
    family = str(request.get("family", ""))
    if family != task.get("family") or timeframe not in TIMEFRAMES or not symbol:
        raise DemoPaperPositionMaintenanceError("task request identity mismatch")
    if record.get("family") != family or qualification.get("family") != family:
        raise DemoPaperPositionMaintenanceError("strategy family lineage mismatch")
    if dataset.get("binding_sha256") != qualification.get("dataset_binding_sha256"):
        raise DemoPaperPositionMaintenanceError("qualification dataset binding mismatch")

    with runtime._lock:
        events = runtime._ensure_account()
        state = replay(events).state
        current = _position(state, symbol)
        if current is None:
            core = {
                "schema_version": CELL_SCHEMA,
                "family": family,
                "symbol": symbol,
                "timeframe": timeframe,
                "status": "FLAT",
                "reason_code": "NO_EXISTING_POSITION",
                "event_count_added": 0,
                "paper_only": True,
                "live_trading_authority": False,
                "exposure_increased": False,
            }
            return {**core, "maintenance_digest": _digest(core)}

        reason = _exit_reason(research)
        if reason is None:
            core = {
                "schema_version": CELL_SCHEMA,
                "family": family,
                "symbol": symbol,
                "timeframe": timeframe,
                "status": "HELD",
                "reason_code": "LATEST_TARGET_REMAINS_ACTIVE",
                "event_count_added": 0,
                "paper_only": True,
                "live_trading_authority": False,
                "exposure_increased": False,
            }
            return {**core, "maintenance_digest": _digest(core)}

        side, quantity, _entry = current
        step_ms = int(TIMEFRAMES[timeframe]["step_ms"])
        last_open_ms = dataset.get("last_open_time_ms")
        if isinstance(last_open_ms, bool) or not isinstance(last_open_ms, int) or last_open_ms < 0:
            raise DemoPaperPositionMaintenanceError("dataset close boundary is invalid")
        source_ms = last_open_ms + step_ms
        occurred_at = _utc_ms(source_ms)
        reference_price = str(dataset.get("last_close", ""))
        try:
            if not reference_price or float(reference_price) <= 0:
                raise ValueError
        except (TypeError, ValueError):
            raise DemoPaperPositionMaintenanceError("maintenance reference price is invalid")

        binding = _digest({
            "account_id": state.aggregate_id,
            "head_event_digest": state.last_event_digest,
            "record_digest": record["record_digest"],
            "dataset_binding_sha256": dataset["binding_sha256"],
            "symbol": symbol,
            "timeframe": timeframe,
            "family": family,
            "quantity": str(quantity),
            "reference_price": reference_price,
            "reason_code": reason,
            "source_ms": source_ms,
        })
        signal_id = f"maintenance-exit-{binding[:40]}"
        correlation_id = f"maintenance-exit-{binding[:32]}"
        risk = _risk_reducing_exit(
            state=state,
            signal_id=signal_id,
            symbol=symbol,
            side=side,
            quantity=str(quantity),
            reference_price=reference_price,
        )
        if not risk.allowed:
            raise DemoPaperPositionMaintenanceError("deterministic risk-reducing exit gate rejected close")

        provenance = {
            "kind": "automatic",
            "source_id": "nexus-demo-position-maintenance",
            "source_timestamp": occurred_at,
            "received_timestamp": occurred_at,
            "timeframe": timeframe,
            "confidence": "1",
            "strategy_version": str(qualification.get("strategy_version", "unknown")),
            "policy_version": "nexus-product-paper-risk-v1",
        }
        signal_event = build_event(
            event_id=f"{signal_id}:signal",
            event_type="signal_recorded",
            aggregate_id=state.aggregate_id or "paper-account",
            sequence=state.last_sequence + 1,
            occurred_at=occurred_at,
            correlation_id=correlation_id,
            causation_id=f"maintenance:{binding[:40]}",
            provenance=provenance,
            previous_event_digest=state.last_event_digest,
            payload={
                "symbol": symbol,
                "timeframe": timeframe,
                "side": side,
                "quantity": str(quantity),
                "reference_price": reference_price,
            },
        )
        signal_state = replay([signal_event], previous_valid=state).state
        result = execute_paper_command(
            command={
                "operation": "close",
                "symbol": symbol,
                "side": side,
                "quantity": str(quantity),
                "reference_price": reference_price,
                "stop_price": reference_price,
                "target_price": reference_price,
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
            raise DemoPaperPositionMaintenanceError("risk-reducing close left residual exposure")
        runtime._write_events([*events, signal_event, *result.events])

    core = {
        "schema_version": CELL_SCHEMA,
        "family": family,
        "symbol": symbol,
        "timeframe": timeframe,
        "status": "CLOSED",
        "reason_code": reason,
        "event_count_added": 1 + len(result.events),
        "realized_pnl": str(result.realized_pnl),
        "risk_reason": risk.reason_code,
        "terminal_event_digest": result.state.last_event_digest,
        "paper_only": True,
        "live_trading_authority": False,
        "exposure_increased": False,
    }
    return {**core, "maintenance_digest": _digest(core)}


def run_position_maintenance(
    *,
    manifest: Mapping[str, Any],
    state_root: str | Path,
    source_sha: str,
) -> dict[str, Any]:
    root = Path(state_root).resolve()
    rows: list[dict[str, Any]] = []
    for symbol in manifest["symbols"]:
        for timeframe in manifest["timeframes"]:
            cell_root = root / "cells" / symbol.lower() / timeframe
            ledger_path = cell_root / "supervisor-ledger.json"
            if ledger_path.is_symlink() or not ledger_path.is_file():
                raise DemoPaperPositionMaintenanceError("verified Supervisor ledger is unavailable")
            ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
            verification = verify_ledger(ledger)
            if verification.get("decision") != "pass" or ledger.get("source_sha") != source_sha:
                raise DemoPaperPositionMaintenanceError("Supervisor ledger failed exact-source verification")
            cell_rows: list[dict[str, Any]] = []
            for task in ledger["tasks"]:
                family = str(task["family"])
                dataset = task.get("research_result", {}).get("dataset", {})
                last_open_ms = dataset.get("last_open_time_ms")
                if isinstance(last_open_ms, bool) or not isinstance(last_open_ms, int):
                    raise DemoPaperPositionMaintenanceError("task replay clock evidence is invalid")
                runtime = ProductRuntime(
                    cell_root / "portfolios" / family,
                    clock=lambda last_open_ms=last_open_ms, timeframe=timeframe: _utc_ms(
                        last_open_ms + int(TIMEFRAMES[timeframe]["step_ms"])
                    ),
                )
                result = maintain_task_position(runtime=runtime, task=task)
                cell_rows.append(result)
                rows.append(result)
            _atomic_json(cell_root / "analysis" / "paper-position-maintenance.json", {
                "schema_version": SCHEMA,
                "source_sha": source_sha,
                "symbol": symbol,
                "timeframe": timeframe,
                "rows": cell_rows,
                "paper_only": True,
                "live_trading_authority": False,
            })
    core = {
        "schema_version": SCHEMA,
        "source_sha": source_sha,
        "cell_count": len(manifest["symbols"]) * len(manifest["timeframes"]),
        "task_count": len(rows),
        "closed_count": sum(row["status"] == "CLOSED" for row in rows),
        "held_count": sum(row["status"] == "HELD" for row in rows),
        "flat_count": sum(row["status"] == "FLAT" for row in rows),
        "rows": rows,
        "paper_only": True,
        "live_trading_authority": False,
        "private_credentials_used": False,
        "automatic_strategy_promotion": False,
        "exposure_increased": False,
    }
    result = {**core, "maintenance_digest": _digest(core)}
    _atomic_json(root / "demo" / "paper-position-maintenance.json", result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--state-root", type=Path, required=True)
    parser.add_argument("--source-sha", required=True)
    args = parser.parse_args()
    manifest = load_manifest(args.manifest)
    result = run_position_maintenance(
        manifest=manifest,
        state_root=args.state_root,
        source_sha=str(args.source_sha).strip().lower(),
    )
    print(json.dumps({
        "closed_count": result["closed_count"],
        "held_count": result["held_count"],
        "flat_count": result["flat_count"],
        "maintenance_digest": result["maintenance_digest"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
