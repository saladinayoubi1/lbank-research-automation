"""Fail-closed four-symbol extension for the NEXUS Demo Paper strategy matrix.

This module deliberately stages the BTC/ETH -> BTC/ETH/SOL/XRP expansion without
silently reinterpreting durable v1 state. The existing matrix engine remains the
execution primitive; this layer validates the v2 manifest, performs exactly one
bounded migration from digest-valid v1 state, and independently verifies the v2
snapshot/state surface before any result is accepted.

Authority remains Research/Backtest/Paper only. No Live/private-credential or
automatic-promotion authority is introduced here.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any, Mapping

from nexus_demo_strategy_matrix import (
    SNAPSHOT_SCHEMA,
    STATE_SCHEMA,
    DemoStrategyMatrixError,
    _atomic_json,
    _digest,
    load_manifest as load_legacy_manifest,
    load_state as load_matrix_state,
    run_matrix_cycle,
)


SCHEMA = "nexus.demo-strategy-matrix.v2"
MIGRATION_SCHEMA = "nexus.demo-strategy-matrix-migration.v1"
APPROVED_SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT")
LEGACY_SYMBOLS = ("BTCUSDT", "ETHUSDT")
TIMEFRAMES = ("minute15", "hour1", "hour4")
FAMILIES = ("momentum", "trend_breakout", "mean_reversion")
_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
AUTHORITY = {
    "paper_only": True,
    "live_trading_authority": False,
    "private_credentials_allowed": False,
    "automatic_strategy_promotion": False,
    "deterministic_risk_final_authority": True,
}
MIGRATION_POLICY = {
    "from_schema_version": "nexus.demo-strategy-matrix.v1",
    "from_matrix_id": "nexus-demo-btc-eth-3tf-3strategy-v1",
    "preserve_verified_legacy_cells": True,
    "new_symbols_start_without_inherited_evidence": True,
    "silent_state_reinterpretation": False,
}


class MultiPairMatrixError(DemoStrategyMatrixError):
    pass


def _read_json(path: Path) -> dict[str, Any]:
    target = Path(path)
    if target.is_symlink() or not target.is_file() or target.stat().st_size > 1_000_000:
        raise MultiPairMatrixError("multi-pair manifest is unavailable or unsafe")
    try:
        value = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise MultiPairMatrixError("multi-pair manifest is unreadable") from exc
    if not isinstance(value, dict):
        raise MultiPairMatrixError("multi-pair manifest is not an object")
    return value


def load_manifest(path: str | Path) -> dict[str, Any]:
    raw = _read_json(Path(path))
    required = {
        "schema_version",
        "matrix_id",
        "symbols",
        "timeframes",
        "families",
        "history_limit",
        "authority",
        "migration",
    }
    if set(raw) != required or raw.get("schema_version") != SCHEMA:
        raise MultiPairMatrixError("multi-pair manifest schema mismatch")
    if raw.get("matrix_id") != "nexus-demo-btc-eth-sol-xrp-3tf-3strategy-v2":
        raise MultiPairMatrixError("multi-pair matrix_id mismatch")
    if raw.get("symbols") != list(APPROVED_SYMBOLS):
        raise MultiPairMatrixError("multi-pair manifest must contain the approved four-symbol surface")
    if raw.get("timeframes") != list(TIMEFRAMES):
        raise MultiPairMatrixError("multi-pair manifest timeframe surface mismatch")
    if raw.get("families") != list(FAMILIES):
        raise MultiPairMatrixError("multi-pair manifest strategy-family surface mismatch")
    history_limit = raw.get("history_limit")
    if isinstance(history_limit, bool) or not isinstance(history_limit, int) or not 60 <= history_limit <= 500:
        raise MultiPairMatrixError("multi-pair history_limit is outside the bounded range")
    if raw.get("authority") != AUTHORITY:
        raise MultiPairMatrixError("multi-pair authority boundary mismatch")
    if raw.get("migration") != MIGRATION_POLICY:
        raise MultiPairMatrixError("multi-pair migration policy mismatch")
    return raw


def _allowed_cell_ids() -> set[str]:
    return {f"{symbol}:{timeframe}" for symbol in APPROVED_SYMBOLS for timeframe in TIMEFRAMES}


def _allowed_lane_ids() -> set[tuple[str, str, str]]:
    return {
        (symbol, timeframe, family)
        for symbol in APPROVED_SYMBOLS
        for timeframe in TIMEFRAMES
        for family in FAMILIES
    }


def _validate_legacy_cells(cells: Mapping[str, Any]) -> None:
    allowed_ids = {f"{symbol}:{timeframe}" for symbol in LEGACY_SYMBOLS for timeframe in TIMEFRAMES}
    if any(cell_id not in allowed_ids for cell_id in cells):
        raise MultiPairMatrixError("legacy state contains a non-v1 cell")
    for cell_id, raw in cells.items():
        if not isinstance(raw, Mapping):
            raise MultiPairMatrixError("legacy matrix cell is not an object")
        symbol, timeframe = cell_id.split(":", 1)
        if raw.get("cell_id") != cell_id or raw.get("symbol") != symbol or raw.get("timeframe") != timeframe:
            raise MultiPairMatrixError("legacy matrix cell identity mismatch")
        if symbol not in LEGACY_SYMBOLS or timeframe not in TIMEFRAMES:
            raise MultiPairMatrixError("legacy matrix cell escaped the approved v1 surface")
        if raw.get("status") not in {"VERIFIED", "BLOCKED"}:
            raise MultiPairMatrixError("legacy matrix cell status is unsupported")


def _new_state(manifest: Mapping[str, Any]) -> dict[str, Any]:
    core = {
        "schema_version": STATE_SCHEMA,
        "matrix_id": manifest["matrix_id"],
        "manifest_sha256": _digest(manifest),
        "cells": {},
        "paper_only": True,
        "live_trading_authority": False,
        "private_credentials_used": False,
        "automatic_strategy_promotion": False,
    }
    return {**core, "state_digest": _digest(core)}


def migrate_legacy_state(
    *,
    legacy_state: Mapping[str, Any],
    legacy_manifest: Mapping[str, Any],
    target_manifest: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    cells = legacy_state.get("cells")
    if not isinstance(cells, Mapping):
        raise MultiPairMatrixError("legacy state omitted cells")
    _validate_legacy_cells(cells)
    if legacy_manifest.get("schema_version") != MIGRATION_POLICY["from_schema_version"]:
        raise MultiPairMatrixError("legacy manifest schema is not approved for migration")
    if legacy_manifest.get("matrix_id") != MIGRATION_POLICY["from_matrix_id"]:
        raise MultiPairMatrixError("legacy matrix_id is not approved for migration")
    if legacy_manifest.get("symbols") != list(LEGACY_SYMBOLS):
        raise MultiPairMatrixError("legacy manifest symbol surface mismatch")
    if legacy_manifest.get("timeframes") != list(TIMEFRAMES):
        raise MultiPairMatrixError("legacy manifest timeframe surface mismatch")
    if legacy_manifest.get("families") != list(FAMILIES):
        raise MultiPairMatrixError("legacy manifest family surface mismatch")
    if legacy_manifest.get("authority") != AUTHORITY:
        raise MultiPairMatrixError("legacy authority boundary mismatch")

    migrated_core: dict[str, Any] = {
        "schema_version": STATE_SCHEMA,
        "matrix_id": target_manifest["matrix_id"],
        "manifest_sha256": _digest(target_manifest),
        "cells": {key: dict(value) for key, value in sorted(cells.items())},
        "paper_only": True,
        "live_trading_authority": False,
        "private_credentials_used": False,
        "automatic_strategy_promotion": False,
    }
    for optional in ("data_mode", "dataset_sha256"):
        if optional in legacy_state:
            migrated_core[optional] = legacy_state[optional]
    migrated = {**migrated_core, "state_digest": _digest(migrated_core)}

    migration_core = {
        "schema_version": MIGRATION_SCHEMA,
        "from_matrix_id": legacy_manifest["matrix_id"],
        "from_manifest_sha256": _digest(legacy_manifest),
        "from_state_digest": legacy_state["state_digest"],
        "to_matrix_id": target_manifest["matrix_id"],
        "to_manifest_sha256": _digest(target_manifest),
        "to_state_digest": migrated["state_digest"],
        "preserved_cell_ids": sorted(cells),
        "preserved_cell_count": len(cells),
        "new_symbols": [symbol for symbol in APPROVED_SYMBOLS if symbol not in LEGACY_SYMBOLS],
        "new_symbol_inherited_cell_count": 0,
        "paper_only": True,
        "live_trading_authority": False,
        "private_credentials_used": False,
        "automatic_strategy_promotion": False,
    }
    migration = {**migration_core, "migration_digest": _digest(migration_core)}
    return migrated, migration


def load_or_migrate_state(
    state_path: str | Path,
    target_manifest: Mapping[str, Any],
    *,
    legacy_manifest_path: str | Path,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    target = Path(state_path)
    if not target.exists():
        return _new_state(target_manifest), None

    try:
        state = load_matrix_state(target, target_manifest)
        _verify_v2_state(state, target_manifest)
        return state, None
    except DemoStrategyMatrixError:
        pass

    legacy_manifest = load_legacy_manifest(legacy_manifest_path)
    try:
        legacy_state = load_matrix_state(target, legacy_manifest)
    except DemoStrategyMatrixError as exc:
        raise MultiPairMatrixError("state is neither valid v2 nor approved digest-valid v1") from exc
    return migrate_legacy_state(
        legacy_state=legacy_state,
        legacy_manifest=legacy_manifest,
        target_manifest=target_manifest,
    )


def _verify_v2_state(state: Mapping[str, Any], manifest: Mapping[str, Any]) -> None:
    core = dict(state)
    claimed = core.pop("state_digest", None)
    cells = core.get("cells")
    if (
        core.get("schema_version") != STATE_SCHEMA
        or core.get("matrix_id") != manifest["matrix_id"]
        or core.get("manifest_sha256") != _digest(manifest)
        or core.get("paper_only") is not True
        or core.get("live_trading_authority") is not False
        or core.get("private_credentials_used") is not False
        or core.get("automatic_strategy_promotion") is not False
        or claimed != _digest(core)
        or not isinstance(cells, Mapping)
        or any(cell_id not in _allowed_cell_ids() for cell_id in cells)
    ):
        raise MultiPairMatrixError("v2 matrix state verification failed")
    for cell_id, raw in cells.items():
        if not isinstance(raw, Mapping):
            raise MultiPairMatrixError("v2 matrix cell is not an object")
        symbol, timeframe = cell_id.split(":", 1)
        if (
            raw.get("cell_id") != cell_id
            or raw.get("symbol") != symbol
            or raw.get("timeframe") != timeframe
            or raw.get("status") not in {"VERIFIED", "BLOCKED"}
        ):
            raise MultiPairMatrixError("v2 matrix cell identity/status mismatch")
        lanes = raw.get("lanes", [])
        if not isinstance(lanes, list) or len(lanes) > len(FAMILIES):
            raise MultiPairMatrixError("v2 matrix cell lanes are invalid")
        seen: set[str] = set()
        for lane in lanes:
            if not isinstance(lane, Mapping):
                raise MultiPairMatrixError("v2 matrix lane is not an object")
            family = lane.get("family")
            if family not in FAMILIES or family in seen:
                raise MultiPairMatrixError("v2 matrix lane family is invalid or duplicated")
            seen.add(str(family))


def verify_v2_snapshot(
    value: Mapping[str, Any],
    *,
    manifest: Mapping[str, Any],
    state: Mapping[str, Any],
) -> dict[str, Any]:
    """Independently verify the exact approved 4 x 3 x 3 Paper snapshot.

    The legacy verifier remains unchanged for v1. This verifier binds v2 evidence
    to the approved manifest, validates the state digest/cell namespace, and
    requires a complete 12-cell/36-lane surface whenever status is VERIFIED.
    """
    checks: dict[str, bool] = {}
    try:
        _verify_v2_state(state, manifest)
        state_ok = True
    except MultiPairMatrixError:
        state_ok = False
    checks["state"] = state_ok

    core = dict(value)
    claimed = core.pop("snapshot_digest", None)
    checks.update({
        "schema": core.get("schema_version") == SNAPSHOT_SCHEMA,
        "digest": claimed == _digest(core),
        "matrix_id": core.get("matrix_id") == manifest["matrix_id"],
        "source_sha": isinstance(core.get("source_sha"), str) and bool(_SHA_RE.fullmatch(core["source_sha"])),
        "run_id": isinstance(core.get("run_id"), str) and core["run_id"].isdigit(),
        "paper_only": core.get("paper_only") is True,
        "live_disabled": core.get("live_trading_authority") is False,
        "credentials_disabled": core.get("private_credentials_used") is False,
        "promotion_disabled": core.get("automatic_strategy_promotion") is False,
        "risk_final": core.get("deterministic_risk_final_authority") is True,
        "state_digest": core.get("state_digest") == state.get("state_digest"),
        "symbols": core.get("symbols") == list(APPROVED_SYMBOLS),
        "timeframes": core.get("timeframes") == list(TIMEFRAMES),
        "families": core.get("families") == list(FAMILIES),
        "matrix_shape": core.get("expected_cell_count") == 12 and core.get("expected_lane_count") == 36,
    })

    cycle = core.get("cycle")
    allowed_cells = _allowed_cell_ids()
    cycle_ok = isinstance(cycle, list) and len(cycle) == 12
    cycle_ids: list[str] = []
    if cycle_ok:
        for row in cycle:
            if not isinstance(row, Mapping):
                cycle_ok = False
                break
            cell_id = row.get("cell_id")
            status = row.get("status")
            if cell_id not in allowed_cells or status not in {"VERIFIED", "BLOCKED", "SKIPPED_NO_NEW_BAR"}:
                cycle_ok = False
                break
            cycle_ids.append(str(cell_id))
        cycle_ok = cycle_ok and len(set(cycle_ids)) == 12 and set(cycle_ids) == allowed_cells
    checks["cycle_surface"] = cycle_ok

    lanes = core.get("lanes")
    lane_ok = isinstance(lanes, list) and core.get("reported_lane_count") == len(lanes)
    lane_ids: list[tuple[str, str, str]] = []
    if lane_ok:
        for lane in lanes:
            if not isinstance(lane, Mapping):
                lane_ok = False
                break
            lane_id = (lane.get("symbol"), lane.get("timeframe"), lane.get("family"))
            if lane_id not in _allowed_lane_ids():
                lane_ok = False
                break
            lane_ids.append((str(lane_id[0]), str(lane_id[1]), str(lane_id[2])))
        lane_ok = lane_ok and len(set(lane_ids)) == len(lane_ids) and len(lane_ids) <= 36
    checks["lane_namespace"] = lane_ok

    verified = core.get("verified_cell_count")
    blocked = core.get("blocked_cell_count")
    counts_ok = (
        isinstance(verified, int) and not isinstance(verified, bool)
        and isinstance(blocked, int) and not isinstance(blocked, bool)
        and 0 <= verified <= 12 and 0 <= blocked <= 12
        and verified + blocked == 12
    )
    checks["cell_counts"] = counts_ok

    if core.get("status") == "VERIFIED":
        checks["verified_completeness"] = (
            verified == 12
            and blocked == 0
            and core.get("reported_lane_count") == 36
            and set(lane_ids) == _allowed_lane_ids()
        )
    elif core.get("status") == "DEGRADED":
        checks["verified_completeness"] = counts_ok and (verified != 12 or blocked != 0)
    else:
        checks["verified_completeness"] = False

    return {"decision": "pass" if all(checks.values()) else "reject", "checks": checks}


def run_cycle(
    *,
    manifest_path: str | Path,
    legacy_manifest_path: str | Path,
    state_path: str | Path,
    state_root: str | Path,
    source_sha: str,
    run_id: str,
    now_ms: int,
    runner=None,
    verifier=None,
    analyzer=None,
):
    manifest = load_manifest(manifest_path)
    state, migration = load_or_migrate_state(
        state_path,
        manifest,
        legacy_manifest_path=legacy_manifest_path,
    )
    kwargs: dict[str, Any] = {
        "manifest": manifest,
        "state": state,
        "state_root": state_root,
        "source_sha": source_sha,
        "run_id": run_id,
        "now_ms": now_ms,
    }
    if runner is not None:
        kwargs["runner"] = runner
    if verifier is not None:
        kwargs["verifier"] = verifier
    if analyzer is not None:
        kwargs["analyzer"] = analyzer
    next_state, snapshot = run_matrix_cycle(**kwargs)
    verification = verify_v2_snapshot(snapshot, manifest=manifest, state=next_state)
    if verification.get("decision") != "pass":
        raise MultiPairMatrixError("multi-pair matrix snapshot failed independent verification")
    return next_state, snapshot, migration


def main() -> int:
    parser = argparse.ArgumentParser(description="Run bounded NEXUS four-symbol Demo Paper matrix")
    parser.add_argument("--manifest", type=Path, default=Path("config/nexus-demo-strategy-matrix-v2.json"))
    parser.add_argument("--legacy-manifest", type=Path, default=Path("config/nexus-demo-strategy-matrix-v1.json"))
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--state-root", type=Path, required=True)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--now-ms", type=int, required=True)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--migration-evidence", type=Path)
    args = parser.parse_args()

    try:
        next_state, snapshot, migration = run_cycle(
            manifest_path=args.manifest,
            legacy_manifest_path=args.legacy_manifest,
            state_path=args.state,
            state_root=args.state_root,
            source_sha=args.source_sha,
            run_id=args.run_id,
            now_ms=args.now_ms,
        )
        _atomic_json(args.state, next_state)
        _atomic_json(args.snapshot, snapshot)
        if migration is not None and args.migration_evidence is not None:
            _atomic_json(args.migration_evidence, migration)
    except (OSError, MultiPairMatrixError, DemoStrategyMatrixError) as exc:
        parser.exit(1, f"NEXUS multi-pair matrix failed closed: {exc}\n")
    print(json.dumps({
        "status": snapshot["status"],
        "expected_cell_count": snapshot["expected_cell_count"],
        "expected_lane_count": snapshot["expected_lane_count"],
        "migration_performed": migration is not None,
        "paper_only": snapshot["paper_only"],
        "live_trading_authority": snapshot["live_trading_authority"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
