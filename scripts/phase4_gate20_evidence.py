from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from phase4_e2e import run_phase4_gate20, verify_gate20_evidence


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate and verify Phase 4 Gate 20 same-SHA E2E evidence")
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--workspace", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    output = args.output.resolve()
    workspace = (args.workspace or output.parent / "gate20-workspace").resolve()
    evidence = run_phase4_gate20(args.source_sha, workspace)
    verify_gate20_evidence(evidence, expected_source_sha=args.source_sha)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(evidence, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "gate": 20,
        "status": "PASS",
        "source_sha": evidence["source_sha"],
        "evidence_digest": evidence["evidence_digest"],
        "paper_only": evidence["paper_only"],
        "audit_head_digest": evidence["audit"]["head_event_digest"],
        "state_digest": evidence["pipeline"]["state_digest"],
        "dashboard_read_only": evidence["dashboard"]["read_only"],
        "replay_identical": evidence["recovery"]["paper_replay_identical"],
        "owner_sensitive_allowed": evidence["ai_control"]["owner_sensitive_allowed"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
