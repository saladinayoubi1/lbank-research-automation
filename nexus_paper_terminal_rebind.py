from __future__ import annotations

import argparse
import json
import os
import re
from copy import deepcopy
from pathlib import Path
from typing import Any, Mapping

import bybit_prospective_paper_forward_v1 as forward

TERMINAL_DECISIONS = {
    "COMPLETE_REVIEW_REQUIRED": "paper_forward_passed_requires_separate_owner_review",
    "QUARANTINED": "paper_forward_failed_no_promotion",
}
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
PROVENANCE_FIELDS = {"last_run_id", "latest_source_sha", "state_digest"}


class PaperTerminalRebindError(RuntimeError):
    pass


def _engine_sha() -> str:
    return forward._file_sha(Path(forward.__file__).resolve())  # noqa: SLF001 - exact producer binding


def rebind_terminal_state(
    state: Mapping[str, Any],
    config: Mapping[str, Any],
    *,
    source_sha: str,
    run_id: int,
    engine_sha256: str,
) -> dict[str, Any]:
    forward.verify_state(state, config, engine_sha256)
    status = state.get("status")
    if status not in TERMINAL_DECISIONS or state.get("decision") != TERMINAL_DECISIONS.get(status):
        raise PaperTerminalRebindError("Paper state is not a valid terminal review snapshot")
    if not SHA_RE.fullmatch(source_sha):
        raise PaperTerminalRebindError("source SHA must be an exact lowercase Git SHA")
    previous_run_id = state.get("last_run_id")
    if isinstance(previous_run_id, bool) or not isinstance(previous_run_id, int):
        raise PaperTerminalRebindError("terminal Paper state run ID is invalid")
    if isinstance(run_id, bool) or not isinstance(run_id, int) or run_id <= previous_run_id:
        raise PaperTerminalRebindError("workflow run ID did not advance")

    before = {key: deepcopy(value) for key, value in state.items() if key not in PROVENANCE_FIELDS}
    result = deepcopy(dict(state))
    result["last_run_id"] = run_id
    result["latest_source_sha"] = source_sha
    unsigned = dict(result)
    unsigned.pop("state_digest", None)
    result["state_digest"] = forward._digest(unsigned)  # noqa: SLF001 - canonical producer digest

    after = {key: deepcopy(value) for key, value in result.items() if key not in PROVENANCE_FIELDS}
    if after != before:
        raise PaperTerminalRebindError("terminal Paper evidence mutated during provenance rebind")
    if (
        result.get("paper_only") is not True
        or result.get("live_trading_enabled") is not False
        or result.get("private_credentials_used") is not False
        or result.get("automatic_live_promotion") is not False
    ):
        raise PaperTerminalRebindError("terminal Paper authority boundary changed")

    forward.verify_state(result, config, engine_sha256)
    return result


def _atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    target = path.resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + f".{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(dict(value), indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, target)


def run(
    *,
    manifest_path: Path,
    state_path: Path,
    output_path: Path,
    source_sha: str,
    run_id: int,
) -> dict[str, Any]:
    config, _ = forward.load_contract(manifest_path.resolve())
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PaperTerminalRebindError("terminal Paper state is unavailable") from exc
    result = rebind_terminal_state(
        state,
        config,
        source_sha=source_sha,
        run_id=run_id,
        engine_sha256=_engine_sha(),
    )
    _atomic_json(output_path, result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Rebind provenance for a terminal prospective Paper snapshot without collecting or mutating evidence."
    )
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--run-id", type=int, required=True)
    args = parser.parse_args()
    result = run(
        manifest_path=args.manifest,
        state_path=args.state,
        output_path=args.output,
        source_sha=args.source_sha,
        run_id=args.run_id,
    )
    print(json.dumps({
        "status": result["status"],
        "decision": result["decision"],
        "completed_bar_count": result["completed_bar_count"],
        "last_execution_utc": result["last_execution_utc"],
        "state_digest": result["state_digest"],
        "terminal_evidence_frozen": True,
        "paper_only": result["paper_only"],
        "live_trading_enabled": result["live_trading_enabled"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
