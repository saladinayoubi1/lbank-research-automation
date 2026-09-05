"""Persistent four-symbol NEXUS Paper loop over public Bybit closed candles.

This is the bounded maintenance cutover for the already-scheduled Paper runtime.
It consumes the accepted v2 matrix manifest, performs the existing digest-verified
v1 -> v2 migration exactly once when durable legacy state is restored, runs the
12-cell / 36-lane matrix, and composes performance, regime selection and Paper
lifecycle evidence without widening authority.

Research/Paper only. Live authority, private exchange credentials, real exchange
orders and automatic strategy promotion remain disabled. Deterministic Risk is
final and issue #984 state is never reused by this runtime.
"""
from __future__ import annotations

import argparse
import json
import re
import time
from pathlib import Path
from typing import Any, Mapping

from nexus_demo_paper_performance_refresh import run_performance_refresh
from nexus_demo_paper_position_maintenance import run_position_maintenance
from nexus_demo_strategy_matrix import _atomic_json as _matrix_atomic_json, run_matrix_cycle
from nexus_multipair_demo_strategy_matrix import (
    MIGRATION_SCHEMA,
    _digest as _matrix_digest,
    load_manifest,
    load_or_migrate_state,
    verify_v2_snapshot,
)
from nexus_multipair_public_regime_cycle import run_multipair_public_regime_cycle
from nexus_multipair_regime_lifecycle import verify_v2_regime_snapshot
from nexus_persistent_paper_trading_loop import (
    STATE_SCHEMA,
    _decimal,
    _digest,
    _fresh_cells,
    _load_policy,
    _performance_health_feedback_operational,
    _read_json,
    _regime_boundary,
    _research_required,
    load_loop_state,
)
from nexus_public_regime_cycle import PUBLIC_DATA_MODE
from scripts.nexus_strategy_discovery_controller import build_status as build_discovery_status


SCHEMA = "nexus.multipair-persistent-paper-trading-loop.v1"
_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
EXPECTED_CELLS = 12
EXPECTED_LANES = 36
MIGRATION_EVIDENCE_NAME = "matrix-v1-to-v2-migration.json"


class MultiPairPersistentPaperTradingLoopError(RuntimeError):
    pass


def _atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    from nexus_persistent_paper_trading_loop import _atomic_json as legacy_atomic_json

    legacy_atomic_json(path, value)


def _verify_migration(value: Mapping[str, Any]) -> dict[str, Any]:
    checks = {
        "schema": False,
        "digest": False,
        "authority": False,
        "surface": False,
    }
    try:
        core = dict(value)
        claimed = core.pop("migration_digest", None)
        checks["schema"] = core.get("schema_version") == MIGRATION_SCHEMA
        checks["digest"] = isinstance(claimed, str) and claimed == _matrix_digest(core)
        checks["authority"] = bool(
            core.get("paper_only") is True
            and core.get("live_trading_authority") is False
            and core.get("private_credentials_used") is False
            and core.get("automatic_strategy_promotion") is False
        )
        preserved = core.get("preserved_cell_ids")
        checks["surface"] = bool(
            core.get("from_matrix_id") == "nexus-demo-btc-eth-3tf-3strategy-v1"
            and core.get("to_matrix_id") == "nexus-demo-btc-eth-sol-xrp-3tf-3strategy-v2"
            and isinstance(preserved, list)
            and core.get("preserved_cell_count") == len(preserved)
            and len(preserved) <= 6
            and all(
                isinstance(cell_id, str)
                and cell_id.split(":", 1)[0] in {"BTCUSDT", "ETHUSDT"}
                for cell_id in preserved
            )
            and core.get("new_symbols") == ["SOLUSDT", "XRPUSDT"]
            and core.get("new_symbol_inherited_cell_count") == 0
        )
    except (KeyError, TypeError, ValueError):
        pass
    return {"decision": "pass" if all(checks.values()) else "reject", "checks": checks}


def _load_migration_evidence(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    value = _read_json(path)
    if _verify_migration(value).get("decision") != "pass":
        raise MultiPairPersistentPaperTradingLoopError("persisted v1-to-v2 migration evidence is invalid")
    return value


def _load_existing_regime(
    path: Path, source_sha: str, boundary_digest: str
) -> dict[str, Any] | None:
    if not path.exists():
        return None
    value = _read_json(path)
    if (
        value.get("source_sha") != source_sha
        or value.get("data_mode") != PUBLIC_DATA_MODE
        or verify_v2_regime_snapshot(value).get("decision") != "pass"
    ):
        return None
    contexts = value.get("context_digests")
    if not isinstance(contexts, Mapping):
        return None
    if not isinstance(boundary_digest, str) or not _SHA256_RE.fullmatch(boundary_digest):
        return None
    return value


def run_persistent_cycle(
    *,
    repo_root: Path,
    state_root: Path,
    source_sha: str,
    run_id: str,
    now_ms: int,
    manifest_path: Path,
    legacy_manifest_path: Path,
    selector_policy_path: Path,
) -> dict[str, Any]:
    source_sha = str(source_sha).strip().lower()
    if not _SHA_RE.fullmatch(source_sha):
        raise MultiPairPersistentPaperTradingLoopError("source_sha must be an exact Git SHA")
    if not str(run_id).isdigit():
        raise MultiPairPersistentPaperTradingLoopError("run_id must be numeric")
    if isinstance(now_ms, bool) or not isinstance(now_ms, int) or now_ms <= 0:
        raise MultiPairPersistentPaperTradingLoopError("now_ms must be positive")

    repo_root = Path(repo_root).resolve()
    root = Path(state_root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    manifest = load_manifest(manifest_path)
    policy = _load_policy(selector_policy_path)
    expected_cells = len(manifest["symbols"]) * len(manifest["timeframes"])
    expected_lanes = expected_cells * len(manifest["families"])
    if expected_cells != EXPECTED_CELLS or expected_lanes != EXPECTED_LANES:
        raise MultiPairPersistentPaperTradingLoopError("persistent v2 surface is not 12 cells / 36 lanes")

    loop_state_path = root / "persistent-loop-state.json"
    loop_state = load_loop_state(loop_state_path)
    matrix_state_path = root / "matrix-state.json"
    state_existed = matrix_state_path.exists()
    matrix_state, migration = load_or_migrate_state(
        matrix_state_path,
        manifest,
        legacy_manifest_path=legacy_manifest_path,
    )
    migration_path = root / "demo" / MIGRATION_EVIDENCE_NAME
    prior_migration = _load_migration_evidence(migration_path)
    if migration is not None:
        if _verify_migration(migration).get("decision") != "pass":
            raise MultiPairPersistentPaperTradingLoopError("fresh v1-to-v2 migration failed verification")
        if prior_migration is not None and prior_migration != migration:
            raise MultiPairPersistentPaperTradingLoopError("migration lineage changed unexpectedly")
        _atomic_json(migration_path, migration)
        migration_evidence = migration
        migration_status = "PERFORMED"
    elif prior_migration is not None:
        migration_evidence = prior_migration
        migration_status = "ALREADY_V2"
    elif state_existed:
        raise MultiPairPersistentPaperTradingLoopError(
            "existing v2 persistent state is missing bounded migration lineage"
        )
    else:
        migration_evidence = None
        migration_status = "FRESH_V2"

    next_matrix_state, matrix_snapshot = run_matrix_cycle(
        manifest=manifest,
        state=matrix_state,
        state_root=root,
        source_sha=source_sha,
        run_id=str(run_id),
        now_ms=now_ms,
        data_mode=PUBLIC_DATA_MODE,
        dataset_sha256=None,
    )
    if verify_v2_snapshot(
        matrix_snapshot, manifest=manifest, state=next_matrix_state
    ).get("decision") != "pass":
        raise MultiPairPersistentPaperTradingLoopError("public v2 matrix snapshot failed verification")
    _matrix_atomic_json(matrix_state_path, next_matrix_state)
    _matrix_atomic_json(root / "demo" / "strategy-matrix.json", matrix_snapshot)

    fresh_cells = _fresh_cells(next_matrix_state, source_sha)
    performance: dict[str, Any] | None = None
    maintenance: dict[str, Any] | None = None
    regime: dict[str, Any] | None = None
    regime_status = "WAITING_FOR_FRESH_CELLS"
    boundary_digest: str | None = None

    if len(fresh_cells) == expected_cells:
        maintenance = run_position_maintenance(
            manifest=manifest, state_root=root, source_sha=source_sha
        )
        if maintenance.get("exposure_increased") is not False:
            raise MultiPairPersistentPaperTradingLoopError("position maintenance increased exposure")
        performance = run_performance_refresh(
            manifest=manifest, state_root=root, source_sha=source_sha
        )
        if performance.get("schema_version") == "nexus.demo-paper-performance-refresh.v1":
            rebound_state = performance.pop("_rebound_matrix_state", None)
            rebound_snapshot = performance.pop("_rebound_matrix_snapshot", None)
            if not isinstance(rebound_state, dict) or not isinstance(rebound_snapshot, dict):
                raise MultiPairPersistentPaperTradingLoopError(
                    "performance refresh omitted rebound v2 matrix evidence"
                )
            if verify_v2_snapshot(
                rebound_snapshot, manifest=manifest, state=rebound_state
            ).get("decision") != "pass":
                raise MultiPairPersistentPaperTradingLoopError(
                    "rebound v2 matrix snapshot failed verification"
                )
            next_matrix_state = rebound_state
            matrix_snapshot = rebound_snapshot
        boundary = _regime_boundary(next_matrix_state, list(manifest["symbols"]))
        boundary_digest = _digest(boundary)
        regime_path = root / "demo" / "regime-cycle.json"
        can_reuse = (
            loop_state.get("last_source_sha") == source_sha
            and loop_state.get("last_regime_boundary_digest") == boundary_digest
        )
        existing = (
            _load_existing_regime(regime_path, source_sha, boundary_digest)
            if can_reuse else None
        )
        if existing is not None:
            regime = existing
            regime_status = "NO_NEW_4H_BOUNDARY"
        else:
            regime = run_multipair_public_regime_cycle(
                manifest=manifest,
                matrix_state=next_matrix_state,
                state_root=root,
                source_sha=source_sha,
                selector_policy=policy,
            )
            if verify_v2_regime_snapshot(regime).get("decision") != "pass":
                raise MultiPairPersistentPaperTradingLoopError(
                    "four-symbol public regime cycle failed verification"
                )
            regime_status = "VERIFIED"

    discovery = build_discovery_status(repo_root)
    if discovery.get("controller_verified") is not True:
        raise MultiPairPersistentPaperTradingLoopError("Strategy Discovery controller is not verified")
    research_required = _research_required(regime, performance)
    rebalance_operational = bool(
        isinstance(regime, Mapping)
        and regime.get("regime_selected_rebalance_operational") is True
        and regime.get("regime_selected_exposure_increase_operational") is True
    )
    performance_feedback_operational = _performance_health_feedback_operational(
        performance, expected_cells
    )
    health_trigger_requested = bool(
        research_required and regime_status == "VERIFIED" and rebalance_operational
    )

    if len(fresh_cells) != expected_cells:
        remaining_core_gap = "WAITING_FOR_FRESH_CELLS"
    elif not rebalance_operational:
        remaining_core_gap = "REGIME_SELECTED_POSITION_CLOSE_AND_RESIZE"
    else:
        remaining_core_gap = "RUNTIME_EVIDENCE_AND_DISCOVERY_FEEDBACK_PROOF"

    next_state_core = {
        "schema_version": STATE_SCHEMA,
        "cycle_count": int(loop_state["cycle_count"]) + 1,
        "last_source_sha": source_sha,
        "last_run_id": str(run_id),
        "last_now_ms": now_ms,
        "last_regime_boundary_digest": boundary_digest,
        "last_regime_cycle_digest": (
            regime.get("cycle_digest") if regime else loop_state.get("last_regime_cycle_digest")
        ),
        "paper_only": True,
        "live_trading_authority": False,
        "private_credentials_used": False,
        "automatic_strategy_promotion": False,
    }
    next_loop_state = {**next_state_core, "state_digest": _digest(next_state_core)}
    _atomic_json(loop_state_path, next_loop_state)

    if migration_evidence is None:
        migration_digest = None
        preserved_cell_count = 0
        new_symbol_inherited_cell_count = 0
    else:
        migration_digest = migration_evidence["migration_digest"]
        preserved_cell_count = migration_evidence["preserved_cell_count"]
        new_symbol_inherited_cell_count = migration_evidence[
            "new_symbol_inherited_cell_count"
        ]

    status = (
        "PAPER_LOOP_ACTIVE"
        if len(fresh_cells) == expected_cells
        else "WAITING_FOR_FRESH_CELLS"
    )
    core = {
        "schema_version": SCHEMA,
        "source_sha": source_sha,
        "run_id": str(run_id),
        "now_ms": now_ms,
        "status": status,
        "data_mode": PUBLIC_DATA_MODE,
        "matrix_id": manifest["matrix_id"],
        "matrix_snapshot_digest": matrix_snapshot["snapshot_digest"],
        "expected_cell_count": expected_cells,
        "fresh_cell_count": len(fresh_cells),
        "fresh_cells": fresh_cells,
        "expected_lane_count": expected_lanes,
        "matrix_migration_status": migration_status,
        "matrix_migration_digest": migration_digest,
        "legacy_preserved_cell_count": preserved_cell_count,
        "new_symbol_inherited_cell_count": new_symbol_inherited_cell_count,
        "regime_status": regime_status,
        "regime_cycle_digest": regime.get("cycle_digest") if regime else None,
        "maintenance_digest": maintenance.get("maintenance_digest") if maintenance else None,
        "performance_refresh_digest": performance.get("refresh_digest") if performance else None,
        "performance_health_feedback_operational": performance_feedback_operational,
        "strategy_discovery_controller_verified": True,
        "strategy_discovery_next_action": discovery.get("next_research_action"),
        "strategy_discovery_ready_stage_count": discovery.get("summary", {}).get(
            "ready_search_stage_count"
        ),
        "strategy_research_required": research_required,
        "strategy_discovery_health_trigger_requested": health_trigger_requested,
        "strategy_discovery_health_trigger_contract": "successful_paper_loop_new_4h_boundary_only",
        "strategy_discovery_rotation": "automatic_daily_and_health_driven_bounded_rotation",
        "persistent_state_digest": next_loop_state["state_digest"],
        "comparison_position_lifecycle": "OPEN_HOLD_RISK_REDUCING_CLOSE",
        "regime_selected_rebalance_operational": rebalance_operational,
        "regime_selected_exposure_increase_operational": bool(
            isinstance(regime, Mapping)
            and regime.get("regime_selected_exposure_increase_operational") is True
        ),
        "remaining_core_gap": remaining_core_gap,
        "trading_engine_complete": False,
        "paper_only": True,
        "live_trading_authority": False,
        "private_credentials_used": False,
        "real_exchange_orders": False,
        "automatic_strategy_promotion": False,
        "deterministic_risk_final_authority": True,
        "persistent_runtime_database_on_github": False,
        "state_isolated_from_issue_984": True,
        "issue_984_state_artifact_touched": False,
    }
    snapshot = {**core, "loop_digest": _digest(core)}
    _atomic_json(root / "demo" / "persistent-paper-trading-loop.json", snapshot)
    return snapshot


def verify_loop_snapshot(value: Mapping[str, Any]) -> dict[str, Any]:
    checks = {
        "schema": False,
        "digest": False,
        "authority": False,
        "shape": False,
        "migration": False,
        "status": False,
        "mission_truth": False,
        "isolation": False,
    }
    try:
        core = dict(value)
        claimed = core.pop("loop_digest", None)
        checks["schema"] = core.get("schema_version") == SCHEMA
        checks["digest"] = isinstance(claimed, str) and claimed == _digest(core)
        checks["authority"] = bool(
            core.get("paper_only") is True
            and core.get("live_trading_authority") is False
            and core.get("private_credentials_used") is False
            and core.get("real_exchange_orders") is False
            and core.get("automatic_strategy_promotion") is False
            and core.get("deterministic_risk_final_authority") is True
        )
        checks["shape"] = bool(
            core.get("matrix_id") == "nexus-demo-btc-eth-sol-xrp-3tf-3strategy-v2"
            and core.get("expected_cell_count") == EXPECTED_CELLS
            and core.get("expected_lane_count") == EXPECTED_LANES
            and isinstance(core.get("fresh_cell_count"), int)
            and not isinstance(core.get("fresh_cell_count"), bool)
            and 0 <= core["fresh_cell_count"] <= EXPECTED_CELLS
            and isinstance(core.get("fresh_cells"), list)
            and len(core["fresh_cells"]) == core["fresh_cell_count"]
            and isinstance(core.get("performance_health_feedback_operational"), bool)
            and isinstance(core.get("strategy_discovery_health_trigger_requested"), bool)
            and isinstance(core.get("regime_selected_rebalance_operational"), bool)
            and isinstance(core.get("regime_selected_exposure_increase_operational"), bool)
        )
        migration_status = core.get("matrix_migration_status")
        migration_digest = core.get("matrix_migration_digest")
        if migration_status in {"PERFORMED", "ALREADY_V2"}:
            migration_valid = bool(
                isinstance(migration_digest, str)
                and _SHA256_RE.fullmatch(migration_digest)
                and isinstance(core.get("legacy_preserved_cell_count"), int)
                and 0 <= core["legacy_preserved_cell_count"] <= 6
                and core.get("new_symbol_inherited_cell_count") == 0
            )
        else:
            migration_valid = bool(
                migration_status == "FRESH_V2"
                and migration_digest is None
                and core.get("legacy_preserved_cell_count") == 0
                and core.get("new_symbol_inherited_cell_count") == 0
            )
        checks["migration"] = migration_valid
        status = core.get("status")
        checks["status"] = bool(
            (
                status == "WAITING_FOR_FRESH_CELLS"
                and core.get("fresh_cell_count") < EXPECTED_CELLS
            )
            or (
                status == "PAPER_LOOP_ACTIVE"
                and core.get("fresh_cell_count") == EXPECTED_CELLS
                and core.get("regime_status") in {"VERIFIED", "NO_NEW_4H_BOUNDARY"}
                and isinstance(core.get("regime_cycle_digest"), str)
                and _SHA256_RE.fullmatch(core["regime_cycle_digest"])
            )
        )
        if status == "WAITING_FOR_FRESH_CELLS":
            mission_state_valid = core.get("remaining_core_gap") == "WAITING_FOR_FRESH_CELLS"
        elif core.get("regime_selected_rebalance_operational") is True:
            mission_state_valid = bool(
                core.get("regime_selected_exposure_increase_operational") is True
                and core.get("performance_health_feedback_operational") is True
                and core.get("remaining_core_gap")
                == "RUNTIME_EVIDENCE_AND_DISCOVERY_FEEDBACK_PROOF"
            )
        else:
            mission_state_valid = (
                core.get("remaining_core_gap") == "REGIME_SELECTED_POSITION_CLOSE_AND_RESIZE"
            )
        checks["mission_truth"] = bool(
            core.get("strategy_discovery_controller_verified") is True
            and core.get("strategy_discovery_health_trigger_contract")
            == "successful_paper_loop_new_4h_boundary_only"
            and core.get("strategy_discovery_rotation")
            == "automatic_daily_and_health_driven_bounded_rotation"
            and mission_state_valid
            and core.get("trading_engine_complete") is False
        )
        checks["isolation"] = bool(
            core.get("persistent_runtime_database_on_github") is False
            and core.get("state_isolated_from_issue_984") is True
            and core.get("issue_984_state_artifact_touched") is False
        )
    except (TypeError, ValueError, KeyError):
        pass
    return {"decision": "pass" if all(checks.values()) else "reject", "checks": checks}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path("."))
    parser.add_argument("--state-root", type=Path, required=True)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--now-ms", type=int)
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path("config/nexus-demo-strategy-matrix-v2.json"),
    )
    parser.add_argument(
        "--legacy-manifest",
        type=Path,
        default=Path("config/nexus-demo-strategy-matrix-v1.json"),
    )
    parser.add_argument(
        "--selector-policy",
        type=Path,
        default=Path("config/nexus-regime-strategy-policy-v1.json"),
    )
    args = parser.parse_args()
    now_ms = args.now_ms if args.now_ms is not None else int(time.time() * 1000)
    snapshot = run_persistent_cycle(
        repo_root=args.repo_root,
        state_root=args.state_root,
        source_sha=args.source_sha,
        run_id=args.run_id,
        now_ms=now_ms,
        manifest_path=args.manifest,
        legacy_manifest_path=args.legacy_manifest,
        selector_policy_path=args.selector_policy,
    )
    verification = verify_loop_snapshot(snapshot)
    print(json.dumps({
        "status": snapshot["status"],
        "fresh_cells": snapshot["fresh_cell_count"],
        "expected_cells": snapshot["expected_cell_count"],
        "expected_lanes": snapshot["expected_lane_count"],
        "migration_status": snapshot["matrix_migration_status"],
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
