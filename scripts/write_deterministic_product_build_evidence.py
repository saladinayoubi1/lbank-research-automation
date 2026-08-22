#!/usr/bin/env python3
"""Write exact-source product metadata without run-specific package bytes."""
from __future__ import annotations

import argparse
import json
import re
from datetime import datetime
from pathlib import Path

SHA = re.compile(r"^[0-9a-f]{40}$")


def write(output: Path, source_sha: str, source_timestamp: str) -> None:
    if not SHA.fullmatch(source_sha):
        raise ValueError("source SHA must be lowercase 40-character Git SHA")
    try:
        parsed = datetime.fromisoformat(source_timestamp.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("source timestamp must be ISO-8601") from exc
    if parsed.tzinfo is None:
        raise ValueError("source timestamp must include timezone")
    payload = {
        "builder": "github-actions/nexus-build-verification/windows-desktop",
        "contract_version": "nexus.product-build-evidence.v1",
        "generated_at": parsed.isoformat().replace("+00:00", "Z"),
        "live_trading_authority": False,
        "paper_only": True,
        "source_sha": source_sha,
        "workflow": "NEXUS Build Verification/windows-desktop",
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, separators=(",", ":"), sort_keys=True) + "\n", encoding="utf-8", newline="\n")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--source-timestamp", required=True)
    args = parser.parse_args()
    try:
        write(args.output, args.source_sha, args.source_timestamp)
    except ValueError as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
