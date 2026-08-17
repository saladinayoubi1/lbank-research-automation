"""Deterministic read-only mission orchestration for the interactive AI Room.

The runner mirrors the repository mission selection policy without executing shell
commands, workers, trading code, or state mutations. It is intentionally suitable for
an L3 reversible route because it only computes the next bounded orchestration plan.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

MISSION_RUNNER_CONTRACT_VERSION = "nexus.mission-runner.v1"
DEFAULT_QUEUE_PATH = Path(__file__).with_name("config") / "nexus-mission-queue.json"
MAX_QUEUE_BYTES = 256_000
MAX_MISSIONS = 256
MAX_PARALLEL = 8
PRIORITY_ORDER = (
    "product_research",
    "phase_blocker",
    "stability",
    "automation",
    "development_speed",
    "security",
    "maintainability",
    "user_experience",
    "monetization",
    "backlog",
)
LANE_ORDER = {"product": 0, "blocker": 1, "general": 2, "backlog": 9}


class MissionRunnerError(ValueError):
    pass


def _canonical(value: Any) -> bytes:
    try:
        return json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        ).encode("utf-8")
    except (TypeError, ValueError, OverflowError) as exc:
        raise MissionRunnerError("mission queue is not canonically serializable") from exc


def _identifier(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 160:
        raise MissionRunnerError(f"{field} must be a non-empty bounded string")
    return value


def load_queue(path: Path = DEFAULT_QUEUE_PATH) -> dict[str, Any]:
    try:
        stat = path.stat()
        if stat.st_size < 2 or stat.st_size > MAX_QUEUE_BYTES:
            raise MissionRunnerError("mission queue size is outside bounds")
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise MissionRunnerError("mission queue is unavailable") from exc
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise MissionRunnerError("mission queue is invalid") from exc
    if not isinstance(payload, dict):
        raise MissionRunnerError("mission queue root must be an object")
    missions = payload.get("missions")
    policy = payload.get("selectionPolicy")
    if not isinstance(missions, list) or not isinstance(policy, Mapping):
        raise MissionRunnerError("mission queue contract is incomplete")
    if not missions or len(missions) > MAX_MISSIONS:
        raise MissionRunnerError("mission count is outside bounds")
    return payload


def _validated_missions(queue: Mapping[str, Any]) -> tuple[list[dict[str, Any]], int]:
    missions = queue.get("missions")
    policy = queue.get("selectionPolicy")
    if not isinstance(missions, list) or not isinstance(policy, Mapping):
        raise MissionRunnerError("mission queue contract is incomplete")
    max_parallel = policy.get("maxParallelMissions", 3)
    if isinstance(max_parallel, bool) or not isinstance(max_parallel, int) or not (1 <= max_parallel <= MAX_PARALLEL):
        raise MissionRunnerError("maxParallelMissions is outside bounds")
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, raw in enumerate(missions):
        if not isinstance(raw, Mapping):
            raise MissionRunnerError(f"mission[{index}] must be an object")
        mission_id = _identifier(raw.get("id"), f"mission[{index}].id")
        title = _identifier(raw.get("title"), f"mission[{index}].title")
        if mission_id in seen:
            raise MissionRunnerError("duplicate mission id")
        seen.add(mission_id)
        status = raw.get("status")
        if status not in {"completed", "active", "queued", "blocked"}:
            raise MissionRunnerError("unsupported mission status")
        priority = raw.get("priority")
        lane = raw.get("lane", "general")
        if priority not in PRIORITY_ORDER or lane not in LANE_ORDER:
            raise MissionRunnerError("unsupported mission priority or lane")
        dependencies = raw.get("dependencies")
        if not isinstance(dependencies, list) or len(dependencies) > 64:
            raise MissionRunnerError("mission dependencies are malformed")
        deps = [_identifier(item, "mission dependency") for item in dependencies]
        if not isinstance(raw.get("reversible"), bool) or raw.get("reversible") is not True:
            raise MissionRunnerError("AI Room may orchestrate reversible missions only")
        normalized.append({
            "id": mission_id,
            "title": title,
            "status": status,
            "priority": priority,
            "lane": lane,
            "dependencies": deps,
            "reversible": True,
        })
    ids = {mission["id"] for mission in normalized}
    if any(dep not in ids for mission in normalized for dep in mission["dependencies"]):
        raise MissionRunnerError("mission dependency references an unknown mission")
    return normalized, max_parallel


def _rank(mission: Mapping[str, Any]) -> tuple[int, int, str]:
    return (
        LANE_ORDER[str(mission["lane"])],
        PRIORITY_ORDER.index(str(mission["priority"])),
        str(mission["id"]),
    )


def orchestrate(queue: Mapping[str, Any]) -> dict[str, Any]:
    missions, max_parallel = _validated_missions(queue)
    by_id = {mission["id"]: mission for mission in missions}

    def dependencies_complete(mission: Mapping[str, Any]) -> bool:
        return all(by_id[dep]["status"] == "completed" for dep in mission["dependencies"])

    ready = sorted(
        [
            mission for mission in missions
            if mission["status"] in {"active", "queued"} and dependencies_complete(mission)
        ],
        key=_rank,
    )
    product_ready = [mission for mission in ready if mission["lane"] == "product"]
    product_slots = (max_parallel + 1) // 2 if product_ready else 0
    selected: list[dict[str, Any]] = []
    selected_ids: set[str] = set()
    for mission in product_ready[:product_slots]:
        selected.append(mission)
        selected_ids.add(mission["id"])
    for mission in ready:
        if len(selected) >= max_parallel:
            break
        if mission["id"] in selected_ids:
            continue
        selected.append(mission)
        selected_ids.add(mission["id"])

    projection = {
        "selected_mission_id": ready[0]["id"] if ready else None,
        "selected_mission_title": ready[0]["title"] if ready else None,
        "parallel_mission_ids": [mission["id"] for mission in selected],
        "parallel_mission_titles": [mission["title"] for mission in selected],
        "ready_count": len(ready),
        "completed_count": sum(mission["status"] == "completed" for mission in missions),
        "blocked_count": sum(mission["status"] == "blocked" for mission in missions),
        "queued_count": sum(mission["status"] == "queued" for mission in missions),
    }
    return {
        "contract_version": MISSION_RUNNER_CONTRACT_VERSION,
        "executed": True,
        "state_mutation": False,
        "reversible": True,
        "paper_only": True,
        "queue_digest": hashlib.sha256(_canonical(queue)).hexdigest(),
        **projection,
    }


def run_mission_orchestration(path: Path = DEFAULT_QUEUE_PATH) -> dict[str, Any]:
    return orchestrate(load_queue(path))
