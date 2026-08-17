from __future__ import annotations

import argparse
import json
from pathlib import Path

import agent_manager as am
import phase5_mission_contract as mc

MISSION_PATH = Path("config/nexus-phase5-missions.json")
RUNTIME_PATH = Path("data/agent_coordination/phase5_mission_runtime.json")
SUMMARY_PATH = Path("data/agent_coordination/phase5_mission_state.json")


def load_mission(path: Path) -> dict:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise mc.MissionContractError("mission definition JSON is corrupt") from exc
    return mc.to_agent_manager_config(payload)


def cycle_shadow(mission_path: Path, runtime_path: Path, summary_path: Path) -> dict:
    template = load_mission(mission_path)
    runtime = mc.load_runtime_strict(runtime_path)
    config = mc.merge_compatible_runtime(template, runtime)
    summary = am.cycle(config)
    am.atomic_json(runtime_path, config)
    am.atomic_json(summary_path, summary)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="NEXUS Phase 5 shadow mission runner")
    parser.add_argument("--mission", default=str(MISSION_PATH))
    parser.add_argument("--runtime", default=str(RUNTIME_PATH))
    parser.add_argument("--summary", default=str(SUMMARY_PATH))
    args = parser.parse_args()

    summary = cycle_shadow(Path(args.mission), Path(args.runtime), Path(args.summary))
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
