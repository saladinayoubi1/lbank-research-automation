"""Refresh Demo Paper performance after risk-reducing position maintenance.

The standard matrix analyzer intentionally focuses on the current-cycle active
statuses.  This bounded refresh additionally carries forward a previously verified
automatic Paper acceptance when a requalified strategy is currently flat, so
closed-trade history and PAPER lifecycle are not lost between replay cycles.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from copy import deepcopy
from pathlib import Path
from typing import Any, Mapping, Sequence

from nexus_demo_strategy_matrix import (
    _baseline,
    _digest as _matrix_digest,
    _read_journal,
    load_manifest,
    load_state,
    verify_snapshot,
)
from nexus_paper_performance_pipeline import (
    build_paper_performance_projection,
    save_paper_performance_projection,
)
from nexus_strategy_paper_supervisor import verify_ledger

SCHEMA = "nexus.demo-paper-performance-refresh.v1"
_ELIGIBLE_LEDGER_STATUSES = {"paper_executed", "position_exists", "no_open_signal"}
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class DemoPaperPerformanceRefreshError(RuntimeError):
    pass


def _canonical(value: Any) -> bytes:
    try:
        return json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise DemoPaperPerformanceRefreshError("refresh evidence is not canonical JSON") from exc


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(dict(value), indent=2, sort_keys=True, ensure_ascii=False))
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def _rebind_matrix_performance(
    *,
    manifest: Mapping[str, Any],
    root: Path,
    source_sha: str,
    rows: Sequence[Mapping[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Atomically rebind refreshed per-cell analysis into matrix state/snapshot digests."""
    state_path = root / "matrix-state.json"
    snapshot_path = root / "demo" / "strategy-matrix.json"
    state = load_state(state_path, manifest)
    if snapshot_path.is_symlink() or not snapshot_path.is_file():
        raise DemoPaperPerformanceRefreshError("strategy matrix snapshot is unavailable")
    try:
        snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise DemoPaperPerformanceRefreshError("strategy matrix snapshot is unreadable") from exc
    if not isinstance(snapshot, dict) or verify_snapshot(snapshot).get("decision") != "pass":
        raise DemoPaperPerformanceRefreshError("strategy matrix snapshot is not verified")
    if (
        snapshot.get("source_sha") != source_sha
        or snapshot.get("status") != "VERIFIED"
        or snapshot.get("state_digest") != state.get("state_digest")
    ):
        raise DemoPaperPerformanceRefreshError("matrix state/snapshot binding is stale before refresh")

    cells = state.get("cells")
    if not isinstance(cells, dict):
        raise DemoPaperPerformanceRefreshError("matrix cells are unavailable")
    expected_cells = {
        f"{symbol}:{timeframe}"
        for symbol in manifest["symbols"]
        for timeframe in manifest["timeframes"]
    }
    row_by_cell: dict[str, Mapping[str, Any]] = {}
    for row in rows:
        if not isinstance(row, Mapping):
            raise DemoPaperPerformanceRefreshError("performance row is not an object")
        cell_id = f"{row.get('symbol')}:{row.get('timeframe')}"
        if cell_id in row_by_cell:
            raise DemoPaperPerformanceRefreshError("duplicate performance cell")
        row_by_cell[cell_id] = row
    if set(cells) != expected_cells or set(row_by_cell) != expected_cells:
        raise DemoPaperPerformanceRefreshError("performance refresh does not bind the exact matrix surface")

    rebound_state = deepcopy(state)
    rebound_cells = rebound_state["cells"]
    for cell_id in sorted(expected_cells):
        cell = rebound_cells[cell_id]
        row = row_by_cell[cell_id]
        projection_digest = row.get("projection_digest")
        status_counts = row.get("status_counts")
        if (
            not isinstance(cell, dict)
            or cell.get("status") != "VERIFIED"
            or cell.get("source_sha") != source_sha
            or not isinstance(projection_digest, str)
            or not _SHA256_RE.fullmatch(projection_digest)
            or not isinstance(status_counts, Mapping)
        ):
            raise DemoPaperPerformanceRefreshError(f"invalid matrix performance binding: {cell_id}")
        cell["analysis_digest"] = projection_digest
        cell["analysis_status_counts"] = dict(status_counts)

    state_core = dict(rebound_state)
    state_core.pop("state_digest", None)
    rebound_state["state_digest"] = _matrix_digest(state_core)

    rebound_snapshot = deepcopy(snapshot)
    snapshot_core = dict(rebound_snapshot)
    snapshot_core.pop("snapshot_digest", None)
    snapshot_core["state_digest"] = rebound_state["state_digest"]
    rebound_snapshot = {**snapshot_core, "snapshot_digest": _matrix_digest(snapshot_core)}
    if verify_snapshot(rebound_snapshot).get("decision") != "pass":
        raise DemoPaperPerformanceRefreshError("rebound strategy matrix snapshot failed verification")

    _atomic_json(state_path, rebound_state)
    _atomic_json(snapshot_path, rebound_snapshot)
    return rebound_state, rebound_snapshot


def refresh_cell_performance(
    *,
    cell_root: Path,
    ledger: Mapping[str, Any],
) -> dict[str, Any]:
    verification = verify_ledger(ledger)
    if verification.get("decision") != "pass":
        raise DemoPaperPerformanceRefreshError("Supervisor ledger is not verified")
    journals: dict[str, Sequence[Mapping[str, Any]]] = {}
    baselines: dict[str, Mapping[str, Any]] = {}
    for task in ledger.get("tasks", []):
        if task.get("status") not in _ELIGIBLE_LEDGER_STATUSES:
            continue
        family = str(task["family"])
        journal_path = cell_root / "portfolios" / family / "product_runtime" / "paper-events.jsonl"
        if journal_path.exists():
            journals[family] = _read_journal(journal_path)
            baselines[family] = _baseline(task)
        elif task.get("status") in {"paper_executed", "position_exists"}:
            raise DemoPaperPerformanceRefreshError("active Paper task is missing its journal")
    projection = build_paper_performance_projection(
        supervisor_ledger=ledger,
        journals_by_family=journals,
        baselines_by_family=baselines,
    )
    save_paper_performance_projection(cell_root / "analysis" / "paper-performance.json", projection)
    return projection


def run_performance_refresh(
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
                raise DemoPaperPerformanceRefreshError("Supervisor ledger is unavailable")
            ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
            if ledger.get("source_sha") != source_sha:
                raise DemoPaperPerformanceRefreshError("Supervisor ledger source SHA mismatch")
            projection = refresh_cell_performance(cell_root=cell_root, ledger=ledger)
            rows.append({
                "symbol": symbol,
                "timeframe": timeframe,
                "strategy_count": projection["strategy_count"],
                "status_counts": projection["status_counts"],
                "projection_digest": projection["projection_digest"],
            })
    rebound_state, rebound_snapshot = _rebind_matrix_performance(
        manifest=manifest,
        root=root,
        source_sha=source_sha,
        rows=rows,
    )
    core = {
        "schema_version": SCHEMA,
        "source_sha": source_sha,
        "cell_count": len(rows),
        "rows": rows,
        "paper_only": True,
        "live_trading_authority": False,
        "automatic_strategy_promotion": False,
    }
    result = {**core, "refresh_digest": _digest(core)}
    _atomic_json(root / "demo" / "paper-performance-refresh.json", result)
    return {
        **result,
        "_rebound_matrix_state": rebound_state,
        "_rebound_matrix_snapshot": rebound_snapshot,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--state-root", type=Path, required=True)
    parser.add_argument("--source-sha", required=True)
    args = parser.parse_args()
    result = run_performance_refresh(
        manifest=load_manifest(args.manifest),
        state_root=args.state_root,
        source_sha=str(args.source_sha).strip().lower(),
    )
    print(json.dumps({
        "cell_count": result["cell_count"],
        "refresh_digest": result["refresh_digest"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())