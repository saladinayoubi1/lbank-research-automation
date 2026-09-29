"""Archive terminal prospective Paper evidence under its ORIGINAL pinned engine.

A QUARANTINED or owner-review terminal state is immutable evidence, not a
candidate to "repair" by replacing the engine SHA with current source code.
The calling workflow must retrieve the exact public GitHub engine file at
state.latest_source_sha, then provide that historical file for digest proof.
No trading, future requalification, runtime lock equivalence or migration is
performed here. Different current code MUST create an independent new Paper
candidate only after the normal separate admission process.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any

import bybit_prospective_paper_forward_v1 as forward
from nexus_paper_terminal_rebind import TERMINAL_DECISIONS

SCHEMA = "nexus.paper-terminal-original-engine-archive.v1"
_SHA40 = re.compile(r"^[0-9a-f]{40}$")
_SHA64 = re.compile(r"^[0-9a-f]{64}$")
MAX_STATE_BYTES = 12 * 1024 * 1024
MAX_ENGINE_BYTES = 2 * 1024 * 1024


class TerminalArchiveError(RuntimeError):
    pass


def _hash_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _digest(value: dict[str, Any]) -> str:
    return _hash_bytes(json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8"))


def _bounded_file(path: Path, *, limit: int) -> bytes:
    if path.is_symlink() or not path.is_file() or path.stat().st_size <= 0 or path.stat().st_size > limit:
        raise TerminalArchiveError("archival input is missing, linked or outside size bounds")
    return path.read_bytes()


def archive_terminal(
    *,
    state_path: Path,
    manifest_path: Path,
    historical_engine_path: Path,
    historical_engine_source_sha: str,
    observer_source_sha: str,
    observer_run_id: int,
    destination: Path,
) -> dict[str, Any]:
    if (
        not isinstance(historical_engine_source_sha, str)
        or not _SHA40.fullmatch(historical_engine_source_sha)
        or not isinstance(observer_source_sha, str)
        or not _SHA40.fullmatch(observer_source_sha)
        or isinstance(observer_run_id, bool) or not isinstance(observer_run_id, int)
        or observer_run_id <= 0
    ):
        raise TerminalArchiveError("source SHA or observer run identity is invalid")
    original_bytes = _bounded_file(state_path, limit=MAX_STATE_BYTES)
    _bounded_file(historical_engine_path, limit=MAX_ENGINE_BYTES)
    try:
        state = json.loads(original_bytes.decode("utf-8"))
    except (UnicodeError, ValueError) as exc:
        raise TerminalArchiveError("original terminal state is malformed") from exc
    if not isinstance(state, dict):
        raise TerminalArchiveError("terminal state must be a signed JSON object")
    if (
        state.get("latest_source_sha") != historical_engine_source_sha
        or state.get("status") not in TERMINAL_DECISIONS
        or state.get("decision") != TERMINAL_DECISIONS[state["status"]]
        or state.get("paper_only") is not True
        or state.get("live_trading_enabled") is not False
        or state.get("private_credentials_used") is not False
        or state.get("automatic_live_promotion") is not False
        or not _SHA64.fullmatch(str(state.get("engine_sha256", "")))
        or isinstance(state.get("last_run_id"), bool)
        or not isinstance(state.get("last_run_id"), int)
        or observer_run_id <= state["last_run_id"]
    ):
        raise TerminalArchiveError("not a non-promotable terminal state from this original source")
    exact_historical_engine_sha = forward._file_sha(historical_engine_path.resolve())
    if exact_historical_engine_sha != state["engine_sha256"]:
        raise TerminalArchiveError("original Git-pinned engine bytes do not match signed Paper state")
    config, _ = forward.load_contract(manifest_path.resolve())
    # Recalculate the original state digest AND the complete original signed
    # event chain against the original engine ID, NEVER the current engine ID.
    # This does not claim to re-execute the historical producer's numeric model.
    forward.verify_state(state, config, exact_historical_engine_sha)
    current_engine_sha = forward._file_sha(Path(forward.__file__).resolve())
    receipt_core = {
        "schema": SCHEMA,
        "original_engine_source_sha": historical_engine_source_sha,
        "original_engine_sha256": exact_historical_engine_sha,
        "original_signed_state_digest": state["state_digest"],
        "original_state_bytes_sha256": _hash_bytes(original_bytes),
        "original_latest_source_sha": state["latest_source_sha"],
        "original_last_run_id": state["last_run_id"],
        "original_completed_bar_count": state["completed_bar_count"],
        "original_last_execution_utc": state["last_execution_utc"],
        "original_status": state["status"],
        "original_decision": state["decision"],
        "observer_source_sha": observer_source_sha,
        "observer_run_id": observer_run_id,
        "current_engine_different_from_original": current_engine_sha != exact_historical_engine_sha,
        "historical_engine_source_digest_verified": True,
        "historical_terminal_event_chain_verified": True,
        "original_signed_evidence_preserved_byte_for_byte": True,
        "current_runtime_equivalence_claimed": False,
        "independent_numerical_historical_replay_claimed": False,
        "current_or_future_paper_execution_authorized": False,
        "new_paper_events_or_exchange_orders_created": False,
        "automatic_paper_promotion": False,
        "live_trading_enabled": False,
        "private_credentials_used": False,
        "owner_review_required": True,
        "archive_only": True,
    }
    receipt = {**receipt_core, "receipt_digest": _digest(receipt_core)}
    if destination.is_symlink() or destination.exists():
        raise TerminalArchiveError("refusing to overwrite prior terminal archive")
    destination.mkdir(parents=True)
    original_target = destination / "original-state.json"
    receipt_target = destination / "archive-receipt.json"
    original_target.write_bytes(original_bytes)
    receipt_target.write_text(
        json.dumps(receipt, sort_keys=True, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    if _hash_bytes(original_target.read_bytes()) != receipt["original_state_bytes_sha256"]:
        raise TerminalArchiveError("immutable terminal bytes failed post-write verification")
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--historical-engine", required=True, type=Path)
    parser.add_argument("--historical-engine-source-sha", required=True)
    parser.add_argument("--observer-source-sha", required=True)
    parser.add_argument("--observer-run-id", required=True, type=int)
    parser.add_argument("--destination", required=True, type=Path)
    args = parser.parse_args()
    result = archive_terminal(
        state_path=args.state,
        manifest_path=args.manifest,
        historical_engine_path=args.historical_engine,
        historical_engine_source_sha=args.historical_engine_source_sha,
        observer_source_sha=args.observer_source_sha,
        observer_run_id=args.observer_run_id,
        destination=args.destination,
    )
    print(json.dumps({k: result[k] for k in (
        "original_status", "original_engine_source_sha",
        "original_engine_sha256", "original_completed_bar_count",
        "historical_terminal_event_chain_verified", "owner_review_required",
        "receipt_digest", "automatic_paper_promotion", "live_trading_enabled"
    )}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
