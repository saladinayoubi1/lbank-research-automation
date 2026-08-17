from __future__ import annotations

import argparse
import json
from pathlib import Path

import agent_manager as am
import phase5_mission_contract as mc
import phase5_mission_runner as mission_runner
import phase5_state_store as state

DEFAULT_STATE_DB = Path("data/agent_coordination/phase5_supervisor_state.sqlite3")
DEFAULT_SUMMARY = Path("data/agent_coordination/phase5_durable_summary.json")


def cycle_durable(mission_path: Path, state_db: Path, summary_path: Path) -> dict:
    template = mission_runner.load_mission(mission_path)
    mission_id = template["mission_id"]
    store = state.SQLiteStateStore(state_db)

    current = store.load_current(mission_id)
    if current is None:
        config = template
        expected_generation = None
    else:
        config = mc.merge_compatible_runtime(template, current.payload)
        expected_generation = current.generation

    summary = am.cycle(config)
    record = store.compare_and_swap(mission_id, expected_generation, config)
    evidence = {
        "schema_version": "nexus.phase5-durable-summary.v1",
        "mission_id": mission_id,
        "mission_revision": template["mission_revision"],
        "state_generation": record.generation,
        "state_sha256": record.payload_sha256,
        "transition_kind": record.transition_kind,
        "summary": summary,
    }
    am.atomic_json(summary_path, evidence)
    return evidence


def recover_durable(
    mission_path: Path,
    state_db: Path,
    summary_path: Path,
    *,
    expected_tip_generation: int,
) -> dict:
    template = mission_runner.load_mission(mission_path)
    mission_id = template["mission_id"]
    store = state.SQLiteStateStore(state_db)
    recovered = store.recover_to_previous_valid(mission_id, expected_tip_generation)
    # Rebind the recovered runtime through the current Mission contract before
    # reporting it as a usable previous-valid state. Do not advance the mission
    # in the recovery transaction itself.
    compatible = mc.merge_compatible_runtime(template, recovered.payload)
    summary = am.summarize(compatible)
    evidence = {
        "schema_version": "nexus.phase5-durable-recovery.v1",
        "mission_id": mission_id,
        "mission_revision": template["mission_revision"],
        "state_generation": recovered.generation,
        "state_sha256": recovered.payload_sha256,
        "transition_kind": recovered.transition_kind,
        "parent_generation": recovered.parent_generation,
        "quarantined_generations": list(recovered.quarantined_generations),
        "summary": summary,
    }
    am.atomic_json(summary_path, evidence)
    return evidence


def main() -> int:
    parser = argparse.ArgumentParser(description="NEXUS Phase 5 durable Supervisor shadow runner")
    parser.add_argument("--mission", default=str(mission_runner.MISSION_PATH))
    parser.add_argument("--state-db", default=str(DEFAULT_STATE_DB))
    parser.add_argument("--summary", default=str(DEFAULT_SUMMARY))
    parser.add_argument("--mode", choices=("cycle", "recover"), default="cycle")
    parser.add_argument("--expected-tip-generation", type=int)
    args = parser.parse_args()

    mission_path = Path(args.mission)
    state_db = Path(args.state_db)
    summary_path = Path(args.summary)
    if args.mode == "recover":
        if args.expected_tip_generation is None or args.expected_tip_generation < 0:
            parser.error("--expected-tip-generation is required for recovery")
        output = recover_durable(
            mission_path,
            state_db,
            summary_path,
            expected_tip_generation=args.expected_tip_generation,
        )
    else:
        if args.expected_tip_generation is not None:
            parser.error("--expected-tip-generation is recovery-only")
        output = cycle_durable(mission_path, state_db, summary_path)

    print(json.dumps(output, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
