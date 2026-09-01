"""Fail-closed stage-1 verifier for NEXUS physical Paper acceptance evidence.

This verifier intentionally proves only the first acceptance stage from one durable
Paper state root: 6/6 exact-source cells, 18/18 exact-source Strategy Paper lanes,
and same-run maintenance/performance/regime evidence with Paper-only authority.
It also requires the verified 4h boundary to have reached the operational health-
feedback/Discovery-trigger handoff. It does NOT claim Strategy Discovery/runtime-
requalification completion and does NOT prove restart/replay; those require their
distinct workflow evidence chains.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Mapping

from nexus_demo_regime_cycle import verify_cycle_snapshot
from nexus_demo_strategy_matrix import load_manifest, load_state
from nexus_persistent_paper_trading_loop import verify_loop_snapshot
from nexus_strategy_paper_supervisor import verify_ledger

_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_MAX_JSON_BYTES = 20_000_000
_TERMINAL_LANE_STATUSES = frozenset(
    {
        "paper_executed",
        "qualification_killed",
        "no_open_signal",
        "position_exists",
        "risk_rejected",
    }
)


class PaperAcceptanceStage1Error(RuntimeError):
    pass


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    target = Path(path)
    if target.is_symlink() or not target.is_file() or target.stat().st_size > _MAX_JSON_BYTES:
        raise PaperAcceptanceStage1Error(f"unsafe or missing evidence: {target}")
    try:
        value = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PaperAcceptanceStage1Error(f"unreadable evidence: {target}") from exc
    if not isinstance(value, dict):
        raise PaperAcceptanceStage1Error(f"evidence is not an object: {target}")
    return value


def _verify_digest(value: Mapping[str, Any], field: str) -> str:
    claimed = value.get(field)
    if not isinstance(claimed, str) or not _SHA256_RE.fullmatch(claimed):
        raise PaperAcceptanceStage1Error(f"invalid {field}")
    core = dict(value)
    core.pop(field, None)
    if claimed != _digest(core):
        raise PaperAcceptanceStage1Error(f"{field} mismatch")
    return claimed


def audit_state_root(*, state_root: Path, manifest_path: Path, source_sha: str) -> dict[str, Any]:
    source_sha = str(source_sha).strip().lower()
    if not _SHA_RE.fullmatch(source_sha):
        raise PaperAcceptanceStage1Error("source_sha must be an exact Git SHA")

    root = Path(state_root).resolve()
    manifest = load_manifest(manifest_path)
    matrix = load_state(root / "matrix-state.json", manifest)
    loop = _read_json(root / "demo" / "persistent-paper-trading-loop.json")
    if verify_loop_snapshot(loop).get("decision") != "pass":
        raise PaperAcceptanceStage1Error("persistent Paper loop snapshot verification failed")

    expected_cells = {
        f"{symbol}:{timeframe}"
        for symbol in manifest["symbols"]
        for timeframe in manifest["timeframes"]
    }
    cells = matrix.get("cells")
    if not isinstance(cells, Mapping) or set(cells) != expected_cells:
        raise PaperAcceptanceStage1Error("matrix does not contain the exact approved 6-cell surface")

    lane_count = 0
    lane_status_counts: dict[str, int] = {}
    for cell_id in sorted(expected_cells):
        cell = cells[cell_id]
        if not isinstance(cell, Mapping):
            raise PaperAcceptanceStage1Error(f"invalid matrix cell: {cell_id}")
        symbol, timeframe = cell_id.split(":", 1)
        if (
            cell.get("status") != "VERIFIED"
            or cell.get("source_sha") != source_sha
            or cell.get("symbol") != symbol
            or cell.get("timeframe") != timeframe
        ):
            raise PaperAcceptanceStage1Error(f"cell is not exact-source VERIFIED: {cell_id}")

        ledger = _read_json(root / "cells" / symbol.lower() / timeframe / "supervisor-ledger.json")
        ledger_verification = verify_ledger(ledger)
        if ledger_verification.get("decision") != "pass":
            raise PaperAcceptanceStage1Error(f"Supervisor ledger rejected: {cell_id}")
        ledger_digest = ledger.get("ledger_digest")
        ledger_core = dict(ledger)
        ledger_core.pop("ledger_digest", None)
        if (
            ledger.get("final_status") != "VERIFIED"
            or not isinstance(ledger_digest, str)
            or not _SHA256_RE.fullmatch(ledger_digest)
            or ledger_digest != _digest(ledger_core)
            or cell.get("ledger_digest") != ledger_digest
            or cell.get("verification_digest") != ledger_verification.get("verification_digest")
        ):
            raise PaperAcceptanceStage1Error(f"Supervisor ledger digest binding mismatch: {cell_id}")
        if (
            ledger.get("source_sha") != source_sha
            or ledger.get("symbol") != symbol
            or ledger.get("timeframe") != timeframe
            or ledger.get("paper_only") is not True
            or ledger.get("live_trading_authority") is not False
        ):
            raise PaperAcceptanceStage1Error(f"Supervisor ledger authority/source mismatch: {cell_id}")

        tasks = ledger.get("tasks")
        lanes = cell.get("lanes")
        if not isinstance(tasks, list) or not isinstance(lanes, list):
            raise PaperAcceptanceStage1Error(f"lane evidence is missing: {cell_id}")
        task_by_family = {
            str(row.get("family")): row for row in tasks if isinstance(row, Mapping)
        }
        lane_by_family = {
            str(row.get("family")): row for row in lanes if isinstance(row, Mapping)
        }
        if set(task_by_family) != set(manifest["families"]) or set(lane_by_family) != set(manifest["families"]):
            raise PaperAcceptanceStage1Error(f"lane family surface mismatch: {cell_id}")
        if len(task_by_family) != len(tasks) or len(lane_by_family) != len(lanes):
            raise PaperAcceptanceStage1Error(f"duplicate lane family detected: {cell_id}")

        for family in sorted(manifest["families"]):
            task = task_by_family[family]
            lane = lane_by_family[family]
            if (
                lane.get("task_id") != task.get("task_id")
                or lane.get("status") != task.get("status")
                or lane.get("evidence_digest") != task.get("evidence_digest")
            ):
                raise PaperAcceptanceStage1Error(f"lane/ledger substitution detected: {cell_id}/{family}")
            digest = lane.get("evidence_digest")
            if not isinstance(digest, str) or not _SHA256_RE.fullmatch(digest):
                raise PaperAcceptanceStage1Error(f"invalid lane evidence digest: {cell_id}/{family}")
            status = str(lane.get("status", ""))
            if status not in _TERMINAL_LANE_STATUSES:
                raise PaperAcceptanceStage1Error(
                    f"nonterminal or unapproved lane outcome: {cell_id}/{family}: {status or '<empty>'}"
                )
            lane_status_counts[status] = lane_status_counts.get(status, 0) + 1
            lane_count += 1

    if lane_count != 18:
        raise PaperAcceptanceStage1Error("exact 18-lane accounting was not proven")

    if (
        loop.get("source_sha") != source_sha
        or loop.get("status") != "PAPER_LOOP_ACTIVE"
        or loop.get("fresh_cell_count") != 6
        or set(loop.get("fresh_cells", [])) != expected_cells
        or loop.get("expected_cell_count") != 6
        or loop.get("expected_lane_count") != 18
        or loop.get("regime_status") != "VERIFIED"
        or loop.get("performance_health_feedback_operational") is not True
        or loop.get("regime_selected_rebalance_operational") is not True
        or loop.get("regime_selected_exposure_increase_operational") is not True
        or loop.get("strategy_research_required") is not True
        or loop.get("strategy_discovery_health_trigger_requested") is not True
        or loop.get("remaining_core_gap") != "RUNTIME_EVIDENCE_AND_DISCOVERY_FEEDBACK_PROOF"
        or loop.get("paper_only") is not True
        or loop.get("live_trading_authority") is not False
        or loop.get("private_credentials_used") is not False
        or loop.get("automatic_strategy_promotion") is not False
        or loop.get("deterministic_risk_final_authority") is not True
    ):
        raise PaperAcceptanceStage1Error(
            "loop does not prove an operational exact-source 6/6 boundary handoff"
        )

    maintenance = _read_json(root / "demo" / "paper-position-maintenance.json")
    maintenance_digest = _verify_digest(maintenance, "maintenance_digest")
    if (
        maintenance_digest != loop.get("maintenance_digest")
        or maintenance.get("source_sha") != source_sha
        or maintenance.get("cell_count") != 6
        or maintenance.get("task_count") != 18
        or maintenance.get("paper_only") is not True
        or maintenance.get("live_trading_authority") is not False
        or maintenance.get("private_credentials_used") is not False
        or maintenance.get("automatic_strategy_promotion") is not False
        or maintenance.get("exposure_increased") is not False
    ):
        raise PaperAcceptanceStage1Error("maintenance evidence is not exact-source/risk-reducing")

    performance = _read_json(root / "demo" / "paper-performance-refresh.json")
    performance_digest = _verify_digest(performance, "refresh_digest")
    if (
        performance_digest != loop.get("performance_refresh_digest")
        or performance.get("source_sha") != source_sha
        or performance.get("cell_count") != 6
        or performance.get("paper_only") is not True
        or performance.get("live_trading_authority") is not False
        or performance.get("automatic_strategy_promotion") is not False
    ):
        raise PaperAcceptanceStage1Error("performance evidence is not exact-source Paper evidence")

    regime = _read_json(root / "demo" / "regime-cycle.json")
    if verify_cycle_snapshot(regime).get("decision") != "pass":
        raise PaperAcceptanceStage1Error("regime evidence verification failed")
    if (
        regime.get("cycle_digest") != loop.get("regime_cycle_digest")
        or regime.get("source_sha") != source_sha
        or regime.get("expected_cell_count") != 6
        or regime.get("verified_cell_count") != 6
        or regime.get("paper_only") is not True
        or regime.get("live_trading_authority") is not False
        or regime.get("private_credentials_used") is not False
        or regime.get("automatic_strategy_promotion") is not False
        or regime.get("deterministic_risk_final_authority") is not True
    ):
        raise PaperAcceptanceStage1Error("regime evidence is not exact-source Paper evidence")

    return {
        "decision": "pass",
        "source_sha": source_sha,
        "verified_cell_count": 6,
        "verified_lane_count": lane_count,
        "lane_status_counts": dict(sorted(lane_status_counts.items())),
        "maintenance_digest": maintenance_digest,
        "performance_refresh_digest": performance_digest,
        "regime_cycle_digest": regime["cycle_digest"],
        "health_trigger_requested": True,
        "stage1_only": True,
        "discovery_runtime_requalification_proven": False,
        "restart_replay_proven": False,
        "paper_only": True,
        "live_trading_authority": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-root", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--source-sha", required=True)
    args = parser.parse_args()
    result = audit_state_root(
        state_root=args.state_root,
        manifest_path=args.manifest,
        source_sha=args.source_sha,
    )
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
