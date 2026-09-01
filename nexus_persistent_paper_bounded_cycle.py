"""Bounded two-pass driver for the public Bybit Paper runtime.

The first matrix pass records exact-main successes and fail-closed blocked cells.
If any cell is blocked, the driver waits for one fixed cooldown and then invokes
the normal persistent cycle exactly once. Because verified cells have already
advanced their closed-bar cursor, the second pass skips them and retries only
blocked cells. No Live authority, credential, endpoint, market, interval, or
candle semantics are widened here.
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from nexus_demo_strategy_matrix import (
    _atomic_json as _matrix_atomic_json,
    load_manifest,
    load_state,
    run_matrix_cycle,
    verify_snapshot,
)
from nexus_persistent_paper_trading_loop import (
    PersistentPaperTradingLoopError,
    run_persistent_cycle,
    verify_loop_snapshot,
)
from nexus_public_regime_cycle import PUBLIC_DATA_MODE

BLOCKED_CELL_COOLDOWN_SECONDS = 30.0


def run_bounded_cycle(
    *,
    repo_root: Path,
    state_root: Path,
    source_sha: str,
    run_id: str,
    now_ms: int,
    manifest_path: Path,
    selector_policy_path: Path,
    sleep=time.sleep,
) -> dict:
    root = Path(state_root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    manifest = load_manifest(manifest_path)
    matrix_state_path = root / "matrix-state.json"
    matrix_state = load_state(matrix_state_path, manifest)

    pre_state, pre_snapshot = run_matrix_cycle(
        manifest=manifest,
        state=matrix_state,
        state_root=root,
        source_sha=source_sha,
        run_id=str(run_id),
        now_ms=now_ms,
        data_mode=PUBLIC_DATA_MODE,
        dataset_sha256=None,
    )
    if verify_snapshot(pre_snapshot).get("decision") != "pass":
        raise PersistentPaperTradingLoopError("bounded matrix pre-pass failed verification")

    _matrix_atomic_json(matrix_state_path, pre_state)
    _matrix_atomic_json(root / "demo" / "strategy-matrix.json", pre_snapshot)

    blocked = int(pre_snapshot.get("blocked_cell_count", 0))
    print(json.dumps({
        "bounded_prepass_blocked_cells": blocked,
        "bounded_prepass_verified_cells": int(pre_snapshot.get("verified_cell_count", 0)),
        "bounded_second_pass_max_attempts_per_cell": 2,
        "paper_only": True,
        "live_trading_authority": False,
    }, sort_keys=True))
    if blocked:
        sleep(BLOCKED_CELL_COOLDOWN_SECONDS)

    snapshot = run_persistent_cycle(
        repo_root=repo_root,
        state_root=root,
        source_sha=source_sha,
        run_id=str(run_id),
        now_ms=now_ms,
        manifest_path=manifest_path,
        selector_policy_path=selector_policy_path,
    )
    if verify_loop_snapshot(snapshot).get("decision") != "pass":
        raise PersistentPaperTradingLoopError("bounded persistent cycle failed verification")
    return snapshot


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path("."))
    parser.add_argument("--state-root", type=Path, required=True)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--now-ms", type=int)
    parser.add_argument(
        "--manifest", type=Path, default=Path("config/nexus-demo-strategy-matrix-v1.json")
    )
    parser.add_argument(
        "--selector-policy", type=Path,
        default=Path("config/nexus-regime-strategy-policy-v1.json"),
    )
    args = parser.parse_args()
    now_ms = args.now_ms if args.now_ms is not None else int(time.time() * 1000)
    snapshot = run_bounded_cycle(
        repo_root=args.repo_root,
        state_root=args.state_root,
        source_sha=args.source_sha,
        run_id=args.run_id,
        now_ms=now_ms,
        manifest_path=args.manifest,
        selector_policy_path=args.selector_policy,
    )
    verification = verify_loop_snapshot(snapshot)
    print(json.dumps({
        "status": snapshot["status"],
        "fresh_cells": snapshot["fresh_cell_count"],
        "regime_status": snapshot["regime_status"],
        "strategy_research_required": snapshot["strategy_research_required"],
        "health_trigger_requested": snapshot["strategy_discovery_health_trigger_requested"],
        "remaining_core_gap": snapshot["remaining_core_gap"],
        "decision": verification["decision"],
        "loop_digest": snapshot["loop_digest"],
    }, sort_keys=True))
    return 0 if verification["decision"] == "pass" else 2


if __name__ == "__main__":
    raise SystemExit(main())
