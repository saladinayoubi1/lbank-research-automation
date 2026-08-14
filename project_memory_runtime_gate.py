from __future__ import annotations

import argparse
import json
from pathlib import Path

import project_memory_validator as pmv


def assess(root: str | Path, expected_main: str) -> dict[str, object]:
    try:
        result = pmv.validate_repository(root, expected_observed_main=expected_main)
    except pmv.MemoryValidationError as exc:
        return {
            "authoritative": False,
            "reason": "stale_or_conflicting_project_memory",
            "detail": str(exc),
            "expected_main_sha": expected_main,
        }
    return {
        "authoritative": True,
        "reason": "validated",
        "expected_main_sha": expected_main,
        "observed_main_sha": result["observed_main_sha"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Assess whether NEXUS Project Memory may be treated as authoritative")
    parser.add_argument("--root", default=".")
    parser.add_argument("--expected-main", required=True)
    args = parser.parse_args()
    print(json.dumps(assess(args.root, args.expected_main), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
