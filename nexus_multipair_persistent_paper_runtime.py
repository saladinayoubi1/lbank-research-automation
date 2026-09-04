"""Persistent four-symbol NEXUS Paper loop over the accepted v2 matrix.

This bounded maintenance adapter promotes the scheduled Paper runtime from the
legacy BTC/ETH matrix to the already-proven BTC/ETH/SOL/XRP v2 surface. Legacy
engines remain the execution primitives; this module supplies exact v2 state
migration and 12-cell verification at orchestration boundaries that still carry
legacy six-cell verifiers.

Authority remains Research/Backtest/Paper only. No Live, private credential,
real exchange order, or automatic promotion authority is introduced.
"""
from __future__ import annotations

import argparse
import json
import re
import time
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
from typing import Any, Iterator, Mapping

import nexus_demo_paper_performance_refresh as performance_refresh
import nexus_demo_regime_cycle as demo_regime
import nexus_demo_strategy_matrix as legacy_matrix
import nexus_multipair_demo_strategy_matrix as multipair_matrix
import nexus_persistent_paper_trading_loop as legacy_loop
import nexus_public_regime_cycle as public_regime
import nexus_regime_selected_exposure_increase as exposure_increase
import nexus_regime_selected_position_rebalance as rebalance
from nexus_demo_paper_position_maintenance import run_position_maintenance
from scripts.nexus_strategy_discovery_controller import build_status as build_discovery_status


EXPECTED_SYMBOLS = tuple(multipair_matrix.APPROVED_SYMBOLS)
EXPECTED_TIMEFRAMES = tuple(multipair_matrix.TIMEFRAMES)
EXPECTED_FAMILIES = tuple(multipair_matrix.FAMILIES)
EXPECTED_CELLS = len(EXPECTED_SYMBOLS) * len(EXPECTED_TIMEFRAMES)
EXPECTED_LANES = EXPECTED_CELLS * len(EXPECTED_FAMILIES)
_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class MultiPairPersistentPaperRuntimeError(RuntimeError):
    pass


def _identity_set() -> set[tuple[str, str]]:
    return {
        (symbol, timeframe)
        for symbol in EXPECTED_SYMBOLS
        for timeframe in EXPECTED_TIMEFRAMES
    }


def verify_regime_cycle_v2(value: Mapping[str, Any]) -> dict[str, Any]:
    checks = {
        "schema": False,
        "digest": False,
        "shape": False,
        "authority": False,
        "cells": False,
    }
    try:
        core = dict(value)
        claimed = core.pop("cycle_digest", None)
        cells = core.get("cells")
        identities = {
            (str(row.get("symbol")), str(row.get("timeframe")))
            for row in cells
            if isinstance(row, Mapping)
        } if isinstance(cells, list) else set()
        checks["schema"] = core.get("schema_version") == demo_regime.SCHEMA
        checks["digest"] = isinstance(claimed, str) and claimed == demo_regime._digest(core)
        checks["shape"] = bool(
            core.get("expected_cell_count") == EXPECTED_CELLS
            and core.get("verified_cell_count") == EXPECTED_CELLS
            and isinstance(cells, list)
            and len(cells) == EXPECTED_CELLS
            and identities == _identity_set()
        )
        checks["authority"] = bool(
            core.get("paper_only") is True
            and core.get("live_trading_authority") is False
            and core.get("private_credentials_used") is False
            and core.get("automatic_strategy_promotion") is False
            and core.get("deterministic_risk_final_authority") is True
            and core.get("frozen_prospective_hour4_lane_mutated") is False
        )
        checks["cells"] = bool(
            isinstance(cells, list)
            and all(
                isinstance(row, Mapping)
                and row.get("schema_version") == demo_regime.CELL_SCHEMA
                and row.get("paper_only") is True
                and row.get("live_trading_authority") is False
                and row.get("private_credentials_used") is False
                and row.get("automatic_strategy_promotion") is False
                and row.get("deterministic_risk_final_authority") is True
                and isinstance(row.get("cell_digest"), str)
                and row["cell_digest"] == demo_regime._digest(
                    {key: item for key, item in row.items() if key != "cell_digest"}
                )
                for row in cells
            )
        )
    except (KeyError, TypeError, ValueError):
        pass
    return {"decision": "pass" if all(checks.values()) else "reject", "checks": checks}


def _validate_regime_snapshot_v2(
    value: Mapping[str, Any], source_sha: str
) -> list[Mapping[str, Any]]:
    verification = verify_regime_cycle_v2(value)
    cells = value.get("cells") if isinstance(value, Mapping) else None
    if (
        verification.get("decision") != "pass"
        or value.get("source_sha") != source_sha
        or not isinstance(cells, list)
    ):
        raise rebalance.RegimeSelectedRebalanceError(
            "v2 regime snapshot authority/source verification failed"
        )
    return cells


def verify_rebalance_v2(value: Mapping[str, Any]) -> dict[str, Any]:
    checks = {
        "schema": False,
        "digest": False,
        "shape": False,
        "authority": False,
        "risk_reducing_only": False,
        "cell_digests": False,
        "action_digests": False,
        "mission_truth": False,
    }
    try:
        core = dict(value)
        claimed = core.pop("rebalance_digest", None)
        cells = core.get("cells")
        identities = {
            (str(cell.get("symbol")), str(cell.get("timeframe")))
            for cell in cells
            if isinstance(cell, Mapping)
        } if isinstance(cells, list) else set()
        checks["schema"] = core.get("schema_version") == rebalance.SCHEMA
        checks["digest"] = isinstance(claimed, str) and claimed == rebalance._digest(core)
        checks["shape"] = bool(
            core.get("cell_count") == EXPECTED_CELLS
            and isinstance(cells, list)
            and len(cells) == EXPECTED_CELLS
            and identities == _identity_set()
        )
        checks["authority"] = bool(
            core.get("paper_only") is True
            and core.get("live_trading_authority") is False
            and core.get("private_credentials_used") is False
            and core.get("automatic_strategy_promotion") is False
            and core.get("deterministic_risk_final_authority") is True
        )
        checks["risk_reducing_only"] = bool(
            core.get("exposure_increased") is False
            and all(
                isinstance(cell, Mapping) and cell.get("exposure_increased") is False
                for cell in cells
            )
        )
        checks["cell_digests"] = bool(
            all(
                isinstance(cell, Mapping)
                and cell.get("schema_version") == rebalance.CELL_SCHEMA
                and isinstance(cell.get("cell_rebalance_digest"), str)
                and cell["cell_rebalance_digest"] == rebalance._digest(
                    {key: item for key, item in cell.items() if key != "cell_rebalance_digest"}
                )
                for cell in cells
            )
        )
        allowed_actions = {
            "FLAT",
            "HELD",
            "REDUCED",
            "CLOSED",
            "HOLD_INCREASE_PENDING_FRESH_RISK",
        }
        checks["action_digests"] = bool(
            all(
                isinstance(action, Mapping)
                and action.get("schema_version") == rebalance.ACTION_SCHEMA
                and action.get("action") in allowed_actions
                and action.get("paper_only") is True
                and action.get("live_trading_authority") is False
                and action.get("exposure_increased") is False
                and isinstance(action.get("action_digest"), str)
                and action["action_digest"] == rebalance._digest(
                    {key: item for key, item in action.items() if key != "action_digest"}
                )
                for cell in cells
                for action in cell.get("actions", [])
            )
        )
        checks["mission_truth"] = bool(
            core.get("risk_reducing_rebalance_operational") is True
            and core.get("exposure_increase_operational") is False
            and core.get("regime_selected_rebalance_operational") is False
            and core.get("remaining_core_gap")
            == "REGIME_SELECTED_EXPOSURE_INCREASE_WITH_FRESH_RISK"
        )
    except (KeyError, TypeError, ValueError):
        pass
    return {"decision": "pass" if all(checks.values()) else "reject", "checks": checks}


def verify_exposure_increase_v2(value: Mapping[str, Any]) -> dict[str, Any]:
    checks = {
        "schema": False,
        "digest": False,
        "shape": False,
        "authority": False,
        "cell_digests": False,
        "action_digests": False,
        "fresh_risk": False,
        "counts": False,
    }
    try:
        core = dict(value)
        claimed = core.pop("increase_digest", None)
        cells = core.get("cells")
        identities = {
            (str(cell.get("symbol")), str(cell.get("timeframe")))
            for cell in cells
            if isinstance(cell, Mapping)
        } if isinstance(cells, list) else set()
        checks["schema"] = core.get("schema_version") == exposure_increase.SCHEMA
        checks["digest"] = isinstance(claimed, str) and claimed == exposure_increase._digest(core)
        checks["shape"] = bool(
            core.get("cell_count") == EXPECTED_CELLS
            and isinstance(cells, list)
            and len(cells) == EXPECTED_CELLS
            and identities == _identity_set()
        )
        checks["authority"] = bool(
            core.get("paper_only") is True
            and core.get("live_trading_authority") is False
            and core.get("private_credentials_used") is False
            and core.get("automatic_strategy_promotion") is False
            and core.get("deterministic_risk_final_authority") is True
            and core.get("fresh_deterministic_risk_required") is True
            and core.get("unauthorized_exposure_increase") is False
        )
        checks["cell_digests"] = bool(
            all(
                isinstance(cell, Mapping)
                and cell.get("schema_version") == exposure_increase.CELL_SCHEMA
                and cell.get("source_sha") == core.get("source_sha")
                and cell.get("paper_only") is True
                and cell.get("live_trading_authority") is False
                and cell.get("unauthorized_exposure_increase") is False
                and cell.get("action_count") == len(cell.get("actions", []))
                and isinstance(cell.get("cell_increase_digest"), str)
                and cell["cell_increase_digest"] == exposure_increase._digest(
                    {key: item for key, item in cell.items() if key != "cell_increase_digest"}
                )
                for cell in cells
            )
        )
        allowed = {
            "INCREASED_WITH_FRESH_RISK",
            "INCREASE_BLOCKED_BY_DETERMINISTIC_RISK",
            "NO_INCREASE_AFTER_POST_CLOSE_SIZING",
        }
        actions = [
            action
            for cell in cells
            for action in cell.get("actions", [])
        ]
        checks["action_digests"] = bool(
            all(
                isinstance(action, Mapping)
                and action.get("schema_version") == exposure_increase.ACTION_SCHEMA
                and action.get("status") in allowed
                and action.get("paper_only") is True
                and action.get("live_trading_authority") is False
                and action.get("fresh_deterministic_risk_required") is True
                and action.get("unauthorized_exposure_increase") is False
                and isinstance(action.get("action_digest"), str)
                and action["action_digest"] == exposure_increase._digest(
                    {key: item for key, item in action.items() if key != "action_digest"}
                )
                for action in actions
            )
        )
        checks["fresh_risk"] = bool(
            core.get("exposure_increase_operational") is True
            and all(
                action.get("status") != "INCREASED_WITH_FRESH_RISK"
                or (
                    action.get("open_risk_allowed") is True
                    and action.get("risk_replay_verified") is True
                    and action.get("journal_committed") is True
                    and exposure_increase._decimal(
                        action.get("final_quantity"), "final_quantity"
                    )
                    > exposure_increase._decimal(
                        action.get("initial_quantity"), "initial_quantity"
                    )
                )
                for action in actions
            )
        )
        checks["counts"] = bool(
            core.get("pending_count")
            == sum(cell.get("pending_count", 0) for cell in cells)
            and core.get("increased_count")
            == sum(
                action.get("status") == "INCREASED_WITH_FRESH_RISK"
                for action in actions
            )
            and core.get("risk_blocked_count")
            == sum(
                action.get("status") == "INCREASE_BLOCKED_BY_DETERMINISTIC_RISK"
                for action in actions
            )
            and core.get("no_increase_count")
            == sum(
                action.get("status") == "NO_INCREASE_AFTER_POST_CLOSE_SIZING"
                for action in actions
            )
        )
    except (
        KeyError,
        TypeError,
        ValueError,
        exposure_increase.RegimeSelectedExposureIncreaseError,
    ):
        pass
    return {"decision": "pass" if all(checks.values()) else "reject", "checks": checks}


@contextmanager
def _v2_regime_verifier_scope() -> Iterator[None]:
    bindings = [
        (demo_regime, "verify_cycle_snapshot", verify_regime_cycle_v2),
        (public_regime, "verify_cycle_snapshot", verify_regime_cycle_v2),
        (rebalance, "_validate_regime_snapshot", _validate_regime_snapshot_v2),
        (rebalance, "verify_regime_selected_rebalance", verify_rebalance_v2),
        (public_regime, "verify_regime_selected_rebalance", verify_rebalance_v2),
        (exposure_increase, "verify_regime_selected_rebalance", verify_rebalance_v2),
        (
            exposure_increase,
            "verify_regime_selected_exposure_increase",
            verify_exposure_increase_v2,
        ),
        (
            public_regime,
            "verify_regime_selected_exposure_increase",
            verify_exposure_increase_v2,
        ),
    ]
    originals = [
        (module, name, getattr(module, name))
        for module, name, _replacement in bindings
    ]
    for module, name, replacement in bindings:
        setattr(module, name, replacement)
    try:
        yield
    finally:
        for module, name, original in originals:
            setattr(module, name, original)


def run_performance_refresh_v2(
    *,
    manifest: Mapping[str, Any],
    state_root: str | Path,
    source_sha: str,
) -> dict[str, Any]:
    root = Path(state_root).resolve()
    rows: list[dict[str, Any]] = []
    for symbol in manifest["symbols"]:
        for timeframe in manifest["timeframes"]:
            cell_root = root / "cells" / symbol.lower() / timeframe
            ledger_path = cell_root / "supervisor-ledger.json"
            if ledger_path.is_symlink() or not ledger_path.is_file():
                raise MultiPairPersistentPaperRuntimeError(
                    "Supervisor ledger is unavailable"
                )
            ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
            if ledger.get("source_sha") != source_sha:
                raise MultiPairPersistentPaperRuntimeError(
                    "Supervisor ledger source SHA mismatch"
                )
            projection = performance_refresh.refresh_cell_performance(
                cell_root=cell_root,
                ledger=ledger,
            )
            rows.append(
                {
                    "symbol": symbol,
                    "timeframe": timeframe,
                    "strategy_count": projection["strategy_count"],
                    "status_counts": projection["status_counts"],
                    "projection_digest": projection["projection_digest"],
                }
            )

    state_path = root / "matrix-state.json"
    snapshot_path = root / "demo" / "strategy-matrix.json"
    state = legacy_matrix.load_state(state_path, manifest)
    if snapshot_path.is_symlink() or not snapshot_path.is_file():
        raise MultiPairPersistentPaperRuntimeError(
            "strategy matrix snapshot is unavailable"
        )
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    if multipair_matrix.verify_v2_snapshot(
        snapshot,
        manifest=manifest,
        state=state,
    ).get("decision") != "pass":
        raise MultiPairPersistentPaperRuntimeError(
            "v2 matrix snapshot is not verified before refresh"
        )
    if (
        snapshot.get("source_sha") != source_sha
        or snapshot.get("status") != "VERIFIED"
        or snapshot.get("state_digest") != state.get("state_digest")
    ):
        raise MultiPairPersistentPaperRuntimeError(
            "v2 matrix state/snapshot binding is stale"
        )

    expected = _identity_set()
    row_by_cell = {
        (str(row["symbol"]), str(row["timeframe"])): row
        for row in rows
    }
    cells = state.get("cells")
    cell_identities = {
        (str(row.get("symbol")), str(row.get("timeframe")))
        for row in cells.values()
        if isinstance(row, Mapping)
    } if isinstance(cells, dict) else set()
    if (
        not isinstance(cells, dict)
        or cell_identities != expected
        or set(row_by_cell) != expected
    ):
        raise MultiPairPersistentPaperRuntimeError(
            "performance refresh does not bind exact v2 surface"
        )

    rebound_state = deepcopy(state)
    for cell_id, cell in rebound_state["cells"].items():
        symbol, timeframe = cell_id.split(":", 1)
        row = row_by_cell[(symbol, timeframe)]
        projection_digest = row.get("projection_digest")
        status_counts = row.get("status_counts")
        if (
            cell.get("status") != "VERIFIED"
            or cell.get("source_sha") != source_sha
            or not isinstance(projection_digest, str)
            or not _SHA256_RE.fullmatch(projection_digest)
            or not isinstance(status_counts, Mapping)
        ):
            raise MultiPairPersistentPaperRuntimeError(
                f"invalid v2 performance binding: {cell_id}"
            )
        cell["analysis_digest"] = projection_digest
        cell["analysis_status_counts"] = dict(status_counts)

    state_core = dict(rebound_state)
    state_core.pop("state_digest", None)
    rebound_state["state_digest"] = legacy_matrix._digest(state_core)
    snapshot_core = dict(snapshot)
    snapshot_core.pop("snapshot_digest", None)
    snapshot_core["state_digest"] = rebound_state["state_digest"]
    rebound_snapshot = {
        **snapshot_core,
        "snapshot_digest": legacy_matrix._digest(snapshot_core),
    }
    if multipair_matrix.verify_v2_snapshot(
        rebound_snapshot,
        manifest=manifest,
        state=rebound_state,
    ).get("decision") != "pass":
        raise MultiPairPersistentPaperRuntimeError(
            "rebound v2 matrix snapshot failed verification"
        )
    performance_refresh._atomic_json(state_path, rebound_state)
    performance_refresh._atomic_json(snapshot_path, rebound_snapshot)

    core = {
        "schema_version": performance_refresh.SCHEMA,
        "source_sha": source_sha,
        "cell_count": len(rows),
        "rows": rows,
        "paper_only": True,
        "live_trading_authority": False,
        "automatic_strategy_promotion": False,
    }
    result = {
        **core,
        "refresh_digest": performance_refresh._digest(core),
    }
    performance_refresh._atomic_json(
        root / "demo" / "paper-performance-refresh.json",
        result,
    )
    return {
        **result,
        "_rebound_matrix_state": rebound_state,
        "_rebound_matrix_snapshot": rebound_snapshot,
    }


def _load_existing_regime_v2(
    path: Path,
    source_sha: str,
    boundary_digest: str,
) -> dict[str, Any] | None:
    if not path.exists():
        return None
    value = legacy_loop._read_json(path)
    if (
        value.get("source_sha") != source_sha
        or value.get("data_mode") != public_regime.PUBLIC_DATA_MODE
        or verify_regime_cycle_v2(value).get("decision") != "pass"
    ):
        return None
    contexts = value.get("context_digests")
    if not isinstance(contexts, Mapping) or set(contexts) != set(EXPECTED_SYMBOLS):
        return None
    if (
        not isinstance(boundary_digest, str)
        or not _SHA256_RE.fullmatch(boundary_digest)
    ):
        return None
    return value


def run_persistent_cycle_v2(
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
        raise MultiPairPersistentPaperRuntimeError(
            "source_sha must be an exact Git SHA"
        )
    if not str(run_id).isdigit():
        raise MultiPairPersistentPaperRuntimeError("run_id must be numeric")
    if isinstance(now_ms, bool) or not isinstance(now_ms, int) or now_ms <= 0:
        raise MultiPairPersistentPaperRuntimeError("now_ms must be positive")

    repo_root = Path(repo_root).resolve()
    root = Path(state_root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    manifest = multipair_matrix.load_manifest(manifest_path)
    if (
        tuple(manifest["symbols"]) != EXPECTED_SYMBOLS
        or tuple(manifest["timeframes"]) != EXPECTED_TIMEFRAMES
        or tuple(manifest["families"]) != EXPECTED_FAMILIES
    ):
        raise MultiPairPersistentPaperRuntimeError(
            "persistent v2 manifest escaped approved surface"
        )
    policy = legacy_loop._load_policy(selector_policy_path)
    loop_state_path = root / "persistent-loop-state.json"
    loop_state = legacy_loop.load_loop_state(loop_state_path)

    matrix_state_path = root / "matrix-state.json"
    matrix_state, migration = multipair_matrix.load_or_migrate_state(
        matrix_state_path,
        manifest,
        legacy_manifest_path=legacy_manifest_path,
    )
    if migration is not None:
        if (
            migration.get("new_symbols") != ["SOLUSDT", "XRPUSDT"]
            or migration.get("new_symbol_inherited_cell_count") != 0
            or migration.get("live_trading_authority") is not False
            or migration.get("automatic_strategy_promotion") is not False
        ):
            raise MultiPairPersistentPaperRuntimeError(
                "v1-to-v2 state migration widened evidence or authority"
            )
        legacy_loop._atomic_json(
            root / "demo" / "matrix-v2-migration.json",
            migration,
        )

    next_matrix_state, matrix_snapshot = legacy_matrix.run_matrix_cycle(
        manifest=manifest,
        state=matrix_state,
        state_root=root,
        source_sha=source_sha,
        run_id=str(run_id),
        now_ms=now_ms,
        data_mode=public_regime.PUBLIC_DATA_MODE,
        dataset_sha256=None,
    )
    if multipair_matrix.verify_v2_snapshot(
        matrix_snapshot,
        manifest=manifest,
        state=next_matrix_state,
    ).get("decision") != "pass":
        raise MultiPairPersistentPaperRuntimeError(
            "public v2 matrix snapshot failed verification"
        )
    legacy_matrix._atomic_json(matrix_state_path, next_matrix_state)
    legacy_matrix._atomic_json(
        root / "demo" / "strategy-matrix.json",
        matrix_snapshot,
    )

    fresh_cells = legacy_loop._fresh_cells(next_matrix_state, source_sha)
    performance: dict[str, Any] | None = None
    maintenance: dict[str, Any] | None = None
    regime: dict[str, Any] | None = None
    regime_status = "WAITING_FOR_FRESH_CELLS"
    boundary_digest: str | None = None

    if len(fresh_cells) == EXPECTED_CELLS:
        maintenance = run_position_maintenance(
            manifest=manifest,
            state_root=root,
            source_sha=source_sha,
        )
        if (
            maintenance.get("exposure_increased") is not False
            or maintenance.get("cell_count") != EXPECTED_CELLS
        ):
            raise MultiPairPersistentPaperRuntimeError(
                "v2 position maintenance widened exposure or surface"
            )
        performance = run_performance_refresh_v2(
            manifest=manifest,
            state_root=root,
            source_sha=source_sha,
        )
        next_matrix_state = performance.pop("_rebound_matrix_state")
        matrix_snapshot = performance.pop("_rebound_matrix_snapshot")
        if performance.get("cell_count") != EXPECTED_CELLS:
            raise MultiPairPersistentPaperRuntimeError(
                "v2 performance refresh surface mismatch"
            )
        boundary = legacy_loop._regime_boundary(
            next_matrix_state,
            list(manifest["symbols"]),
        )
        boundary_digest = legacy_loop._digest(boundary)
        regime_path = root / "demo" / "regime-cycle.json"
        can_reuse = (
            loop_state.get("last_source_sha") == source_sha
            and loop_state.get("last_regime_boundary_digest") == boundary_digest
        )
        existing = (
            _load_existing_regime_v2(
                regime_path,
                source_sha,
                boundary_digest,
            )
            if can_reuse
            else None
        )
        if existing is not None:
            regime = existing
            regime_status = "NO_NEW_4H_BOUNDARY"
        else:
            with _v2_regime_verifier_scope():
                regime = public_regime.run_public_regime_cycle(
                    manifest=manifest,
                    matrix_state=next_matrix_state,
                    state_root=root,
                    source_sha=source_sha,
                    selector_policy=policy,
                )
            if verify_regime_cycle_v2(regime).get("decision") != "pass":
                raise MultiPairPersistentPaperRuntimeError(
                    "public v2 regime cycle failed verification"
                )
            regime_status = "VERIFIED"

    discovery = build_discovery_status(repo_root)
    if discovery.get("controller_verified") is not True:
        raise MultiPairPersistentPaperRuntimeError(
            "Strategy Discovery controller is not verified"
        )
    research_required = legacy_loop._research_required(regime, performance)
    rebalance_operational = bool(
        isinstance(regime, Mapping)
        and regime.get("regime_selected_rebalance_operational") is True
        and regime.get("regime_selected_exposure_increase_operational") is True
    )
    performance_feedback_operational = (
        legacy_loop._performance_health_feedback_operational(
            performance,
            EXPECTED_CELLS,
        )
    )
    health_trigger_requested = bool(
        research_required
        and regime_status == "VERIFIED"
        and rebalance_operational
    )

    if len(fresh_cells) != EXPECTED_CELLS:
        remaining_core_gap = "WAITING_FOR_FRESH_CELLS"
    elif not rebalance_operational:
        remaining_core_gap = "REGIME_SELECTED_POSITION_CLOSE_AND_RESIZE"
    else:
        remaining_core_gap = "RUNTIME_EVIDENCE_AND_DISCOVERY_FEEDBACK_PROOF"

    next_state_core = {
        "schema_version": legacy_loop.STATE_SCHEMA,
        "cycle_count": int(loop_state["cycle_count"]) + 1,
        "last_source_sha": source_sha,
        "last_run_id": str(run_id),
        "last_now_ms": now_ms,
        "last_regime_boundary_digest": boundary_digest,
        "last_regime_cycle_digest": (
            regime.get("cycle_digest")
            if regime
            else loop_state.get("last_regime_cycle_digest")
        ),
        "paper_only": True,
        "live_trading_authority": False,
        "private_credentials_used": False,
        "automatic_strategy_promotion": False,
    }
    next_loop_state = {
        **next_state_core,
        "state_digest": legacy_loop._digest(next_state_core),
    }
    legacy_loop._atomic_json(loop_state_path, next_loop_state)

    status = (
        "PAPER_LOOP_ACTIVE"
        if len(fresh_cells) == EXPECTED_CELLS
        else "WAITING_FOR_FRESH_CELLS"
    )
    core = {
        "schema_version": legacy_loop.SCHEMA,
        "source_sha": source_sha,
        "run_id": str(run_id),
        "now_ms": now_ms,
        "status": status,
        "data_mode": public_regime.PUBLIC_DATA_MODE,
        "matrix_snapshot_digest": matrix_snapshot["snapshot_digest"],
        "expected_cell_count": EXPECTED_CELLS,
        "fresh_cell_count": len(fresh_cells),
        "fresh_cells": fresh_cells,
        "expected_lane_count": EXPECTED_LANES,
        "regime_status": regime_status,
        "regime_cycle_digest": regime.get("cycle_digest") if regime else None,
        "maintenance_digest": (
            maintenance.get("maintenance_digest") if maintenance else None
        ),
        "performance_refresh_digest": (
            performance.get("refresh_digest") if performance else None
        ),
        "performance_health_feedback_operational": (
            performance_feedback_operational
        ),
        "strategy_discovery_controller_verified": True,
        "strategy_discovery_next_action": discovery.get(
            "next_research_action"
        ),
        "strategy_discovery_ready_stage_count": discovery.get(
            "summary", {}
        ).get("ready_search_stage_count"),
        "strategy_research_required": research_required,
        "strategy_discovery_health_trigger_requested": (
            health_trigger_requested
        ),
        "strategy_discovery_health_trigger_contract": (
            "successful_paper_loop_new_4h_boundary_only"
        ),
        "strategy_discovery_rotation": (
            "automatic_daily_and_health_driven_bounded_rotation"
        ),
        "persistent_state_digest": next_loop_state["state_digest"],
        "comparison_position_lifecycle": "OPEN_HOLD_RISK_REDUCING_CLOSE",
        "regime_selected_rebalance_operational": rebalance_operational,
        "regime_selected_exposure_increase_operational": bool(
            isinstance(regime, Mapping)
            and regime.get("regime_selected_exposure_increase_operational")
            is True
        ),
        "remaining_core_gap": remaining_core_gap,
        "trading_engine_complete": False,
        "paper_only": True,
        "live_trading_authority": False,
        "private_credentials_used": False,
        "automatic_strategy_promotion": False,
        "deterministic_risk_final_authority": True,
    }
    snapshot = {
        **core,
        "loop_digest": legacy_loop._digest(core),
    }
    legacy_loop._atomic_json(
        root / "demo" / "persistent-paper-trading-loop.json",
        snapshot,
    )
    return snapshot


def verify_loop_snapshot_v2(value: Mapping[str, Any]) -> dict[str, Any]:
    checks = {
        "schema": False,
        "digest": False,
        "authority": False,
        "shape": False,
        "status": False,
        "mission_truth": False,
    }
    try:
        core = dict(value)
        claimed = core.pop("loop_digest", None)
        fresh_cells = core.get("fresh_cells")
        expected_ids = {
            f"{symbol}:{timeframe}"
            for symbol, timeframe in _identity_set()
        }
        checks["schema"] = core.get("schema_version") == legacy_loop.SCHEMA
        checks["digest"] = (
            isinstance(claimed, str)
            and claimed == legacy_loop._digest(core)
        )
        checks["authority"] = bool(
            core.get("paper_only") is True
            and core.get("live_trading_authority") is False
            and core.get("private_credentials_used") is False
            and core.get("automatic_strategy_promotion") is False
            and core.get("deterministic_risk_final_authority") is True
        )
        checks["shape"] = bool(
            core.get("expected_cell_count") == EXPECTED_CELLS
            and core.get("expected_lane_count") == EXPECTED_LANES
            and isinstance(core.get("fresh_cell_count"), int)
            and not isinstance(core.get("fresh_cell_count"), bool)
            and 0 <= core["fresh_cell_count"] <= EXPECTED_CELLS
            and isinstance(fresh_cells, list)
            and len(fresh_cells) == core["fresh_cell_count"]
            and set(fresh_cells).issubset(expected_ids)
            and isinstance(
                core.get("performance_health_feedback_operational"), bool
            )
            and isinstance(
                core.get("strategy_discovery_health_trigger_requested"), bool
            )
            and isinstance(
                core.get("regime_selected_rebalance_operational"), bool
            )
            and isinstance(
                core.get("regime_selected_exposure_increase_operational"), bool
            )
        )
        status = core.get("status")
        checks["status"] = bool(
            (
                status == "WAITING_FOR_FRESH_CELLS"
                and core.get("fresh_cell_count") < EXPECTED_CELLS
            )
            or (
                status == "PAPER_LOOP_ACTIVE"
                and core.get("fresh_cell_count") == EXPECTED_CELLS
                and core.get("regime_status")
                in {"VERIFIED", "NO_NEW_4H_BOUNDARY"}
                and isinstance(core.get("regime_cycle_digest"), str)
                and _SHA256_RE.fullmatch(core["regime_cycle_digest"])
            )
        )
        if status == "WAITING_FOR_FRESH_CELLS":
            mission_state_valid = (
                core.get("remaining_core_gap") == "WAITING_FOR_FRESH_CELLS"
            )
        elif core.get("regime_selected_rebalance_operational") is True:
            mission_state_valid = bool(
                core.get("regime_selected_exposure_increase_operational")
                is True
                and core.get("performance_health_feedback_operational") is True
                and core.get("remaining_core_gap")
                == "RUNTIME_EVIDENCE_AND_DISCOVERY_FEEDBACK_PROOF"
            )
        else:
            mission_state_valid = (
                core.get("remaining_core_gap")
                == "REGIME_SELECTED_POSITION_CLOSE_AND_RESIZE"
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
    except (KeyError, TypeError, ValueError):
        pass
    return {
        "decision": "pass" if all(checks.values()) else "reject",
        "checks": checks,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path("."))
    parser.add_argument("--state-root", type=Path, required=True)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--now-ms", type=int, default=None)
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
    now_ms = (
        int(time.time() * 1000)
        if args.now_ms is None
        else args.now_ms
    )
    result = run_persistent_cycle_v2(
        repo_root=args.repo_root,
        state_root=args.state_root,
        source_sha=args.source_sha,
        run_id=str(args.run_id),
        now_ms=now_ms,
        manifest_path=args.manifest,
        legacy_manifest_path=args.legacy_manifest,
        selector_policy_path=args.selector_policy,
    )
    verification = verify_loop_snapshot_v2(result)
    if verification.get("decision") != "pass":
        raise MultiPairPersistentPaperRuntimeError(
            f"persistent v2 loop snapshot rejected: {verification}"
        )
    print(
        json.dumps(
            {
                "status": result["status"],
                "expected_cell_count": result["expected_cell_count"],
                "expected_lane_count": result["expected_lane_count"],
                "fresh_cell_count": result["fresh_cell_count"],
                "regime_status": result["regime_status"],
                "loop_digest": result["loop_digest"],
                "paper_only": True,
                "live_trading_authority": False,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
