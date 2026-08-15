from __future__ import annotations

import argparse
import json
import os
import re
import stat
import subprocess
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


def _git_stdout(repo: Path, *args: str) -> str | None:
    try:
        completed = subprocess.run(
            ["git", "-C", str(repo), *args],
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return completed.stdout.strip()


def _direct_snapshot_integration_is_fresh(repo: Path, observed_main: str, expected_current_main: str) -> bool:
    """Allow only the commit that directly integrates a snapshot to preserve freshness.

    STATE.json necessarily records the main SHA observed before its own integration commit exists.
    The integration commit is therefore accepted only when the authoritative expected SHA is the
    repository HEAD, the recorded SHA is that HEAD's first parent, and the integration commit itself
    changed canonical STATE.json. Any later main advance fails this one-hop rule and becomes stale.
    """
    head = _git_stdout(repo, "rev-parse", "HEAD")
    if head != expected_current_main:
        return False
    parent_line = _git_stdout(repo, "rev-list", "--parents", "-n", "1", "HEAD")
    if not parent_line:
        return False
    parts = parent_line.split()
    if len(parts) < 2 or parts[1] != observed_main:
        return False
    changed = _git_stdout(repo, "diff", "--name-only", parts[1], head)
    if changed is None:
        return False
    changed_paths = {line.strip().replace("\\", "/") for line in changed.splitlines() if line.strip()}
    return (CANONICAL_DIR / "STATE.json").as_posix() in changed_paths


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
    _require("verify current `main`, open prs/issues and ci/workflow evidence" in recovery.lower(), "RECOVERY_PLAYBOOK.md must require live repository verification")
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
    _require(continuity.get("required_reads") == CANONICAL_REQUIRED_READS, "required_reads must name exactly the four canonical Project Memory paths")
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
    freshness_ok = observed_main == expected_observed_main or _direct_snapshot_integration_is_fresh(repo, observed_main, expected_observed_main)
    _require(freshness_ok, f"stale Project Memory: STATE observed {observed_main}, expected {expected_observed_main}")

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
    parser.add_argument("--expected-observed-main", required=True, help="authoritative current repository SHA; STATE must match it or be its direct integration parent")
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
