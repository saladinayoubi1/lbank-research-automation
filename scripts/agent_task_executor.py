from __future__ import annotations

import argparse
import base64
import json
import os
import subprocess
from pathlib import Path
from typing import Any

DISPATCH_KEYS = {
    "schema_version", "task_id", "lease_id", "correlation_id", "dispatch_id", "worker_id",
    "transport", "phase", "gate", "title", "required_capabilities", "acceptance",
    "authority", "attempt",
}
AGENT_REVIEW_PREFIX = "You are a bounded NEXUS repository reviewer."


def _bounded_id(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 160:
        raise ValueError(f"{field} must be a non-empty bounded string")
    return value


def decode_payload(value: str) -> dict[str, Any]:
    data = json.loads(base64.urlsafe_b64decode(value.encode("ascii")).decode("utf-8"))
    if not isinstance(data, dict) or set(data) != DISPATCH_KEYS:
        raise ValueError("dispatch payload schema mismatch")
    if data["schema_version"] != 2:
        raise ValueError("unsupported dispatch payload schema")
    for field in ("task_id", "lease_id", "correlation_id", "dispatch_id", "worker_id", "transport"):
        _bounded_id(data[field], field)
    if int(data["authority"]) >= 4:
        raise ValueError("L4 payload execution is forbidden")
    if data["transport"] not in {"github-cloud", "deepseek", "windows"}:
        raise ValueError("unsupported dispatch transport")
    if not isinstance(data["required_capabilities"], list) or not all(isinstance(item, str) for item in data["required_capabilities"]):
        raise ValueError("required_capabilities must be a string list")
    if not isinstance(data["acceptance"], list) or not all(isinstance(item, str) for item in data["acceptance"]):
        raise ValueError("acceptance must be a string list")
    return data


def run(cmd: list[str], timeout: int = 600) -> dict[str, Any]:
    proc = subprocess.run(cmd, text=True, capture_output=True, timeout=timeout, check=False)
    return {
        "ok": proc.returncode == 0,
        "returncode": proc.returncode,
        "stdout": proc.stdout[-12000:],
        "stderr": proc.stderr[-12000:],
    }


def deterministic_execution(payload: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    task_id = payload["task_id"]
    if task_id in {"P4-MGR-001", "P4-MGR-002"}:
        result = run(["python", "-m", "pytest", "-q", "tests/test_agent_manager.py", "tests/test_agent_manager_runner.py", "tests/test_agent_transport.py"])
        return ("success" if result["ok"] else "failure", {"executor": "pytest", "tests": result, "failure_class": "deterministic_test_failure" if not result["ok"] else None})
    if task_id == "P4-DATA-001":
        checks = []
        for path in ["config", "data", "tests"]:
            checks.append({"path": path, "exists": Path(path).exists()})
        ok = all(item["exists"] for item in checks)
        return ("success" if ok else "failure", {"executor": "filesystem-preflight", "checks": checks, "failure_class": "data_prerequisite_missing" if not ok else None})
    # Architecture/UI/Event tasks require reasoning, not a fabricated deterministic success.
    return "failure", {
        "failure_class": "specialized_reasoning_provider_required",
        "executor": "bounded-deterministic",
        "message": "Task requires a reasoning-capable worker; deterministic executor refused to fabricate completion.",
    }


def deepseek_execution(payload: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    if os.environ.get("NEXUS_DEEPSEEK_PAID_ROUTING_ALLOWED") != "1":
        return "failure", {
            "failure_class": "provider_budget_gate_closed",
            "provider": "deepseek",
            "correlation_id": payload["correlation_id"],
        }
    from deepseek_provider import DeepSeekError, chat

    bounded_metadata = {
        "task_id": payload["task_id"],
        "correlation_id": payload["correlation_id"],
        "role": payload["worker_id"],
        "title": payload.get("title", ""),
        "required_capabilities": payload.get("required_capabilities", []),
        "acceptance": payload.get("acceptance", []),
        "instruction": "Review only this bounded repository task metadata. Return concise findings, evidence_needed, best_next_action, and risks. Do not claim repository changes or tests you did not perform. Do not request credentials, private data, live trading, production mutation, billing or signing authority.",
    }
    prompt = AGENT_REVIEW_PREFIX + "\n" + json.dumps(bounded_metadata, ensure_ascii=False, sort_keys=True)
    try:
        result = chat(
            [{"role": "user", "content": prompt}],
            complexity="routine",
            max_tokens=900,
            ledger_path="build/deepseek/usage.json",
            timeout=90,
        )
    except DeepSeekError as exc:
        return "failure", {
            "failure_class": "deepseek_provider_error",
            "provider": "deepseek",
            "correlation_id": payload["correlation_id"],
            "error": str(exc),
        }
    return "success", {
        "provider": "deepseek",
        "model": result["model"],
        "content": result["content"],
        "cost_usd": result["cost_usd"],
        "month_spent_usd": result["month_spent_usd"],
        "month_remaining_usd": result["month_remaining_usd"],
        "correlation_id": payload["correlation_id"],
        "dispatch_id": payload["dispatch_id"],
    }


def execute(payload: dict[str, Any], transport: str) -> dict[str, Any]:
    if transport != payload["transport"]:
        raise ValueError("transport mismatch")
    if transport == "deepseek":
        outcome, evidence = deepseek_execution(payload)
    elif transport in {"github-cloud", "windows"}:
        outcome, evidence = deterministic_execution(payload)
    else:
        raise ValueError("unsupported transport")
    return {
        "schema_version": 2,
        "task_id": payload["task_id"],
        "lease_id": payload["lease_id"],
        "correlation_id": payload["correlation_id"],
        "dispatch_id": payload["dispatch_id"],
        "worker_id": payload["worker_id"],
        "transport": transport,
        "outcome": outcome,
        "evidence": evidence,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Execute one bounded NEXUS agent task")
    parser.add_argument("--payload-b64", required=True)
    parser.add_argument("--transport", required=True)
    parser.add_argument("--output", default="result.json")
    args = parser.parse_args()
    payload = decode_payload(args.payload_b64)
    result = execute(payload, args.transport)
    Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["outcome"] == "success" else 2


if __name__ == "__main__":
    raise SystemExit(main())
