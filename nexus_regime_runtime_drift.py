"""Bind verified regime runtime evidence to Paper performance drift.

This bridge is a read-only control projection. It can recommend a WATCH haircut,
removal, or cash preservation for the next selector cycle, but it cannot mutate
the current runtime, promote a strategy, execute an order, or grant Live authority.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Mapping

from nexus_paper_performance_pipeline import SCHEMA as PERFORMANCE_SCHEMA
from nexus_regime_strategy_runtime import verify_runtime_evidence
from nexus_strategy_paper_supervisor import verify_ledger


SCHEMA = "nexus.regime-runtime-drift.v1"
_PERFORMANCE_KEYS = {
    "contract_version", "supervisor_verification_digest", "paper_only",
    "live_trading_authority", "strategy_count", "status_counts", "strategies",
    "projection_digest",
}
_ALLOWED_STATUS = {"HEALTHY", "WATCH", "DEGRADED", "QUARANTINED", "INSUFFICIENT_EVIDENCE"}


class RegimeRuntimeDriftError(RuntimeError):
    pass


def _canonical(value: Any) -> bytes:
    try:
        return json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise RegimeRuntimeDriftError("regime drift evidence is not canonical JSON") from exc


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _validate_performance_projection(
    projection: Any, supervisor_verification_digest: str
) -> list[dict[str, Any]]:
    if not isinstance(projection, Mapping) or set(projection) != _PERFORMANCE_KEYS:
        raise RegimeRuntimeDriftError("Paper performance projection schema mismatch")
    core = dict(projection)
    claimed = core.pop("projection_digest", None)
    if (
        core.get("contract_version") != PERFORMANCE_SCHEMA
        or core.get("paper_only") is not True
        or core.get("live_trading_authority") is not False
        or core.get("supervisor_verification_digest") != supervisor_verification_digest
        or claimed != _digest(core)
    ):
        raise RegimeRuntimeDriftError("Paper performance projection verification failed")
    strategies = core.get("strategies")
    if (
        not isinstance(strategies, list)
        or core.get("strategy_count") != len(strategies)
        or len(strategies) > 32
        or not all(isinstance(row, Mapping) for row in strategies)
    ):
        raise RegimeRuntimeDriftError("Paper performance strategies are invalid")
    return [dict(row) for row in strategies]


def build_regime_runtime_drift(
    *,
    supervisor_ledger: Mapping[str, Any],
    performance_projection: Mapping[str, Any],
    runtime_evidence: Mapping[str, Any],
) -> dict[str, Any]:
    """Return a digest-bound next-cycle drift control projection."""
    supervisor_verification = verify_ledger(supervisor_ledger)
    if supervisor_verification.get("decision") != "pass":
        raise RegimeRuntimeDriftError("Supervisor ledger is not independently verified")
    runtime_verification = verify_runtime_evidence(runtime_evidence)
    if runtime_verification.get("decision") != "pass":
        raise RegimeRuntimeDriftError("regime runtime evidence is not independently verified")
    source_sha = supervisor_ledger.get("source_sha")
    if runtime_evidence.get("source_sha") != source_sha:
        raise RegimeRuntimeDriftError("runtime and Supervisor source SHA mismatch")
    strategies = _validate_performance_projection(
        performance_projection, str(supervisor_verification.get("verification_digest", ""))
    )
    by_family: dict[str, dict[str, Any]] = {}
    for row in strategies:
        family = row.get("family")
        status = row.get("status")
        if (
            not isinstance(family, str)
            or not family
            or family in by_family
            or status not in _ALLOWED_STATUS
        ):
            raise RegimeRuntimeDriftError("performance family or status is invalid")
        by_family[family] = row

    allocations = runtime_evidence.get("selection", {}).get("allocations", [])
    if not isinstance(allocations, list):
        raise RegimeRuntimeDriftError("runtime allocations are invalid")
    controls: list[dict[str, Any]] = []
    selected: list[dict[str, Any]] = []
    for allocation in allocations:
        if not isinstance(allocation, Mapping):
            raise RegimeRuntimeDriftError("runtime allocation row is invalid")
        family = allocation.get("family")
        monitor = by_family.get(str(family))
        if monitor is None:
            raise RegimeRuntimeDriftError("selected family lacks performance evidence")
        status = monitor["status"]
        action = "KEEP"
        reason = "PERFORMANCE_HEALTHY"
        if status == "WATCH":
            action = "WATCH_HAIRCUT_NEXT_CYCLE"
            reason = "PERFORMANCE_WATCH"
        elif status in {"DEGRADED", "QUARANTINED"}:
            action = "REMOVE_FROM_NEXT_SELECTION"
            reason = f"PERFORMANCE_{status}"
        elif status == "INSUFFICIENT_EVIDENCE":
            action = "PRESERVE_CURRENT_POLICY_BOUND"
            reason = "PERFORMANCE_SAMPLE_INSUFFICIENT"
        row = {
            "family": family,
            "strategy_id": allocation.get("strategy_id"),
            "runtime_weight": allocation.get("weight"),
            "performance_status": status,
            "monitor_digest": monitor.get("monitor_digest"),
            "next_cycle_action": action,
            "reason_code": reason,
        }
        selected.append(row)
        if action != "KEEP":
            controls.append(dict(row))

    core = {
        "schema_version": SCHEMA,
        "source_sha": source_sha,
        "supervisor_verification_digest": supervisor_verification["verification_digest"],
        "performance_projection_digest": performance_projection["projection_digest"],
        "runtime_digest": runtime_evidence["runtime_digest"],
        "runtime_verification_digest": runtime_verification["verification_digest"],
        "selection_digest": runtime_evidence["selection_digest"],
        "alignment": runtime_evidence["selection"]["alignment"],
        "cash_weight": runtime_evidence["cash_weight"],
        "drift_state": "ACTION_REQUIRED" if controls else "STABLE",
        "selected_strategies": selected,
        "next_cycle_controls": controls,
        "current_runtime_mutated": False,
        "paper_only": True,
        "live_trading_authority": False,
        "promotion_authority": False,
    }
    return {**core, "drift_digest": _digest(core)}


def persist_regime_runtime_drift(projection: Mapping[str, Any], state_root: Path) -> Path:
    """Persist one immutable projection under its verified drift digest."""
    if not isinstance(projection, Mapping):
        raise RegimeRuntimeDriftError("regime drift projection must be an object")
    core = dict(projection)
    claimed = core.pop("drift_digest", None)
    if (
        core.get("schema_version") != SCHEMA
        or core.get("paper_only") is not True
        or core.get("live_trading_authority") is not False
        or core.get("promotion_authority") is not False
        or claimed != _digest(core)
    ):
        raise RegimeRuntimeDriftError("regime drift projection verification failed")
    root = Path(state_root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    target = root / f"{claimed}.json"
    payload = json.dumps(
        dict(projection), indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False
    ).encode("utf-8") + b"\n"
    try:
        descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        if target.is_symlink() or not target.is_file() or target.read_bytes() != payload:
            raise RegimeRuntimeDriftError("append-only regime drift evidence collision")
        return target
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        target.unlink(missing_ok=True)
        raise
    return target
