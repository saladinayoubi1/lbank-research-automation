from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / ".nexus_runtime" / "phase3"
OUT.mkdir(parents=True, exist_ok=True)


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def write(name: str, payload: dict) -> None:
    path = OUT / name
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp, path)


def evidence() -> int:
    evidence_dir = ROOT / "research" / "evidence"
    files = sorted(str(p.relative_to(ROOT)) for p in evidence_dir.glob("*") if p.is_file())
    required_signals = {
        "market_structure": any("market_structure" in f for f in files),
        "strategy_matrix": any("strategy" in f or "ema" in f for f in files),
        "execution_realism": any("execution" in f or "backtest" in f for f in files),
    }
    payload = {
        "task": "phase3_evidence_inventory",
        "timestamp": now(),
        "files": files,
        "signals": required_signals,
        "verified": all(required_signals.values()),
        "next_action": "expand missing foundational crypto evidence and strategy-family matrices" if not all(required_signals.values()) else "evidence baseline present; continue depth/coverage review",
    }
    write("evidence.json", payload)
    print(json.dumps(payload, sort_keys=True))
    return 0


def strategy() -> int:
    candidates = []
    for path in [ROOT / "research" / "evidence" / "ema_crossover_evidence_matrix.md"]:
        if path.exists():
            candidates.append(str(path.relative_to(ROOT)))
    payload = {
        "task": "strategy_evidence_to_experiment",
        "timestamp": now(),
        "candidate_evidence": candidates,
        "required_validation": [
            "deterministic rules",
            "fees/slippage/funding realism",
            "out-of-sample or walk-forward split",
            "robustness across regimes/symbols/timeframes",
            "benchmark and uncertainty",
            "kill/invalidation criteria",
        ],
        "verified": bool(candidates),
        "next_action": "prepare or run deterministic backtest only from an evidence-backed candidate",
    }
    write("strategy.json", payload)
    print(json.dumps(payload, sort_keys=True))
    return 0


def gates() -> int:
    checks = []
    for rel in [
        "scripts/nexus_orchestrator.js",
        "scripts/deepseek_smoke.py",
        "docs/project_memory/OPERATING_RULES.md",
    ]:
        checks.append({"path": rel, "present": (ROOT / rel).exists()})
    # Paid DeepSeek routing is intentionally fail-closed until its hard budget gate is explicitly enabled.
    deepseek_allowed = os.environ.get("NEXUS_DEEPSEEK_PAID_ROUTING_ALLOWED") == "1"
    payload = {
        "task": "phase3_frozen_gate_probe",
        "timestamp": now(),
        "checks": checks,
        "deepseek_paid_routing_allowed": deepseek_allowed,
        "deepseek_key_present": bool(os.environ.get("DEEPSEEK_API_KEY")),
        "verified": all(item["present"] for item in checks),
        "note": "DeepSeek remains advisory and fail-closed unless both key and paid-routing gate are present.",
    }
    if deepseek_allowed and os.environ.get("DEEPSEEK_API_KEY") and (ROOT / "scripts" / "deepseek_smoke.py").exists():
        proc = subprocess.run([sys.executable, str(ROOT / "scripts" / "deepseek_smoke.py")], cwd=ROOT, text=True, capture_output=True, timeout=60)
        payload["deepseek_smoke"] = {"returncode": proc.returncode, "stdout": proc.stdout[-2000:], "stderr": proc.stderr[-2000:]}
        payload["verified"] = payload["verified"] and proc.returncode == 0
    write("gates.json", payload)
    print(json.dumps(payload, sort_keys=True))
    return 0


def main() -> int:
    if len(sys.argv) != 2 or sys.argv[1] not in {"evidence", "strategy", "gates"}:
        print("usage: nexus_phase3_task.py {evidence|strategy|gates}", file=sys.stderr)
        return 2
    return globals()[sys.argv[1]]()


if __name__ == "__main__":
    raise SystemExit(main())
