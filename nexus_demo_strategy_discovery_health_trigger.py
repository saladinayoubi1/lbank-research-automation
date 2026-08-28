"""Fail-closed Demo lifecycle bridge to bounded Strategy Discovery.

The immutable Bybit Demo matrix is a proof/runtime lane that can keep the trading
engine progressing while prospective public Bybit networking is unavailable.  This
module independently verifies the synchronized regime cycle and completed lifecycle,
then emits only a research-dispatch recommendation.  It cannot qualify, promote, or
execute a strategy.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Mapping

from nexus_demo_regime_cycle import verify_cycle_snapshot
from nexus_demo_regime_lifecycle_bridge import verify_demo_regime_lifecycle


SCHEMA = "nexus.demo-strategy-discovery-health-trigger.v1"


class DemoStrategyDiscoveryHealthTriggerError(RuntimeError):
    pass


def _canonical(value: Any) -> bytes:
    try:
        return json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise DemoStrategyDiscoveryHealthTriggerError("trigger evidence is not canonical JSON") from exc


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _cash_weight(value: Any) -> Decimal:
    if isinstance(value, bool):
        raise DemoStrategyDiscoveryHealthTriggerError("cash weight is invalid")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise DemoStrategyDiscoveryHealthTriggerError("cash weight is invalid") from exc
    if not result.is_finite() or result < 0 or result > 1:
        raise DemoStrategyDiscoveryHealthTriggerError("cash weight is outside [0, 1]")
    return result


def build_demo_health_trigger(
    regime_snapshot: Mapping[str, Any], lifecycle_snapshot: Mapping[str, Any]
) -> dict[str, Any]:
    if verify_cycle_snapshot(regime_snapshot).get("decision") != "pass":
        raise DemoStrategyDiscoveryHealthTriggerError("Demo regime cycle failed verification")
    if verify_demo_regime_lifecycle(lifecycle_snapshot).get("decision") != "pass":
        raise DemoStrategyDiscoveryHealthTriggerError("Demo lifecycle failed verification")
    if (
        regime_snapshot.get("source_sha") != lifecycle_snapshot.get("source_sha")
        or regime_snapshot.get("cycle_digest") != lifecycle_snapshot.get("regime_cycle_digest")
        or regime_snapshot.get("paper_only") is not True
        or lifecycle_snapshot.get("paper_only") is not True
        or regime_snapshot.get("live_trading_authority") is not False
        or lifecycle_snapshot.get("live_trading_authority") is not False
        or regime_snapshot.get("private_credentials_used") is not False
        or lifecycle_snapshot.get("private_credentials_used") is not False
        or regime_snapshot.get("automatic_strategy_promotion") is not False
        or lifecycle_snapshot.get("automatic_strategy_promotion") is not False
        or regime_snapshot.get("deterministic_risk_final_authority") is not True
        or lifecycle_snapshot.get("deterministic_risk_final_authority") is not True
        or lifecycle_snapshot.get("regime_selected_rebalance_operational") is not True
    ):
        raise DemoStrategyDiscoveryHealthTriggerError("Demo regime/lifecycle authority binding failed")

    cells = regime_snapshot.get("cells")
    expected = regime_snapshot.get("expected_cell_count")
    verified = regime_snapshot.get("verified_cell_count")
    if (
        not isinstance(cells, list)
        or isinstance(expected, bool)
        or not isinstance(expected, int)
        or expected <= 0
        or verified != expected
        or len(cells) != expected
    ):
        raise DemoStrategyDiscoveryHealthTriggerError("Demo regime cells are incomplete")

    candidate_total = 0
    action_required_cells = 0
    all_cash_cells = 0
    for cell in cells:
        if not isinstance(cell, Mapping):
            raise DemoStrategyDiscoveryHealthTriggerError("Demo regime cell is invalid")
        candidate_count = cell.get("candidate_count")
        if isinstance(candidate_count, bool) or not isinstance(candidate_count, int) or candidate_count < 0:
            raise DemoStrategyDiscoveryHealthTriggerError("Demo candidate count is invalid")
        candidate_total += candidate_count
        if cell.get("drift_state") == "ACTION_REQUIRED":
            action_required_cells += 1
        elif cell.get("drift_state") != "STABLE":
            raise DemoStrategyDiscoveryHealthTriggerError("Demo drift state is unsupported")
        if _cash_weight(cell.get("cash_weight")) == Decimal("1"):
            all_cash_cells += 1

    no_eligible_candidates = candidate_total == 0
    drift_research_required = action_required_cells > 0
    should_dispatch = bool(no_eligible_candidates or drift_research_required)
    if no_eligible_candidates:
        reason = "NO_ELIGIBLE_PAPER_CANDIDATES"
    elif drift_research_required:
        reason = "PERFORMANCE_DRIFT_RESEARCH_REQUIRED"
    else:
        reason = "CURRENT_DEMO_RESEARCH_HEALTH_SUFFICIENT"

    core = {
        "schema_version": SCHEMA,
        "source_sha": regime_snapshot.get("source_sha"),
        "regime_cycle_digest": regime_snapshot.get("cycle_digest"),
        "lifecycle_digest": lifecycle_snapshot.get("lifecycle_digest"),
        "verified_cell_count": verified,
        "eligible_candidate_count": candidate_total,
        "action_required_cell_count": action_required_cells,
        "all_cash_cell_count": all_cash_cells,
        "should_dispatch": should_dispatch,
        "reason_code": reason,
        "trigger_scope": "verified_demo_lifecycle_research_gap_only",
        "daily_rotation_remains_required": True,
        "research_only": True,
        "paper_only": True,
        "live_trading_authority": False,
        "qualification_authority": False,
        "automatic_strategy_promotion": False,
    }
    return {**core, "trigger_digest": _digest(core)}


def verify_demo_health_trigger(value: Mapping[str, Any]) -> dict[str, Any]:
    checks = {"schema": False, "digest": False, "authority": False, "shape": False}
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
            and core.get("trigger_scope") == "verified_demo_lifecycle_research_gap_only"
            and isinstance(core.get("verified_cell_count"), int)
            and isinstance(core.get("eligible_candidate_count"), int)
            and isinstance(core.get("action_required_cell_count"), int)
            and isinstance(core.get("all_cash_cell_count"), int)
        )
    except (TypeError, ValueError):
        pass
    return {"decision": "pass" if all(checks.values()) else "reject", "checks": checks}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--regime-snapshot", type=Path, required=True)
    parser.add_argument("--lifecycle-snapshot", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        regime = json.loads(args.regime_snapshot.read_text(encoding="utf-8"))
        lifecycle = json.loads(args.lifecycle_snapshot.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise DemoStrategyDiscoveryHealthTriggerError("Demo trigger inputs are unavailable") from exc
    decision = build_demo_health_trigger(regime, lifecycle)
    if verify_demo_health_trigger(decision).get("decision") != "pass":
        raise DemoStrategyDiscoveryHealthTriggerError("Demo health trigger failed verification")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(decision, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(decision, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
