from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from gate20_evidence_security import verify_gate20_evidence_strict
from phase4_e2e import Phase4E2EError, run_phase4_gate20


def _validated_sha(value: str, field: str) -> str:
    if not isinstance(value, str) or len(value) != 40:
        raise Phase4E2EError(f"{field} must be a 40-character Git commit SHA")
    try:
        int(value, 16)
    except ValueError as exc:
        raise Phase4E2EError(f"{field} must be hexadecimal") from exc
    return value.lower()


def require_exact_runtime_head(expected_sha: str, actual_sha: str) -> str:
    """Fail closed unless the executing checkout is the declared evidence SHA."""
    expected = _validated_sha(expected_sha, "source_sha")
    actual = _validated_sha(actual_sha, "runtime_git_head")
    if actual != expected:
        raise Phase4E2EError("runtime Git HEAD does not match source_sha")
    return actual


def current_git_head() -> str:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise Phase4E2EError("unable to resolve runtime Git HEAD")
    return _validated_sha(completed.stdout.strip(), "runtime_git_head")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate and verify Phase 4 Gate 20 same-SHA E2E evidence")
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--workspace", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    source_sha = require_exact_runtime_head(args.source_sha, current_git_head())
    output = args.output.resolve()
    workspace = (args.workspace or output.parent / "gate20-workspace").resolve()
    evidence = run_phase4_gate20(source_sha, workspace)
    verify_gate20_evidence_strict(
        evidence,
        expected_source_sha=source_sha,
        verification_workspace=workspace.parent / "gate20-independent-verification",
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(evidence, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "gate": 20,
        "status": "PASS",
        "source_sha": evidence["source_sha"],
        "runtime_git_head": source_sha,
        "evidence_digest": evidence["evidence_digest"],
        "paper_only": evidence["paper_only"],
        "audit_head_digest": evidence["audit"]["head_event_digest"],
        "state_digest": evidence["pipeline"]["state_digest"],
        "dashboard_read_only": evidence["dashboard"]["read_only"],
        "replay_identical": evidence["recovery"]["paper_replay_identical"],
        "owner_sensitive_allowed": evidence["ai_control"]["owner_sensitive_allowed"],
        "independent_security_rerun": True,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
