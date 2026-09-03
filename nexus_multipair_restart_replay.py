"""Deterministic restart/replay evidence for the four-symbol Paper matrix.

This module does not execute trades or fetch market data. It captures a verified
12-cell/36-lane matrix state after one physical process, then independently
verifies that a later process/job reloaded the same durable state and skipped
all duplicate closed bars when replayed at the exact same bounded clock.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any, Mapping

from nexus_multipair_demo_strategy_matrix import load_manifest, verify_v2_snapshot

CAPTURE_SCHEMA = "nexus.multipair-restart-seed.v1"
PROOF_SCHEMA = "nexus.multipair-restart-replay-proof.v1"
_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
EXPECTED_SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT")
EXPECTED_TIMEFRAMES = ("minute15", "hour1", "hour4")
EXPECTED_FAMILIES = ("momentum", "trend_breakout", "mean_reversion")


class MultiPairRestartReplayError(RuntimeError):
    pass


def _canonical(value: Any) -> bytes:
    try:
        return json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise MultiPairRestartReplayError("restart/replay evidence is not canonical JSON") from exc


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _read_json(path: str | Path) -> dict[str, Any]:
    target = Path(path)
    if target.is_symlink() or not target.is_file() or target.stat().st_size > 5_000_000:
        raise MultiPairRestartReplayError(f"evidence file is unavailable or unsafe: {target}")
    try:
        value = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise MultiPairRestartReplayError(f"evidence file is unreadable: {target}") from exc
    if not isinstance(value, dict):
        raise MultiPairRestartReplayError(f"evidence file is not an object: {target}")
    return value


def _atomic_json(path: str | Path, value: Mapping[str, Any]) -> None:
    target = Path(path).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(dict(value), indent=2, sort_keys=True, ensure_ascii=False))
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, target)


def _state_surface(state: Mapping[str, Any]) -> tuple[dict[str, int], list[list[str]]]:
    cells = state.get("cells")
    if not isinstance(cells, Mapping) or len(cells) != 12:
        raise MultiPairRestartReplayError("durable matrix state must contain exactly 12 cells")
    expected_cells = {
        f"{symbol}:{timeframe}"
        for symbol in EXPECTED_SYMBOLS
        for timeframe in EXPECTED_TIMEFRAMES
    }
    if set(cells) != expected_cells:
        raise MultiPairRestartReplayError("durable matrix state cell namespace mismatch")

    cursors: dict[str, int] = {}
    lanes: list[list[str]] = []
    for cell_id in sorted(cells):
        row = cells[cell_id]
        if not isinstance(row, Mapping) or row.get("status") != "VERIFIED":
            raise MultiPairRestartReplayError("restart seed contains a non-verified cell")
        cursor = row.get("last_completed_open_ms")
        if isinstance(cursor, bool) or not isinstance(cursor, int) or cursor < 0:
            raise MultiPairRestartReplayError("restart seed contains an invalid cell cursor")
        cursors[cell_id] = cursor
        cell_lanes = row.get("lanes")
        if not isinstance(cell_lanes, list) or len(cell_lanes) != 3:
            raise MultiPairRestartReplayError("restart seed must preserve three isolated lanes per cell")
        seen: set[str] = set()
        for lane in cell_lanes:
            if not isinstance(lane, Mapping):
                raise MultiPairRestartReplayError("restart seed lane is not an object")
            family = lane.get("family")
            if family not in EXPECTED_FAMILIES or family in seen:
                raise MultiPairRestartReplayError("restart seed lane family is invalid or duplicated")
            seen.add(str(family))
            lanes.append([str(row["symbol"]), str(row["timeframe"]), str(family)])
    if len(lanes) != 36 or len({tuple(row) for row in lanes}) != 36:
        raise MultiPairRestartReplayError("restart seed must preserve exactly 36 isolated lanes")
    return cursors, sorted(lanes)


def capture_seed(
    *,
    manifest_path: str | Path,
    state_path: str | Path,
    snapshot_path: str | Path,
    source_sha: str,
    run_id: str,
    now_ms: int,
    output_path: str | Path,
) -> dict[str, Any]:
    source_sha = str(source_sha).strip().lower()
    if not _SHA_RE.fullmatch(source_sha):
        raise MultiPairRestartReplayError("source_sha must be an exact Git SHA")
    if not str(run_id).isdigit():
        raise MultiPairRestartReplayError("run_id must be numeric")
    if isinstance(now_ms, bool) or not isinstance(now_ms, int) or now_ms <= 0:
        raise MultiPairRestartReplayError("now_ms must be a positive integer")

    manifest = load_manifest(manifest_path)
    state = _read_json(state_path)
    snapshot = _read_json(snapshot_path)
    verification = verify_v2_snapshot(snapshot, manifest=manifest, state=state)
    if verification.get("decision") != "pass":
        raise MultiPairRestartReplayError("seed snapshot failed independent v2 verification")
    if (
        snapshot.get("status") != "VERIFIED"
        or snapshot.get("source_sha") != source_sha
        or snapshot.get("run_id") != str(run_id)
        or snapshot.get("expected_cell_count") != 12
        or snapshot.get("verified_cell_count") != 12
        or snapshot.get("blocked_cell_count") != 0
        or snapshot.get("expected_lane_count") != 36
        or snapshot.get("reported_lane_count") != 36
        or snapshot.get("symbols") != list(EXPECTED_SYMBOLS)
        or snapshot.get("timeframes") != list(EXPECTED_TIMEFRAMES)
        or snapshot.get("families") != list(EXPECTED_FAMILIES)
        or snapshot.get("paper_only") is not True
        or snapshot.get("live_trading_authority") is not False
        or snapshot.get("private_credentials_used") is not False
        or snapshot.get("automatic_strategy_promotion") is not False
        or snapshot.get("deterministic_risk_final_authority") is not True
    ):
        raise MultiPairRestartReplayError("seed snapshot does not satisfy the 12/36 Paper boundary")
    cursors, lanes = _state_surface(state)
    core = {
        "schema_version": CAPTURE_SCHEMA,
        "source_sha": source_sha,
        "run_id": str(run_id),
        "now_ms": now_ms,
        "state_digest": state.get("state_digest"),
        "snapshot_digest": snapshot.get("snapshot_digest"),
        "cell_cursors": cursors,
        "lane_ids": lanes,
        "paper_only": True,
        "live_trading_authority": False,
        "private_credentials_used": False,
        "automatic_strategy_promotion": False,
        "deterministic_risk_final_authority": True,
    }
    result = {**core, "capture_digest": _digest(core)}
    _atomic_json(output_path, result)
    return result


def verify_restart(
    *,
    manifest_path: str | Path,
    seed_path: str | Path,
    state_path: str | Path,
    snapshot_path: str | Path,
    source_sha: str,
    run_id: str,
    output_path: str | Path,
) -> dict[str, Any]:
    seed = _read_json(seed_path)
    seed_core = dict(seed)
    claimed_capture = seed_core.pop("capture_digest", None)
    if seed_core.get("schema_version") != CAPTURE_SCHEMA or claimed_capture != _digest(seed_core):
        raise MultiPairRestartReplayError("restart seed digest verification failed")
    source_sha = str(source_sha).strip().lower()
    if source_sha != seed.get("source_sha") or str(run_id) != seed.get("run_id"):
        raise MultiPairRestartReplayError("restart identity does not match seed identity")

    manifest = load_manifest(manifest_path)
    state = _read_json(state_path)
    snapshot = _read_json(snapshot_path)
    verification = verify_v2_snapshot(snapshot, manifest=manifest, state=state)
    if verification.get("decision") != "pass":
        raise MultiPairRestartReplayError("restart snapshot failed independent v2 verification")
    cursors, lanes = _state_surface(state)
    cycle = snapshot.get("cycle")
    if (
        snapshot.get("status") != "VERIFIED"
        or snapshot.get("source_sha") != source_sha
        or snapshot.get("run_id") != str(run_id)
        or snapshot.get("verified_cell_count") != 12
        or snapshot.get("blocked_cell_count") != 0
        or snapshot.get("reported_lane_count") != 36
        or state.get("state_digest") != seed.get("state_digest")
        or cursors != seed.get("cell_cursors")
        or lanes != seed.get("lane_ids")
        or not isinstance(cycle, list)
        or len(cycle) != 12
        or {row.get("cell_id") for row in cycle if isinstance(row, Mapping)} != set(cursors)
        or any(not isinstance(row, Mapping) or row.get("status") != "SKIPPED_NO_NEW_BAR" for row in cycle)
        or snapshot.get("paper_only") is not True
        or snapshot.get("live_trading_authority") is not False
        or snapshot.get("private_credentials_used") is not False
        or snapshot.get("automatic_strategy_promotion") is not False
        or snapshot.get("deterministic_risk_final_authority") is not True
    ):
        raise MultiPairRestartReplayError("restart/replay continuity verification failed")

    core = {
        "schema_version": PROOF_SCHEMA,
        "source_sha": source_sha,
        "run_id": str(run_id),
        "replay_now_ms": seed.get("now_ms"),
        "seed_state_digest": seed.get("state_digest"),
        "restart_state_digest": state.get("state_digest"),
        "restart_snapshot_digest": snapshot.get("snapshot_digest"),
        "verified_cell_count": 12,
        "blocked_cell_count": 0,
        "reported_lane_count": 36,
        "duplicate_bar_execution_count": 0,
        "skipped_no_new_bar_count": 12,
        "state_digest_preserved": True,
        "cell_cursors_preserved": True,
        "lane_identity_preserved": True,
        "paper_only": True,
        "live_trading_authority": False,
        "private_credentials_used": False,
        "automatic_strategy_promotion": False,
        "deterministic_risk_final_authority": True,
    }
    proof = {**core, "proof_digest": _digest(core)}
    _atomic_json(output_path, proof)
    return proof


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    capture = sub.add_parser("capture")
    capture.add_argument("--manifest", required=True, type=Path)
    capture.add_argument("--state", required=True, type=Path)
    capture.add_argument("--snapshot", required=True, type=Path)
    capture.add_argument("--source-sha", required=True)
    capture.add_argument("--run-id", required=True)
    capture.add_argument("--now-ms", required=True, type=int)
    capture.add_argument("--output", required=True, type=Path)

    verify = sub.add_parser("verify")
    verify.add_argument("--manifest", required=True, type=Path)
    verify.add_argument("--seed", required=True, type=Path)
    verify.add_argument("--state", required=True, type=Path)
    verify.add_argument("--snapshot", required=True, type=Path)
    verify.add_argument("--source-sha", required=True)
    verify.add_argument("--run-id", required=True)
    verify.add_argument("--output", required=True, type=Path)

    args = parser.parse_args()
    try:
        if args.command == "capture":
            result = capture_seed(
                manifest_path=args.manifest, state_path=args.state,
                snapshot_path=args.snapshot, source_sha=args.source_sha,
                run_id=args.run_id, now_ms=args.now_ms, output_path=args.output,
            )
            print(json.dumps({"capture_digest": result["capture_digest"], "state_digest": result["state_digest"]}, sort_keys=True))
        else:
            result = verify_restart(
                manifest_path=args.manifest, seed_path=args.seed,
                state_path=args.state, snapshot_path=args.snapshot,
                source_sha=args.source_sha, run_id=args.run_id,
                output_path=args.output,
            )
            print(json.dumps({"proof_digest": result["proof_digest"], "state_digest_preserved": True, "skipped_no_new_bar_count": 12}, sort_keys=True))
    except (OSError, MultiPairRestartReplayError) as exc:
        parser.exit(1, f"NEXUS multi-pair restart/replay failed closed: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
