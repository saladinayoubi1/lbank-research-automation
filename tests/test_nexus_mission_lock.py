from __future__ import annotations

import json
from pathlib import Path

import pytest

import nexus_mission_lock as mission_lock


def test_repository_mission_lock_is_valid() -> None:
    result = mission_lock.validate_mission_lock(".")
    assert result["decision"] == "PASS"
    assert result["primary_delivery_objective"] == "continuously_operating_paper_trading_engine"
    assert result["work_priority"] == "trading_engine_first"
    assert result["live_trading_authority"] is False
    assert result["required_symbols"] == ["BTCUSDT", "ETHUSDT"]
    assert result["required_timeframes"] == ["minute15", "hour1", "hour4"]
    assert result["required_strategy_families"] == ["momentum", "trend_breakout", "mean_reversion"]


@pytest.mark.parametrize(
    ("path", "value", "message"),
    [
        (("primary_delivery_objective",), "mobile_app_delivery", "primary delivery objective"),
        (("work_priority", "rule"), "packaging_first", "work priority"),
        (("safety_boundary", "live_trading_authority"), True, "Live authority"),
        (("safety_boundary", "deterministic_risk_final_authority"), False, "Deterministic Risk"),
        (("trading_engine", "continuous_strategy_discovery_required"), False, "Strategy Factory"),
        (("work_priority", "supporting_work_must_not_displace_trading_engine"), False, "support work"),
        (("completion_gate", "required_multi_timeframe"), False, "completion invariant"),
    ],
)
def test_mission_drift_fails_closed(tmp_path: Path, path: tuple[str, ...], value, message: str) -> None:
    config = json.loads(Path("config/nexus-mission-lock.json").read_text(encoding="utf-8"))
    cursor = config
    for key in path[:-1]:
        cursor = cursor[key]
    cursor[path[-1]] = value
    target = tmp_path / "config"
    target.mkdir(parents=True)
    (target / "nexus-mission-lock.json").write_text(json.dumps(config), encoding="utf-8")
    with pytest.raises(mission_lock.MissionLockError, match=message):
        mission_lock.validate_mission_lock(tmp_path)


def test_project_memory_names_the_machine_readable_mission_lock() -> None:
    memory = Path("docs/project_memory/PROJECT_MEMORY.md").read_text(encoding="utf-8")
    assert "## Mission Lock — primary delivery objective" in memory
    assert "continuously operating **Paper-only trading engine**" in memory
    assert "config/nexus-mission-lock.json" in memory
    assert "supporting work must not displace the trading engine" in memory.lower()
    assert "A green build, installer, app, workflow or proof harness is not equivalent" in memory
