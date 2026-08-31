"""Fail-closed bridge from verified Paper-loop health to bounded Strategy Discovery.

This module does not dispatch workflows itself. It verifies one persistent Paper-loop
snapshot and produces a digest-bound decision telling the separately permissioned
Strategy Discovery rotation whether a health-driven dispatch is justified. Daily
rotation remains independent so CASH/NO_ACTION cannot stop research.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from nexus_persistent_paper_trading_loop import verify_loop_snapshot


SCHEMA = "nexus.strategy-discovery-health-trigger.v1"


class StrategyDiscoveryHealthTriggerError(RuntimeError):
    pass


def _canonical(value: Any) -> bytes:
    try:
        return json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise StrategyDiscoveryHealthTriggerError("trigger evidence is not canonical JSON") from exc


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def build_health_trigger(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(snapshot, Mapping):
        raise StrategyDiscoveryHealthTriggerError("Paper-loop snapshot must be an object")
    verification = verify_loop_snapshot(snapshot)
    if verification.get("decision") != "pass":
        raise StrategyDiscoveryHealthTriggerError("Paper-loop snapshot failed independent verification")
    if (
        snapshot.get("paper_only") is not True
        or snapshot.get("live_trading_authority") is not False
        or snapshot.get("private_credentials_used") is not False
        or snapshot.get("automatic_strategy_promotion") is not False
        or snapshot.get("deterministic_risk_final_authority") is not True
    ):
        raise StrategyDiscoveryHealthTriggerError("Paper-loop authority boundary is invalid")

    active = snapshot.get("status") == "PAPER_LOOP_ACTIVE"
    new_boundary = snapshot.get("regime_status") == "VERIFIED"
    research_required = snapshot.get("strategy_research_required") is True
    controller_verified = snapshot.get("strategy_discovery_controller_verified") is True
    lifecycle_ready = snapshot.get("regime_selected_rebalance_operational") is True

    should_dispatch = bool(
        active and new_boundary and research_required and controller_verified and lifecycle_ready
    )
    if should_dispatch:
        reason = "NEW_4H_BOUNDARY_RESEARCH_REQUIRED"
    elif not active:
        reason = "PAPER_LOOP_NOT_ACTIVE"
    elif not new_boundary:
        reason = "NO_NEW_4H_BOUNDARY"
    elif not research_required:
        reason = "CURRENT_RESEARCH_HEALTH_SUFFICIENT"
    elif not controller_verified:
        reason = "DISCOVERY_CONTROLLER_NOT_VERIFIED"
    else:
        reason = "REGIME_LIFECYCLE_NOT_READY"

    core = {
        "schema_version": SCHEMA,
        "source_sha": snapshot.get("source_sha"),
        "run_id": snapshot.get("run_id"),
        "loop_digest": snapshot.get("loop_digest"),
        "should_dispatch": should_dispatch,
        "reason_code": reason,
        "trigger_scope": "new_verified_4h_boundary_only",
        "daily_rotation_remains_required": True,
        "research_only": True,
        "paper_only": True,
        "live_trading_authority": False,
        "qualification_authority": False,
        "automatic_strategy_promotion": False,
    }
    return {**core, "trigger_digest": _digest(core)}


def verify_health_trigger(value: Mapping[str, Any]) -> dict[str, Any]:
    checks = {
        "schema": False,
        "digest": False,
        "authority": False,
        "shape": False,
    }
    try:
        core = dict(value)
        claimed = core.pop("trigger_digest", None)
        checks["schema"] = core.get("schema_version") == SCHEMA
        checks["digest"] = isinstance(claimed, str) and claimed == _digest(core)
        checks["authority"] = bool(
            core.get("research_only") is True
            and core.get("paper_only") is True
            and core.get("live_trading_authority") is False
            and core.get("qualification_authority") is False
            and core.get("automatic_strategy_promotion") is False
            and core.get("daily_rotation_remains_required") is True
        )
        checks["shape"] = bool(
            isinstance(core.get("should_dispatch"), bool)
            and isinstance(core.get("reason_code"), str)
            and bool(core.get("reason_code"))
            and core.get("trigger_scope") == "new_verified_4h_boundary_only"
        )
    except (TypeError, ValueError):
        pass
    return {"decision": "pass" if all(checks.values()) else "reject", "checks": checks}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--loop-snapshot", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        snapshot = json.loads(args.loop_snapshot.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise StrategyDiscoveryHealthTriggerError("Paper-loop snapshot is unavailable") from exc
    decision = build_health_trigger(snapshot)
    if verify_health_trigger(decision).get("decision") != "pass":
        raise StrategyDiscoveryHealthTriggerError("health trigger failed verification")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(decision, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(decision, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

# Semantic no-op: exact-main physical Paper proof trigger after coordinator durability fix.
