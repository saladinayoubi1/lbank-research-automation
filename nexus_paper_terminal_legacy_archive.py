"""Fail-closed archival proof for ONE independently verified historical terminal Paper run.

Never migrate or re-sign the original terminal state as if the NEW engine had
executed 181 historical bars. Preserve its exact bytes and historical source.
This module authorizes no new forward observations, Paper admission or Live.
An unrelated old run/source/engine/state needs separate reviewed migration.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any, Mapping

import bybit_prospective_paper_forward_v1 as forward

SCHEMA = "nexus.paper-terminal-historical-quarantine-archive.v1"
OLD_SOURCE_SHA = "961fc206bb9475666152f15c729e00dd2e1bd184"
OLD_ENGINE_SHA256 = "0a1dcb2fc6b5cda30093b5486cf97ffac6d6a4768c8d30ca9fb79a385f6df796"
OLD_STATE_DIGEST = "0caa0abacbafdb1d2631888383ac1fe0069a5080b0c7d716e38917dbad2efbad"
OLD_STATE_RAW_SHA256 = "fbfd2de59f3aebd27d7692c06f0cbe99c703b90fdde2ec287d9e24b551a85888"
OLD_RUN_ID = 36255472645
OLD_BAR_COUNT = 181
_SHA40 = re.compile(r"^[0-9a-f]{40}$")


class HistoricalTerminalArchiveError(ValueError):
    pass


def _regular_bytes(path: Path) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise HistoricalTerminalArchiveError("historical input must be an exact regular file")
    return path.read_bytes()


def _source_engine_digest(raw: bytes) -> str:
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise HistoricalTerminalArchiveError("original engine source is not UTF-8") from exc
    return hashlib.sha256(text.replace("\r\n", "\n").replace("\r", "\n").encode("utf-8")).hexdigest()


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(_regular_bytes(path))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise HistoricalTerminalArchiveError("historical artifact is not canonical JSON") from exc
    if not isinstance(value, dict):
        raise HistoricalTerminalArchiveError("historical artifact must be a JSON object")
    return value


def verify_historical(
    *,
    manifest_path: Path,
    state_path: Path,
    old_engine_path: Path,
    old_run_path: Path,
) -> dict[str, Any]:
    config, _ = forward.load_contract(manifest_path.resolve())
    raw_state = _regular_bytes(state_path)
    state = _load_json(state_path)
    if (
        hashlib.sha256(raw_state).hexdigest() != OLD_STATE_RAW_SHA256
        or state.get("state_digest") != OLD_STATE_DIGEST
        or state.get("engine_sha256") != OLD_ENGINE_SHA256
        or state.get("latest_source_sha") != OLD_SOURCE_SHA
        or state.get("last_run_id") != OLD_RUN_ID
        or state.get("completed_bar_count") != OLD_BAR_COUNT
        or state.get("status") != "QUARANTINED"
        or state.get("decision") != "paper_forward_failed_no_promotion"
        or state.get("paper_only") is not True
        or state.get("live_trading_enabled") is not False
        or state.get("private_credentials_used") is not False
        or state.get("automatic_live_promotion") is not False
        or _source_engine_digest(_regular_bytes(old_engine_path)) != OLD_ENGINE_SHA256
    ):
        raise HistoricalTerminalArchiveError("untrusted or altered legacy terminal Paper evidence")
    # Re-validate every original event digest, sequential chain and authority
    # using the exact verified ORIGINAL code digest, never today's engine hash.
    forward.verify_state(state, config, OLD_ENGINE_SHA256)
    original_run = _load_json(old_run_path)
    if (
        original_run.get("id") != OLD_RUN_ID
        or original_run.get("head_sha") != OLD_SOURCE_SHA
        or original_run.get("name") != "Bybit prospective Paper forward v1"
        or original_run.get("head_branch") != "main"
        or original_run.get("event") != "schedule"
        or original_run.get("status") != "completed"
        or original_run.get("conclusion") != "success"
        or original_run.get("html_url")
           != "https://github.com/saladinayoubi1/lbank-research-automation/actions/runs/" + str(OLD_RUN_ID)
    ):
        raise HistoricalTerminalArchiveError("historical producing GitHub run identity rejected")
    return state


def _receipt_core(
    state: Mapping[str, Any], *, current_source_sha: str, current_run_id: int,
) -> dict[str, Any]:
    if not _SHA40.fullmatch(current_source_sha):
        raise HistoricalTerminalArchiveError("current run source SHA invalid")
    if (
        type(current_run_id) is not int or current_run_id <= OLD_RUN_ID
        or current_source_sha == OLD_SOURCE_SHA
    ):
        raise HistoricalTerminalArchiveError("archive must be made by a subsequent different exact source run")
    return {
        "schema": SCHEMA,
        "original_source_sha": OLD_SOURCE_SHA,
        "original_engine_sha256": OLD_ENGINE_SHA256,
        "original_run_id": OLD_RUN_ID,
        "original_state_digest": OLD_STATE_DIGEST,
        "original_state_raw_sha256": OLD_STATE_RAW_SHA256,
        "original_status": "QUARANTINED",
        "original_completed_bar_count": OLD_BAR_COUNT,
        "original_last_execution_utc": state["last_execution_utc"],
        "current_source_sha": current_source_sha,
        "current_run_id": current_run_id,
        "historical_state_unchanged": True,
        "historical_source_verified": True,
        "historical_run_identity_verified": True,
        "historical_events_digest_chain_verified": True,
        "historical_runtime_requalified_for_current_engine": False,
        "new_bars_processed": 0,
        "paper_qualification": "FAILED_HISTORICAL_QUARANTINED",
        "new_paper_admission": False,
        "owner_paper_journal_touched": False,
        "live_trading_enabled": False,
        "private_credentials_used": False,
        "automatic_paper_promotion": False,
    }


def _digest(data: Mapping[str, Any]) -> str:
    return forward._digest(data)  # noqa: SLF001 - exact canonical JSON digest


def archive(
    *,
    manifest_path: Path, state_path: Path, old_engine_path: Path,
    old_run_path: Path, current_source_sha: str, current_run_id: int,
    output: Path,
) -> dict[str, Any]:
    if output.exists():
        raise HistoricalTerminalArchiveError("never overwrite a previous historical quarantine archive receipt")
    state = verify_historical(
        manifest_path=manifest_path, state_path=state_path,
        old_engine_path=old_engine_path, old_run_path=old_run_path,
    )
    core = _receipt_core(state, current_source_sha=current_source_sha, current_run_id=current_run_id)
    receipt = {**core, "receipt_digest": _digest(core)}
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + f".{os.getpid()}.tmp")
    try:
        temporary.write_text(
            json.dumps(receipt, sort_keys=True, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, output)
    finally:
        temporary.unlink(missing_ok=True)
    return receipt


def verify_receipt(
    *,
    manifest_path: Path, state_path: Path, old_engine_path: Path,
    old_run_path: Path, current_source_sha: str, current_run_id: int,
    receipt_path: Path,
) -> dict[str, Any]:
    state = verify_historical(
        manifest_path=manifest_path, state_path=state_path,
        old_engine_path=old_engine_path, old_run_path=old_run_path,
    )
    receipt = _load_json(receipt_path)
    core = _receipt_core(state, current_source_sha=current_source_sha, current_run_id=current_run_id)
    if receipt != {**core, "receipt_digest": _digest(core)}:
        raise HistoricalTerminalArchiveError("quarantine archive receipt is not exact")
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("archive", "verify"))
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--old-engine", type=Path, required=True)
    parser.add_argument("--old-run", type=Path, required=True)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--run-id", required=True, type=int)
    parser.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args()
    common = dict(
        manifest_path=args.manifest, state_path=args.state,
        old_engine_path=args.old_engine, old_run_path=args.old_run,
        current_source_sha=args.source_sha, current_run_id=args.run_id,
    )
    result = (
        archive(output=args.receipt, **common)
        if args.mode == "archive" else
        verify_receipt(receipt_path=args.receipt, **common)
    )
    print(json.dumps({
        "schema": result["schema"], "original_run_id": result["original_run_id"],
        "original_state_digest": result["original_state_digest"],
        "original_status": result["original_status"],
        "original_completed_bar_count": result["original_completed_bar_count"],
        "current_source_sha": result["current_source_sha"],
        "current_run_id": result["current_run_id"],
        "receipt_digest": result["receipt_digest"],
        "historical_runtime_requalified_for_current_engine": False,
        "new_paper_admission": False, "live_trading_enabled": False,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
