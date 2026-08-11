from __future__ import annotations

import argparse
import re
import subprocess
from pathlib import Path

import project_memory_validator as pmv

SHA_RE = re.compile(r"^[0-9a-f]{40}$")
PROTECTED_PATHS = {
    "docs/project_memory/PROJECT_MEMORY.md",
    "docs/project_memory/STATE.json",
    "docs/project_memory/DECISIONS.md",
    "docs/project_memory/RECOVERY_PLAYBOOK.md",
    "project_memory_validator.py",
}


def _require_sha(value: str, label: str) -> None:
    if SHA_RE.fullmatch(value) is None:
        raise ValueError(f"{label} must be a lowercase 40-hex SHA")


def changed_paths(base_sha: str, head_sha: str, root: str | Path = ".") -> set[str]:
    _require_sha(base_sha, "base SHA")
    _require_sha(head_sha, "head SHA")
    proc = subprocess.run(
        ["git", "diff", "--name-only", "--diff-filter=ACMRT", base_sha, head_sha, "--"],
        cwd=Path(root),
        check=True,
        capture_output=True,
        text=True,
    )
    return {line.strip().replace("\\", "/") for line in proc.stdout.splitlines() if line.strip()}


def gate_required(paths: set[str]) -> bool:
    return bool(paths & PROTECTED_PATHS)


def validate_pr(root: str | Path, base_sha: str, head_sha: str) -> dict[str, object]:
    paths = changed_paths(base_sha, head_sha, root)
    if not gate_required(paths):
        return {"validated": False, "reason": "no protected Project Memory path changed"}
    result = pmv.validate_repository(root, expected_observed_main=base_sha)
    return {
        "validated": True,
        "observed_main_sha": result["observed_main_sha"],
        "protected_changes": sorted(paths & PROTECTED_PATHS),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Bind Project Memory PR validation to the authoritative PR base SHA")
    parser.add_argument("--root", default=".")
    parser.add_argument("--base-sha", required=True)
    parser.add_argument("--head-sha", required=True)
    args = parser.parse_args()
    try:
        result = validate_pr(args.root, args.base_sha, args.head_sha)
    except (ValueError, subprocess.CalledProcessError, pmv.MemoryValidationError) as exc:
        print(f"Project Memory CI gate failed: {exc}")
        return 2
    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
