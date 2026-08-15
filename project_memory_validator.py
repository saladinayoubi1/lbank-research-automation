from __future__ import annotations

import argparse
import json
import os
import re
import stat
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

CANONICAL_DIR = Path("docs/project_memory")
CANONICAL_FILES = (
    "PROJECT_MEMORY.md",
    "STATE.json",
    "DECISIONS.md",
    "RECOVERY_PLAYBOOK.md",
)
CANONICAL_REQUIRED_READS = [(CANONICAL_DIR / name).as_posix() for name in CANONICAL_FILES]
SHA_RE = re.compile(r"^[0-9a-f]{40}$")


class MemoryValidationError(ValueError):
    pass


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise MemoryValidationError(message)


def _identity(info: os.stat_result) -> tuple[int, int]:
    return (info.st_dev, info.st_ino)


def _stable_signature(info: os.stat_result) -> tuple[int, int, int, int]:
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)


def _read_stable_text(path: Path) -> str:
    """Read one canonical file from a single verified file identity.

    The path is lstat'd before open, the opened descriptor identity must match,
    and descriptor/path signatures must remain unchanged through the read. This
    rejects replacement between path validation and use instead of relying on a
    check-then-read Path.read_text() sequence.
    """
    try:
        before = path.lstat()
    except OSError as exc:
        raise MemoryValidationError(f"canonical Project Memory file unavailable: {path}") from exc
    _require(not stat.S_ISLNK(before.st_mode), f"symlink substitution rejected: {path.as_posix()}")
    _require(stat.S_ISREG(before.st_mode), f"canonical Project Memory path is not a regular file: {path}")

    flags = os.O_RDONLY
    if hasattr(os, "O_BINARY"):
        flags |= os.O_BINARY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW

    fd = -1
    try:
        fd = os.open(path, flags)
        opened = os.fstat(fd)
        _require(stat.S_ISREG(opened.st_mode), f"canonical Project Memory path is not a regular file: {path}")
        _require(_identity(opened) == _identity(before), f"canonical Project Memory file replaced during validation: {path}")

        with os.fdopen(fd, "r", encoding="utf-8", closefd=False) as handle:
            text = handle.read()
            after_read = os.fstat(fd)
        after_path = path.lstat()

        _require(not stat.S_ISLNK(after_path.st_mode), f"symlink substitution rejected: {path.as_posix()}")
        _require(_stable_signature(after_read) == _stable_signature(opened), f"canonical Project Memory file changed during validation: {path}")
        _require(_stable_signature(after_path) == _stable_signature(opened), f"canonical Project Memory file replaced during validation: {path}")
        return text
    except MemoryValidationError:
        raise
    except (OSError, UnicodeError) as exc:
        raise MemoryValidationError(f"canonical Project Memory file changed or unreadable during validation: {path}") from exc
    finally:
        if fd >= 0:
            os.close(fd)


def _load_json_text(text: str, path: Path) -> dict[str, Any]:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise MemoryValidationError(f"malformed state: {path}") from exc
    _require(isinstance(data, dict), "STATE.json must contain an object")
    return data


def _parse_utc(value: Any) -> datetime:
    _require(isinstance(value, str) and value.endswith("Z"), "observed_at_utc must be an RFC3339 UTC timestamp")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise MemoryValidationError("observed_at_utc is malformed") from exc
    _require(parsed.tzinfo is not None, "observed_at_utc must be timezone-aware")
    return parsed.astimezone(timezone.utc)


def validate_repository(root: str | Path = ".", expected_observed_main: str | None = None) -> dict[str, Any]:
    repo = Path(root).resolve()
    memory_dir = repo / CANONICAL_DIR

    for name in CANONICAL_FILES:
        path = memory_dir / name
        _require(not path.is_symlink(), f"symlink substitution rejected: {(CANONICAL_DIR / name).as_posix()}")
        _require(path.is_file(), f"missing canonical Project Memory file: {(CANONICAL_DIR / name).as_posix()}")
        _require(path.resolve().parent == memory_dir.resolve(), f"alternate-path substitution rejected: {path}")

    project_memory = _read_stable_text(memory_dir / "PROJECT_MEMORY.md")
    decisions = _read_stable_text(memory_dir / "DECISIONS.md")
    recovery = _read_stable_text(memory_dir / "RECOVERY_PLAYBOOK.md")
    state_path = memory_dir / "STATE.json"
    state = _load_json_text(_read_stable_text(state_path), state_path)

    _require("## Immutable mission and safety boundary" in project_memory, "PROJECT_MEMORY.md missing safety boundary")
    _require("## Durable-memory contract" in project_memory, "PROJECT_MEMORY.md missing durable-memory contract")
    _require("append-oriented" in decisions.lower(), "DECISIONS.md must preserve append/supersede semantics")
    _require("verify current `main`, open PRs/issues and CI/workflow evidence" in recovery, "RECOVERY_PLAYBOOK.md must require live repository verification")
    _require("presence alone" in recovery.lower(), "RECOVERY_PLAYBOOK.md must reject backup-presence-only recovery claims")

    _require(isinstance(state.get("schema_version"), int) and state["schema_version"] >= 2, "unsupported STATE.json schema_version")
    _require(state.get("project") == "NEXUS / lbank-research-automation", "STATE.json project identity mismatch")

    policy = state.get("memory_policy")
    _require(isinstance(policy, dict), "STATE.json missing memory_policy")
    _require(policy.get("repository_is_durable_source") is True, "repository source-of-truth policy must remain enabled")
    _require(policy.get("chat_is_source_of_truth") is False, "chat must not become source of truth")
    _require(policy.get("secrets_allowed") is False, "Project Memory must remain secret-free")
    _require(policy.get("core_goals_agent_editable") is False, "agents must not gain core-goal authority")

    continuity = state.get("continuity")
    _require(isinstance(continuity, dict), "STATE.json missing continuity section")
    required_reads = continuity.get("required_reads")
    _require(required_reads == CANONICAL_REQUIRED_READS, "required_reads must name exactly the four canonical Project Memory paths")

    drive = continuity.get("drive_backup")
    _require(isinstance(drive, dict), "STATE.json missing drive_backup contract")
    _require(drive.get("secondary_only") is True, "Drive backup must remain secondary-only")
    _require(drive.get("may_authorize_production_recovery") is False, "Drive presence must not authorize production recovery")

    evidence = state.get("current_evidence")
    _require(isinstance(evidence, dict), "STATE.json missing current_evidence")
    observed_main = evidence.get("observed_main_sha")
    _require(isinstance(observed_main, str) and SHA_RE.fullmatch(observed_main) is not None, "observed_main_sha must be a lowercase 40-hex SHA")
    observed_at = _parse_utc(evidence.get("observed_at_utc"))

    _require(expected_observed_main is not None, "authoritative expected observed-main SHA is required")
    _require(SHA_RE.fullmatch(expected_observed_main) is not None, "expected observed-main SHA is malformed")
    _require(observed_main == expected_observed_main, f"stale Project Memory: STATE observed {observed_main}, expected {expected_observed_main}")

    data_policy = state.get("data_policy")
    _require(isinstance(data_policy, dict), "STATE.json missing data_policy")
    _require(data_policy.get("research_only") is True, "research-only boundary must remain enabled")
    _require(data_policy.get("real_trading") is False, "real trading must remain disabled")
    _require(data_policy.get("fabricated_market_data") is False, "fabricated market data must remain forbidden")

    return {
        "schema_version": state["schema_version"],
        "observed_main_sha": observed_main,
        "observed_at_utc": observed_at.isoformat().replace("+00:00", "Z"),
        "canonical_files": list(CANONICAL_REQUIRED_READS),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Fail-closed validator for canonical NEXUS Project Memory")
    parser.add_argument("--root", default=".", help="repository root")
    parser.add_argument("--expected-observed-main", required=True, help="exact authoritative repository SHA that STATE.json must record")
    args = parser.parse_args()
    try:
        result = validate_repository(args.root, args.expected_observed_main)
    except MemoryValidationError as exc:
        print(f"Project Memory validation failed: {exc}")
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
