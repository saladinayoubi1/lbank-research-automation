from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

MISSION_LOCK_PATH = Path("config/nexus-mission-lock.json")


class MissionLockError(ValueError):
    pass


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise MissionLockError(message)


def validate_mission_lock(root: str | Path = ".") -> dict[str, Any]:
    repo = Path(root).resolve()
    path = repo / MISSION_LOCK_PATH
    _require(path.is_file() and not path.is_symlink(), "canonical mission lock missing or substituted")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise MissionLockError("mission lock unreadable or malformed") from exc

    _require(isinstance(data, dict), "mission lock must be an object")
    _require(data.get("schema_version") == 1, "unsupported mission lock schema")
    _require(data.get("project") == "NEXUS / lbank-research-automation", "mission lock project mismatch")
    _require(data.get("locked") is True, "mission lock must remain enabled")
    _require(
        data.get("primary_delivery_objective") == "continuously_operating_paper_trading_engine",
        "primary delivery objective drifted from the Paper trading engine",
    )

    safety = data.get("safety_boundary")
    _require(isinstance(safety, dict), "mission lock safety boundary missing")
    _require(safety.get("research_backtest_paper_only") is True, "Paper-only boundary must remain enabled")
    _require(safety.get("live_trading_authority") is False, "mission lock cannot grant Live authority")
    _require(safety.get("private_exchange_credentials_allowed") is False, "private exchange credentials remain forbidden")
    _require(safety.get("automatic_live_promotion") is False, "automatic Live promotion remains forbidden")
    _require(safety.get("deterministic_risk_final_authority") is True, "Deterministic Risk must remain final")

    engine = data.get("trading_engine")
    _require(isinstance(engine, dict), "trading engine mission contract missing")
    _require(engine.get("portfolio_model") == "multi_pair_multi_timeframe_multi_strategy", "portfolio model drifted")
    _require(engine.get("required_symbols") == ["BTCUSDT", "ETHUSDT"], "verified base pair set drifted")
    _require(engine.get("required_timeframes") == ["minute15", "hour1", "hour4"], "required timeframe set drifted")
    _require(
        engine.get("required_strategy_families") == ["momentum", "trend_breakout", "mean_reversion"],
        "required strategy family set drifted",
    )
    required_loop = engine.get("required_loop")
    expected_loop = [
        "canonical_public_market_data",
        "multi_pair_context",
        "multi_timeframe_context",
        "multi_strategy_evaluation",
        "regime_classification",
        "independent_qualification",
        "portfolio_allocation_decision",
        "deterministic_risk",
        "paper_open_close_rebalance",
        "performance_drift",
        "strategy_health_lifecycle",
        "strategy_factory_discovery_requalification",
        "next_closed_candle_cycle",
    ]
    _require(required_loop == expected_loop, "required trading loop order drifted")
    _require(engine.get("cash_reject_no_action_are_valid") is True, "cash/reject/no-action must remain valid")
    _require(engine.get("continuous_strategy_discovery_required") is True, "Strategy Factory discovery must remain continuous")
    _require(engine.get("restart_replay_required") is True, "restart/replay evidence must remain required")

    priority = data.get("work_priority")
    _require(isinstance(priority, dict), "work-priority contract missing")
    _require(priority.get("rule") == "trading_engine_first", "work priority drifted from trading_engine_first")
    _require(priority.get("material_work_requires_direct_mission_link") is True, "material work must remain mission-linked")
    _require(priority.get("supporting_work_must_not_displace_trading_engine") is True, "support work cannot displace trading engine")
    _require(priority.get("green_ci_is_not_trading_completion") is True, "green CI cannot equal trading completion")

    completion = data.get("completion_gate")
    _require(isinstance(completion, dict), "completion gate missing")
    for key in (
        "trading_core_complete_claim_requires_persistent_end_to_end_loop",
        "required_runtime_evidence",
        "required_multi_pair",
        "required_multi_timeframe",
        "required_multi_strategy",
        "required_genuine_paper_outcomes_to_performance_drift",
        "required_continuous_strategy_factory",
        "allow_cash_only_cycle",
        "allow_reject_no_action_cycle",
    ):
        _require(completion.get(key) is True, f"completion invariant disabled: {key}")

    deviation = data.get("deviation_policy")
    _require(isinstance(deviation, dict), "deviation policy missing")
    _require(deviation.get("material_task_without_direct_mission_link") == "defer_or_reject", "unlinked work must defer/reject")
    _require(deviation.get("owner_override_required_for_priority_change") is True, "priority changes require owner override")
    _require(deviation.get("mission_change_requires_project_memory_update") is True, "mission changes must update Project Memory")

    return {
        "decision": "PASS",
        "primary_delivery_objective": data["primary_delivery_objective"],
        "work_priority": priority["rule"],
        "live_trading_authority": safety["live_trading_authority"],
        "required_symbols": engine["required_symbols"],
        "required_timeframes": engine["required_timeframes"],
        "required_strategy_families": engine["required_strategy_families"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Fail-closed validator for the NEXUS Mission Lock")
    parser.add_argument("--root", default=".")
    args = parser.parse_args()
    try:
        result = validate_mission_lock(args.root)
    except MissionLockError as exc:
        print(f"NEXUS Mission Lock validation failed: {exc}")
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
