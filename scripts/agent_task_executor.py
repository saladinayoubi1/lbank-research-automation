from __future__ import annotations

import argparse
import base64
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

DISPATCH_KEYS = {
    "schema_version", "task_id", "lease_id", "correlation_id", "dispatch_id", "worker_id",
    "transport", "phase", "gate", "title", "required_capabilities", "acceptance",
    "authority", "attempt",
}
AGENT_REVIEW_PREFIX = "You are a bounded NEXUS repository reviewer."

# Phase 4 fixed proof workloads are deliberately hard-coded. A dispatch may
# select one of these identifiers, but it cannot inject a path or command.
# Each mapped task runs only its canonical acceptance contract; dispatch input
# cannot substitute a path, command, phase, or transport.
PHASE4_WORKLOADS: dict[str, dict[str, Any]] = {
    "P4-UI-001": {
        "transports": ("github-cloud",),
        "suite": ("tests/test_web_ui.py",),
        "purpose": "source-bound-responsive-read-only-shell-and-degraded-state-proof",
    },
    "P4-EVENT-001": {
        "transports": ("github-cloud",),
        "suite": ("tests/test_nexus_event_store.py",),
        "purpose": "source-bound-event-store-canonical-chain-replay-and-corruption-proof",
    },
}

# Phase 7 proof workloads are deliberately hard-coded. A dispatch may select one
# of these identifiers, but it cannot inject a path or command. This keeps the
# worker useful for real resource consumption while preserving the execution
# boundary: Research / Backtest / Paper only, no credentials and no Live/L4.
PHASE7_WORKLOADS: dict[str, dict[str, Any]] = {
    "P7-LAPTOP-CANONICAL": {
        "transports": ("windows",),
        "suite": (
            "tests/test_phase5_data_binding.py",
            "tests/test_canonical_backtest_boundary.py",
            "tests/test_product_offline_runtime.py",
        ),
        "offline_capable": True,
        "network_required": False,
        "purpose": "canonical-data-and-offline-backtest-proof",
    },
    "P7-CLOUD-VERIFY": {
        "transports": ("github-cloud",),
        "suite": (
            "tests/test_agent_transport.py",
            "tests/test_phase7_resource_manager.py",
            "tests/test_phase7_mission_projection.py",
        ),
        "offline_capable": False,
        "network_required": False,
        "purpose": "resource-routing-transport-and-mission-verification",
    },
    "P7-RESEARCH-STRATEGY": {
        "transports": ("github-cloud",),
        "suite": (
            "tests/test_phase5_strategy_factory.py",
            "tests/test_phase6_research_pipeline.py",
            "tests/test_downstream_provenance_boundary.py",
        ),
        "offline_capable": False,
        "network_required": False,
        "purpose": "research-strategy-and-provenance-proof",
    },
    "P7-PAPER-PERFORMANCE": {
        "transports": ("github-cloud",),
        "suite": (
            "tests/test_deterministic_risk.py",
            "tests/test_paper_execution.py",
            "tests/test_paper_event_store.py",
            "tests/test_performance_metrics.py",
            "tests/test_phase7_e2e_proof.py",
        ),
        "offline_capable": False,
        "network_required": False,
        "purpose": "risk-paper-performance-and-e2e-proof",
    },
}


def _bounded_id(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 160:
        raise ValueError(f"{field} must be a non-empty bounded string")
    return value


def decode_payload(value: str) -> dict[str, Any]:
    if not isinstance(value, str) or not value or len(value) > 64_000:
        raise ValueError("dispatch payload must be a non-empty bounded string")
    try:
        decoded = base64.b64decode(value.encode("ascii"), altchars=b"-_", validate=True)
        data = json.loads(decoded.decode("utf-8"))
    except (UnicodeEncodeError, UnicodeDecodeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError("dispatch payload encoding is invalid") from exc
    qa_keys = {"research_producer_lease_id", "research_producer_receipt_digest",
               "research_producer_source_sha"}
    followon_keys = {
        "research_predecessor_source_sha", "research_predecessor_receipt_digest",
        "research_predecessor_qa_digest", "research_predecessor_ledger_digest",
        "research_predecessor_mechanism",
    }
    if not isinstance(data, dict):
        raise ValueError("dispatch payload schema mismatch")
    keys = set(data)
    is_followon = data.get("task_id") == "P7-RESEARCH-COMPOSITE-002"
    is_research_qa = (
        data.get("task_id") in {"P7-RESEARCH-COMPOSITE-001", "P7-RESEARCH-COMPOSITE-002"}
        and data.get("worker_id") == "qa-verifier-agent"
    )
    expected = DISPATCH_KEYS | (qa_keys if is_research_qa else set()) | (
        followon_keys if is_followon else set()
    )
    if keys != expected:
        raise ValueError("dispatch payload schema mismatch")
    if is_followon:
        # Bound repo-root import, never a dispatch-selected Python module.
        repo_root = str(Path(__file__).resolve().parents[1])
        if repo_root not in sys.path:
            sys.path.insert(0, repo_root)
        from nexus_research_missions import validate_ancestry
        validate_ancestry({k: data[k] for k in followon_keys})
    if is_research_qa:
        if keys != expected or not qa_keys.issubset(keys):
            raise ValueError("Research independent QA producer binding absent")
        if (
            not isinstance(data["research_producer_lease_id"], str)
            or len(data["research_producer_lease_id"]) > 160
            or not data["research_producer_lease_id"]
            or not isinstance(data["research_producer_receipt_digest"], str)
            or len(data["research_producer_receipt_digest"]) != 64
            or any(c not in "0123456789abcdef" for c in data["research_producer_receipt_digest"])
            or not isinstance(data["research_producer_source_sha"], str)
            or len(data["research_producer_source_sha"]) != 40
            or any(c not in "0123456789abcdef" for c in data["research_producer_source_sha"])
        ):
            raise ValueError("independent QA source or producer receipt is invalid")
    if data["schema_version"] != 2:
        raise ValueError("unsupported dispatch payload schema")
    for field in ("task_id", "lease_id", "correlation_id", "dispatch_id", "worker_id", "transport"):
        _bounded_id(data[field], field)
    if isinstance(data["authority"], bool) or not isinstance(data["authority"], int):
        raise ValueError("authority must be an integer")
    if data["authority"] >= 4 or data["authority"] < 0:
        raise ValueError("L4 or invalid payload execution is forbidden")
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


def _bounded_pytest_workload(
    payload: dict[str, Any],
    transport: str,
    spec: dict[str, Any],
    *,
    expected_phase: int,
) -> tuple[str, dict[str, Any]]:
    task_id = payload["task_id"]
    if payload.get("phase") != expected_phase:
        return "failure", {
            "failure_class": "workload_phase_mismatch",
            "executor": "bounded-pytest",
            "workload_id": task_id,
            "expected_phase": expected_phase,
            "observed_phase": payload.get("phase"),
        }
    allowed = tuple(spec["transports"])
    if transport not in allowed:
        return "failure", {
            "failure_class": "workload_transport_mismatch",
            "executor": "bounded-pytest",
            "workload_id": task_id,
            "allowed_transports": list(allowed),
            "observed_transport": transport,
        }
    suite = tuple(spec["suite"])
    result = run([sys.executable, "-m", "pytest", "-q", *suite], timeout=900)
    ok = bool(result["ok"])
    return ("success" if ok else "failure"), {
        "executor": "bounded-pytest",
        "workload_id": task_id,
        "purpose": spec["purpose"],
        "suite": list(suite),
        "transport": transport,
        "tests": result,
        "failure_class": None if ok else "deterministic_test_failure",
    }


def _phase7_pytest_workload(payload: dict[str, Any], transport: str, spec: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    outcome, evidence = _bounded_pytest_workload(payload, transport, spec, expected_phase=7)
    evidence["offline_capable"] = bool(spec["offline_capable"])
    evidence["network_required"] = bool(spec["network_required"])
    return outcome, evidence


def deterministic_execution(payload: dict[str, Any], transport: str) -> tuple[str, dict[str, Any]]:
    task_id = payload["task_id"]
    phase4 = PHASE4_WORKLOADS.get(task_id)
    if phase4 is not None:
        return _bounded_pytest_workload(payload, transport, phase4, expected_phase=4)
    phase7 = PHASE7_WORKLOADS.get(task_id)
    if phase7 is not None:
        return _phase7_pytest_workload(payload, transport, phase7)
    if task_id in {"P7-RESEARCH-COMPOSITE-001", "P7-RESEARCH-COMPOSITE-002"}:
        # This is a real numerical workload, not the historical Phase-7 pytest
        # proof. Only the bounded Research Agent's cloud lease may start it.
        worker = payload.get("worker_id")
        if payload.get("phase") != 7 or transport != "github-cloud" or worker not in {"research-agent", "qa-verifier-agent"}:
            return "failure", {
                "executor": "nexus-real-composite-backtest",
                "failure_class": "research_lease_worker_phase_or_transport_mismatch",
                "auto_demo_promotion": False,
                "live_enabled": False,
                "qualification_authority": False,
            }
        # Executed as scripts/agent_task_executor.py, so sys.path[0] is
        # scripts/. Resolve only this checked-out repository root; never
        # import workload code from a caller-supplied path or dispatch value.
        repo_root = str(Path(__file__).resolve().parents[1])
        if repo_root not in sys.path:
            sys.path.insert(0, repo_root)
        from nexus_agent_composite_runtime import (
            RealResearchError, run_lease, verify_independently,
        )
        try:
            source = os.environ.get("GITHUB_SHA", "")
            if worker == "qa-verifier-agent":
                # QA has its own Agent Manager lease, but independently replays
                # the specific producer's original prior state and numeric work.
                if source != payload["research_producer_source_sha"]:
                    raise RealResearchError("QA source differs from the producer's immutable source")
                proof = verify_independently(
                    archive_root=Path("build/agent-research/archive"),
                    previous_ledger=Path("build/agent-research/producer/result/previous-ledger.json"),
                    source_sha=source,
                    lease_id=payload["research_producer_lease_id"],
                    result_dir=Path("build/agent-research/producer/result"),
                    output=Path("build/agent-research/qa-evidence.json"),
                )
                if proof["producer_receipt_digest"] != payload["research_producer_receipt_digest"]:
                    raise RealResearchError("QA bound to a different producer digest")
                if task_id == "P7-RESEARCH-COMPOSITE-002":
                    original_receipt = json.loads(Path(
                        "build/agent-research/producer/result/agent-receipt.json"
                    ).read_text(encoding="utf-8"))
                    if (
                        original_receipt.get("prior_ledger_digest")
                        != payload["research_predecessor_ledger_digest"]
                        or original_receipt.get("mechanism")
                        == payload["research_predecessor_mechanism"]
                    ):
                        raise RealResearchError("QA detected successor frontier mismatch or same causal mechanism")
                return "success", {
                    "executor": "nexus-independent-composite-numeric-qa",
                    "producer_receipt_digest": proof["producer_receipt_digest"],
                    "producer_lease_id": payload["research_producer_lease_id"],
                    "source_sha": proof["source_sha"],
                    "qa_digest": proof["qa_digest"],
                    "independent_qa_complete": True,
                    "qualification_authority": False,
                    "auto_demo_promotion": False,
                    "live_enabled": False,
                }
            # The secure runner's preparer must have staged both immutable
            # inputs from verified artifacts. No first-mechanism reset fallback.
            evidence = run_lease(
                archive_root=Path("build/agent-research/archive"),
                previous_ledger=Path("build/agent-research/previous-ledger.json"),
                source_sha=source, lease_id=payload["lease_id"],
                output_dir=Path("build/agent-research/result"),
            )
            if task_id == "P7-RESEARCH-COMPOSITE-002" and (
                evidence["prior_ledger_digest"] != payload["research_predecessor_ledger_digest"]
                or evidence["mechanism"] == payload["research_predecessor_mechanism"]
            ):
                raise RealResearchError("successor did not advance to a different QA-bound causal mechanism")
            return "success", {
                "executor": "nexus-real-composite-backtest",
                "workload_id": task_id,
                "lease_id": payload["lease_id"],
                "mechanism": evidence["mechanism"],
                "config_fingerprint": evidence["config_fingerprint"],
                "archive_sha256": evidence["archive_sha256"],
                "source_sha": evidence["source_sha"],
                "prior_ledger_digest": evidence["prior_ledger_digest"],
                "report_digest": evidence["report_digest"],
                "ledger_digest": evidence["ledger_digest"],
                "receipt_digest": evidence["receipt_digest"],
                "validation": evidence["validation"],
                "independent_qa_complete": False,
                "qualification_authority": False,
                "auto_demo_promotion": False,
                "live_enabled": False,
            }
        except (OSError, ValueError, RuntimeError) as exc:
            return "failure", {
                "executor": "nexus-real-composite-backtest",
                "failure_class": "verified_research_execution_failed",
                "reason": str(exc)[:600],
                "auto_demo_promotion": False,
                "live_enabled": False,
                "qualification_authority": False,
            }
    if task_id in {"P4-MGR-001", "P4-MGR-002"}:
        result = run([sys.executable, "-m", "pytest", "-q", "tests/test_agent_manager.py", "tests/test_agent_manager_runner.py", "tests/test_agent_transport.py"])
        return ("success" if result["ok"] else "failure", {"executor": "pytest", "tests": result, "failure_class": "deterministic_test_failure" if not result["ok"] else None})
    if task_id == "P4-DATA-001":
        checks = []
        for path in ["config", "data", "tests"]:
            checks.append({"path": path, "exists": Path(path).exists()})
        ok = all(item["exists"] for item in checks)
        return ("success" if ok else "failure", {"executor": "filesystem-preflight", "checks": checks, "failure_class": "data_prerequisite_missing" if not ok else None})
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
        outcome, evidence = deterministic_execution(payload, transport)
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
    parser.add_argument("--payload-b64", default=os.environ.get("NEXUS_TASK_PAYLOAD_B64"))
    parser.add_argument("--transport", default=os.environ.get("NEXUS_TASK_TRANSPORT"))
    parser.add_argument("--output", default="result.json")
    args = parser.parse_args()
    if not args.payload_b64 or not args.transport:
        parser.error("bounded payload and transport are required")
    payload = decode_payload(args.payload_b64)
    result = execute(payload, args.transport)
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["outcome"] == "success" else 2


if __name__ == "__main__":
    raise SystemExit(main())
