"""Persistent autonomous NEXUS Paper trading loop over public Bybit closed candles.

This is the mission-oriented runtime controller.  It reuses the existing 2 x 3 x 3
Strategy Paper matrix, position maintenance, performance/drift evidence, synchronized
regime selector, Deterministic Risk and isolated Paper engine.  It never grants Live
trading authority, never accepts private exchange credentials and never promotes a
strategy automatically.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import time
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Mapping

from nexus_demo_paper_performance_refresh import run_performance_refresh
from nexus_demo_paper_position_maintenance import run_position_maintenance
from nexus_demo_regime_cycle import _common_as_of, verify_cycle_snapshot
from nexus_demo_strategy_matrix import (
    _atomic_json as _matrix_atomic_json,
    load_manifest,
    load_state,
    run_matrix_cycle,
    verify_snapshot,
)
from nexus_public_regime_cycle import PUBLIC_DATA_MODE, run_public_regime_cycle
from nexus_regime_strategy_selector import validate_policy
from scripts.nexus_strategy_discovery_controller import build_status as build_discovery_status


SCHEMA = "nexus.persistent-paper-trading-loop.v1"
STATE_SCHEMA = "nexus.persistent-paper-trading-loop-state.v1"
_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_MAX_JSON_BYTES = 20_000_000


class PersistentPaperTradingLoopError(RuntimeError):
    pass


def _canonical(value: Any) -> bytes:
    try:
        return json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise PersistentPaperTradingLoopError("loop evidence is not canonical JSON") from exc


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    target = Path(path).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + f".{os.getpid()}.tmp")
    payload = json.dumps(
        dict(value), indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False
    ) + "\n"
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, target)


def _read_json(path: Path) -> dict[str, Any]:
    path = Path(path)
    if path.is_symlink() or not path.is_file() or path.stat().st_size > _MAX_JSON_BYTES:
        raise PersistentPaperTradingLoopError(f"unsafe or missing state: {path.name}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PersistentPaperTradingLoopError(f"unreadable state: {path.name}") from exc
    if not isinstance(value, dict):
        raise PersistentPaperTradingLoopError(f"state is not an object: {path.name}")
    return value


def _empty_loop_state() -> dict[str, Any]:
    core = {
        "schema_version": STATE_SCHEMA,
        "cycle_count": 0,
        "last_source_sha": None,
        "last_run_id": None,
        "last_now_ms": None,
        "last_regime_boundary_digest": None,
        "last_regime_cycle_digest": None,
        "paper_only": True,
        "live_trading_authority": False,
        "private_credentials_used": False,
        "automatic_strategy_promotion": False,
    }
    return {**core, "state_digest": _digest(core)}


def load_loop_state(path: Path) -> dict[str, Any]:
    if not Path(path).exists():
        return _empty_loop_state()
    raw = _read_json(path)
    core = dict(raw)
    claimed = core.pop("state_digest", None)
    if (
        core.get("schema_version") != STATE_SCHEMA
        or isinstance(core.get("cycle_count"), bool)
        or not isinstance(core.get("cycle_count"), int)
        or core["cycle_count"] < 0
        or core.get("paper_only") is not True
        or core.get("live_trading_authority") is not False
        or core.get("private_credentials_used") is not False
        or core.get("automatic_strategy_promotion") is not False
        or claimed != _digest(core)
    ):
        raise PersistentPaperTradingLoopError("persistent loop state verification failed")
    return raw


def _load_policy(path: Path) -> dict[str, Any]:
    return validate_policy(_read_json(path))


def _fresh_cells(matrix_state: Mapping[str, Any], source_sha: str) -> list[str]:
    cells = matrix_state.get("cells")
    if not isinstance(cells, Mapping):
        return []
    return sorted(
        str(cell_id)
        for cell_id, row in cells.items()
        if isinstance(row, Mapping)
        and row.get("status") == "VERIFIED"
        and row.get("source_sha") == source_sha
    )


def _regime_boundary(matrix_state: Mapping[str, Any], symbols: list[str]) -> dict[str, int]:
    return {symbol: _common_as_of(matrix_state, symbol) for symbol in symbols}


def _decimal(value: Any) -> Decimal:
    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise PersistentPaperTradingLoopError("non-decimal allocation evidence") from exc
    if not number.is_finite():
        raise PersistentPaperTradingLoopError("non-finite allocation evidence")
    return number


def _research_required(regime: Mapping[str, Any] | None, performance: Mapping[str, Any] | None) -> bool:
    status_counts: list[Mapping[str, Any]] = []
    if isinstance(performance, Mapping):
        for row in performance.get("rows", []):
            if isinstance(row, Mapping) and isinstance(row.get("status_counts"), Mapping):
                status_counts.append(row["status_counts"])
    unhealthy = any(
        int(counts.get("DEGRADED", 0) or 0) > 0
        or int(counts.get("QUARANTINED", 0) or 0) > 0
        for counts in status_counts
    )
    cells = regime.get("cells") if isinstance(regime, Mapping) else None
    all_cash = bool(
        isinstance(cells, list)
        and cells
        and all(_decimal(row.get("cash_weight", "1")) == Decimal("1") for row in cells)
    )
    return unhealthy or all_cash


def _load_existing_regime(path: Path, source_sha: str, boundary_digest: str) -> dict[str, Any] | None:
    if not path.exists():
        return None
    value = _read_json(path)
    if (
        value.get("source_sha") != source_sha
        or value.get("data_mode") != PUBLIC_DATA_MODE
        or verify_cycle_snapshot(value).get("decision") != "pass"
    ):
        return None
    contexts = value.get("context_digests")
    if not isinstance(contexts, Mapping):
        return None
    # Boundary identity is separately persisted by the loop state.  This check
    # prevents a stale regime snapshot from being reused after state loss.
    if not isinstance(boundary_digest, str) or not re.fullmatch(r"[0-9a-f]{64}", boundary_digest):
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
    selector_policy_path: Path,
) -> dict[str, Any]:
    source_sha = str(source_sha).strip().lower()
    if not _SHA_RE.fullmatch(source_sha):
        raise PersistentPaperTradingLoopError("source_sha must be an exact Git SHA")
    if not str(run_id).isdigit():
        raise PersistentPaperTradingLoopError("run_id must be numeric")
    if isinstance(now_ms, bool) or not isinstance(now_ms, int) or now_ms <= 0:
        raise PersistentPaperTradingLoopError("now_ms must be positive")

    repo_root = Path(repo_root).resolve()
    root = Path(state_root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    manifest = load_manifest(manifest_path)
    policy = _load_policy(selector_policy_path)
    loop_state_path = root / "persistent-loop-state.json"
    loop_state = load_loop_state(loop_state_path)

    matrix_state_path = root / "matrix-state.json"
    matrix_state = load_state(matrix_state_path, manifest)
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
    if verify_snapshot(matrix_snapshot).get("decision") != "pass":
        raise PersistentPaperTradingLoopError("public matrix snapshot failed verification")
    _matrix_atomic_json(matrix_state_path, next_matrix_state)
    _matrix_atomic_json(root / "demo" / "strategy-matrix.json", matrix_snapshot)

    expected_cells = len(manifest["symbols"]) * len(manifest["timeframes"])
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
            raise PersistentPaperTradingLoopError("position maintenance increased exposure")
        performance = run_performance_refresh(
            manifest=manifest, state_root=root, source_sha=source_sha
        )
        boundary = _regime_boundary(next_matrix_state, list(manifest["symbols"]))
        boundary_digest = _digest(boundary)
        regime_path = root / "demo" / "regime-cycle.json"
        can_reuse = (
            loop_state.get("last_source_sha") == source_sha
            and loop_state.get("last_regime_boundary_digest") == boundary_digest
        )
        existing = _load_existing_regime(regime_path, source_sha, boundary_digest) if can_reuse else None
        if existing is not None:
            regime = existing
            regime_status = "NO_NEW_4H_BOUNDARY"
        else:
            regime = run_public_regime_cycle(
                manifest=manifest,
                matrix_state=next_matrix_state,
                state_root=root,
                source_sha=source_sha,
                selector_policy=policy,
            )
            if verify_cycle_snapshot(regime).get("decision") != "pass":
                raise PersistentPaperTradingLoopError("public regime cycle failed verification")
            regime_status = "VERIFIED"

    discovery = build_discovery_status(repo_root)
    if discovery.get("controller_verified") is not True:
        raise PersistentPaperTradingLoopError("Strategy Discovery controller is not verified")
    research_required = _research_required(regime, performance)

    next_state_core = {
        "schema_version": STATE_SCHEMA,
        "cycle_count": int(loop_state["cycle_count"]) + 1,
        "last_source_sha": source_sha,
        "last_run_id": str(run_id),
        "last_now_ms": now_ms,
        "last_regime_boundary_digest": boundary_digest,
        "last_regime_cycle_digest": regime.get("cycle_digest") if regime else loop_state.get("last_regime_cycle_digest"),
        "paper_only": True,
        "live_trading_authority": False,
        "private_credentials_used": False,
        "automatic_strategy_promotion": False,
    }
    next_loop_state = {**next_state_core, "state_digest": _digest(next_state_core)}
    _atomic_json(loop_state_path, next_loop_state)

    status = "PAPER_LOOP_ACTIVE" if len(fresh_cells) == expected_cells else "WAITING_FOR_FRESH_CELLS"
    core = {
        "schema_version": SCHEMA,
        "source_sha": source_sha,
        "run_id": str(run_id),
        "now_ms": now_ms,
        "status": status,
        "data_mode": PUBLIC_DATA_MODE,
        "matrix_snapshot_digest": matrix_snapshot["snapshot_digest"],
        "expected_cell_count": expected_cells,
        "fresh_cell_count": len(fresh_cells),
        "fresh_cells": fresh_cells,
        "expected_lane_count": len(manifest["symbols"]) * len(manifest["timeframes"]) * len(manifest["families"]),
        "regime_status": regime_status,
        "regime_cycle_digest": regime.get("cycle_digest") if regime else None,
        "maintenance_digest": maintenance.get("maintenance_digest") if maintenance else None,
        "performance_refresh_digest": performance.get("refresh_digest") if performance else None,
        "strategy_discovery_controller_verified": True,
        "strategy_discovery_next_action": discovery.get("next_research_action"),
        "strategy_discovery_ready_stage_count": discovery.get("summary", {}).get("ready_search_stage_count"),
        "strategy_research_required": research_required,
        "strategy_discovery_rotation": "automatic_daily_bounded_rotation",
        "persistent_state_digest": next_loop_state["state_digest"],
        "comparison_position_lifecycle": "OPEN_HOLD_RISK_REDUCING_CLOSE",
        "regime_selected_rebalance_operational": False,
        "remaining_core_gap": "REGIME_SELECTED_POSITION_CLOSE_AND_RESIZE",
        "trading_engine_complete": False,
        "paper_only": True,
        "live_trading_authority": False,
        "private_credentials_used": False,
        "automatic_strategy_promotion": False,
        "deterministic_risk_final_authority": True,
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
        "status": False,
        "mission_truth": False,
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
            and core.get("automatic_strategy_promotion") is False
            and core.get("deterministic_risk_final_authority") is True
        )
        checks["shape"] = bool(
            core.get("expected_cell_count") == 6
            and core.get("expected_lane_count") == 18
            and isinstance(core.get("fresh_cell_count"), int)
            and 0 <= core["fresh_cell_count"] <= 6
            and isinstance(core.get("fresh_cells"), list)
            and len(core["fresh_cells"]) == core["fresh_cell_count"]
        )
        status = core.get("status")
        checks["status"] = bool(
            (status == "WAITING_FOR_FRESH_CELLS" and core.get("fresh_cell_count") < 6)
            or (
                status == "PAPER_LOOP_ACTIVE"
                and core.get("fresh_cell_count") == 6
                and core.get("regime_status") in {"VERIFIED", "NO_NEW_4H_BOUNDARY"}
                and isinstance(core.get("regime_cycle_digest"), str)
            )
        )
        checks["mission_truth"] = bool(
            core.get("strategy_discovery_controller_verified") is True
            and core.get("regime_selected_rebalance_operational") is False
            and core.get("remaining_core_gap") == "REGIME_SELECTED_POSITION_CLOSE_AND_RESIZE"
            and core.get("trading_engine_complete") is False
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
        "--manifest", type=Path, default=Path("config/nexus-demo-strategy-matrix-v1.json")
    )
    parser.add_argument(
        "--selector-policy", type=Path,
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
        selector_policy_path=args.selector_policy,
    )
    verification = verify_loop_snapshot(snapshot)
    print(json.dumps({
        "status": snapshot["status"],
        "fresh_cells": snapshot["fresh_cell_count"],
        "regime_status": snapshot["regime_status"],
        "strategy_research_required": snapshot["strategy_research_required"],
        "decision": verification["decision"],
        "loop_digest": snapshot["loop_digest"],
    }, sort_keys=True))
    return 0 if verification["decision"] == "pass" else 2


if __name__ == "__main__":
    raise SystemExit(main())
