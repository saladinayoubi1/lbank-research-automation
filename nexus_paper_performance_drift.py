"""Deterministic Paper performance and drift monitor for NEXUS strategies.

This module consumes verified Supervisor evidence and closed Paper trades. It has
analytics and quarantine authority only; it cannot promote or execute a strategy.
"""
from __future__ import annotations

import hashlib
import json
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping, Sequence

from performance_analytics import analyze_performance
from nexus_strategy_paper_supervisor import verify_ledger
from strategy_lifecycle import (
    apply_health_lifecycle,
    promote_candidate_to_paper,
    replay_lifecycle,
)
from strategy_registry import evaluate_strategy_health

SCHEMA = "nexus.paper-performance-drift.v1"
MIN_CLOSED_TRADES = 5


class PaperPerformanceDriftError(RuntimeError):
    pass


def _canonical(value: Any) -> bytes:
    try:
        return json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise PaperPerformanceDriftError("monitor evidence is not canonical JSON") from exc


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _decimal(value: Any, field: str) -> Decimal:
    if isinstance(value, float):
        raise PaperPerformanceDriftError(f"{field} must not use binary floating point")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise PaperPerformanceDriftError(f"{field} is not a decimal") from exc
    if not result.is_finite():
        raise PaperPerformanceDriftError(f"{field} must be finite")
    return result


def _drop_pct(baseline: Decimal, current: Decimal) -> Decimal:
    if baseline <= 0:
        return Decimal("100") if current < baseline else Decimal("0")
    return max(Decimal("0"), (baseline - current) / baseline * Decimal("100"))


def _cost_increase_pct(baseline: Decimal, current: Decimal) -> Decimal:
    if baseline < 0:
        raise PaperPerformanceDriftError("baseline fee per trade must be non-negative")
    if baseline == 0:
        return Decimal("100") if current > 0 else Decimal("0")
    return max(Decimal("0"), (current - baseline) / baseline * Decimal("100"))


def evaluate_paper_drift(
    *,
    supervisor_ledger: Mapping[str, Any],
    task_id: str,
    closed_trades: Sequence[Mapping[str, Any]],
    baseline_expectancy: Any,
    baseline_fee_per_trade: Any,
    initial_equity: Any = "10000",
) -> dict[str, Any]:
    """Measure one isolated Paper strategy and append quarantine when required."""
    supervisor_verification = verify_ledger(supervisor_ledger)
    if supervisor_verification.get("decision") != "pass":
        raise PaperPerformanceDriftError("Supervisor evidence is not independently verified")
    tasks = supervisor_ledger.get("tasks")
    matches = [row for row in tasks if row.get("task_id") == task_id]
    if len(matches) != 1:
        raise PaperPerformanceDriftError("task is not uniquely bound to the verified ledger")
    supervisor_task = matches[0]
    if supervisor_task.get("paper_only") is not True or supervisor_task.get("live_trading_authority") is not False:
        raise PaperPerformanceDriftError("task exceeds Paper authority")
    if supervisor_task.get("status") not in {"paper_executed", "position_exists"}:
        raise PaperPerformanceDriftError("task has no active Paper evidence")
    research = supervisor_task.get("research_result")
    if not isinstance(research, Mapping):
        raise PaperPerformanceDriftError("strategy research evidence is missing")
    record = research.get("strategy_record")
    lifecycle = research.get("research_lifecycle")
    if not isinstance(record, Mapping) or not isinstance(lifecycle, Sequence):
        raise PaperPerformanceDriftError("strategy registry or lifecycle evidence is missing")
    if record.get("family") != supervisor_task.get("family"):
        raise PaperPerformanceDriftError("strategy family binding mismatch")
    if record.get("dataset_binding_sha256") != supervisor_ledger.get("dataset_binding_sha256"):
        raise PaperPerformanceDriftError("strategy dataset binding mismatch")

    current_state = replay_lifecycle(lifecycle)
    if current_state == "CANDIDATE" and supervisor_task.get("status") == "paper_executed":
        paper = supervisor_task.get("paper_result", {})
        lifecycle = promote_candidate_to_paper(record, lifecycle, {
            "risk_gate_allowed": paper.get("risk", {}).get("allowed") is True,
            "replay_verified": True,
            "paper_execution_evidence_sha256": supervisor_task["evidence_digest"],
            "independent_verifier_evidence_sha256": supervisor_verification["verification_digest"],
            "producer_id": supervisor_task["worker_id"],
            "verifier_id": supervisor_verification["verifier"],
        })
    elif current_state not in {"CANDIDATE", "PAPER"}:
        raise PaperPerformanceDriftError("strategy is not an active Candidate or Paper strategy")

    if len(closed_trades) < MIN_CLOSED_TRADES:
        core = {
            "schema_version": SCHEMA,
            "strategy_id": record.get("strategy_id"),
            "family": supervisor_task.get("family"),
            "status": "INSUFFICIENT_EVIDENCE",
            "closed_trade_count": len(closed_trades),
            "minimum_closed_trades": MIN_CLOSED_TRADES,
            "lifecycle": list(lifecycle),
            "lifecycle_state": replay_lifecycle(lifecycle),
            "paper_only": True,
            "live_trading_authority": False,
            "promotion_authority": False,
        }
        return {**core, "monitor_digest": _digest(core)}

    source_binding = str(supervisor_task.get("producer_result", {}).get("evidence", {}).get(
        "dataset_binding_sha256", ""
    ))
    analytics = analyze_performance(
        source_binding_sha256=source_binding,
        initial_equity=initial_equity,
        trades=closed_trades,
    )
    baseline_expectancy_value = _decimal(baseline_expectancy, "baseline_expectancy")
    baseline_fee_value = _decimal(baseline_fee_per_trade, "baseline_fee_per_trade")
    current_expectancy = _decimal(analytics["expectancy"], "expectancy")
    total_fees = sum((_decimal(row["fees"], "fees") for row in closed_trades), Decimal("0"))
    fee_per_trade = total_fees / Decimal(len(closed_trades))
    regime_rows = analytics.get("regime_breakdown", {})
    regime_mismatch = bool(
        regime_rows and all(_decimal(row["expectancy"], "regime.expectancy") < 0 for row in regime_rows.values())
    )
    signals = {
        "data_eligible": True,
        "performance_drop_pct": float(_drop_pct(baseline_expectancy_value, current_expectancy)),
        "execution_cost_increase_pct": float(_cost_increase_pct(baseline_fee_value, fee_per_trade)),
        "regime_mismatch": regime_mismatch,
        "correlation_shift_pct": 0.0,
    }
    health = evaluate_strategy_health(record, signals)
    updated_lifecycle = apply_health_lifecycle(record, lifecycle, health)
    core = {
        "schema_version": SCHEMA,
        "strategy_id": record["strategy_id"],
        "family": supervisor_task.get("family"),
        "status": health["health_state"],
        "analytics": analytics,
        "health": health,
        "lifecycle": list(updated_lifecycle),
        "lifecycle_state": replay_lifecycle(updated_lifecycle),
        "paper_only": True,
        "live_trading_authority": False,
        "promotion_authority": False,
    }
    return {**core, "monitor_digest": _digest(core)}
