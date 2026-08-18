from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SNAPSHOT_CONTRACT = "nexus.agent-manager-snapshot.v1"
MAX_EVENTS = 200
MAX_BYTES = 2_000_000


def _read_object(path: Path, *, required: bool) -> dict[str, Any] | None:
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        if required:
            raise SystemExit(f"required snapshot input missing: {path}")
        return None
    if len(raw) > MAX_BYTES:
        raise SystemExit(f"snapshot input too large: {path}")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SystemExit(f"invalid snapshot input: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise SystemExit(f"snapshot input root is not an object: {path}")
    return value


def _events(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    if path.stat().st_size > MAX_BYTES:
        raise SystemExit("manager event ledger is too large to export safely")
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            value = json.loads(line)
            if isinstance(value, dict):
                rows.append(value)
                if len(rows) > MAX_EVENTS:
                    rows.pop(0)
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description="Export a portable, paper-only NEXUS Agent Manager snapshot")
    parser.add_argument("--config", type=Path, default=Path("config/nexus-agent-manager.json"))
    parser.add_argument("--runtime", type=Path, default=Path("data/agent_coordination/agent_manager_runtime.json"))
    parser.add_argument("--summary", type=Path, default=Path("data/agent_coordination/manager_state.json"))
    parser.add_argument("--events", type=Path, default=Path("data/agent_coordination/manager_events.jsonl"))
    parser.add_argument("--output", type=Path, default=Path("data/agent_coordination/nexus-mission-control-snapshot.json"))
    args = parser.parse_args()

    config = _read_object(args.config, required=True)
    if config.get("schema_version") != 1 or not isinstance(config.get("workers"), list) or not isinstance(config.get("tasks"), list):
        raise SystemExit("agent-manager config is not snapshot eligible")
    runtime = _read_object(args.runtime, required=False)
    if runtime is not None and runtime.get("schema_version") != 1:
        raise SystemExit("agent-manager runtime schema mismatch")
    summary = _read_object(args.summary, required=False)
    payload = {
        "contract_version": SNAPSHOT_CONTRACT,
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "source": "github-cloud-coordinator",
        "config": config,
        "runtime": runtime,
        "summary": summary,
        "events": _events(args.events),
        "paper_only": True,
        "live_trading_authority": False,
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")
    if len(raw) > MAX_BYTES:
        raise SystemExit("portable mission snapshot exceeds bounded size")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    tmp = args.output.with_suffix(args.output.suffix + ".tmp")
    with tmp.open("wb") as handle:
        handle.write(raw); handle.flush(); os.fsync(handle.fileno())
    os.replace(tmp, args.output)
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
