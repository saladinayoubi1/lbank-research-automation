from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import platform
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from phase5_gate9_e2e import Gate9Error, PROOF_SUITES, run_gate9, validate_gate9_evidence


def _canonical_json(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def current_git_head() -> str:
    completed = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=False)
    if completed.returncode != 0:
        raise Gate9Error("unable to resolve runtime Git HEAD")
    return completed.stdout.strip().lower()


def require_exact_head(expected: str) -> str:
    actual = current_git_head()
    if actual != expected.lower():
        raise Gate9Error("runtime Git HEAD does not match source_sha")
    return actual


def run_proof_suites() -> None:
    completed = subprocess.run([sys.executable, "-m", "pytest", "-q", *PROOF_SUITES], cwd=ROOT, check=False)
    if completed.returncode != 0:
        raise Gate9Error("Phase 5 fixed-SHA proof suites failed")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate NEXUS Phase 5 Gate 9 exact-head runtime evidence")
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    source_sha = require_exact_head(args.source_sha)
    run_proof_suites()
    gate9 = run_gate9(source_sha)
    validate_gate9_evidence(gate9, expected_source_sha=source_sha)
    core = {
        "schema_version": "nexus.phase5-gate9-runtime-evidence.v1",
        "source_sha": source_sha,
        "runtime_platform": platform.system(),
        "proof_suites_executed": True,
        "proof_suites": PROOF_SUITES,
        "gate9": gate9,
    }
    artifact = {**core, "runtime_evidence_digest": hashlib.sha256(_canonical_json(core)).hexdigest()}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(artifact, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({
        "gate": 9,
        "status": "PASS",
        "source_sha": source_sha,
        "runtime_platform": artifact["runtime_platform"],
        "runtime_evidence_digest": artifact["runtime_evidence_digest"],
        "gate9_evidence_digest": gate9["evidence_digest"],
        "strategy_terminal_status": gate9["gate6"]["status"],
        "strategy_kill_reasons": gate9["gate6"]["kill_reasons"],
        "gate7_source": gate9["gate7"]["source"],
        "gate8_cutover_ready": gate9["gate8"]["cutover_ready"],
        "paper_only": gate9["paper_only"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
