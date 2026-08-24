"""Fail-closed acceptance verifier for the final NEXUS Paper-only proof mission.

This module does not manufacture runtime evidence.  It consumes the durable
artifacts emitted by the verified Supervisor, Paper performance projection,
resource ledger, and Project Memory projection and binds them to one Git SHA.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any, Mapping, Sequence

from nexus_strategy_paper_supervisor import verify_ledger

SCHEMA = "nexus.final-proof-mission.v1"
_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_RESOURCE_STATES = {"EXECUTED", "UNAVAILABLE", "BLOCKED"}
_REQUIRED_RESOURCES = {"internal_agents", "deepseek", "windows_laptop", "cloud_verifier"}


class FinalProofMissionError(RuntimeError):
    pass


def _canonical(value: Any) -> bytes:
    try:
        return json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise FinalProofMissionError("proof evidence is not canonical JSON") from exc


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _sha(value: Any) -> str:
    normalized = str(value).strip().lower()
    if not _SHA_RE.fullmatch(normalized):
        raise FinalProofMissionError("source_sha must be a 40-character Git SHA")
    return normalized


def _validate_resource_rows(rows: Any, source_sha: str) -> tuple[dict[str, bool], dict[str, str]]:
    checks: dict[str, bool] = {}
    states: dict[str, str] = {}
    if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)):
        return {"resource_ledger": False}, states
    seen: set[str] = set()
    for index, row in enumerate(rows):
        valid = isinstance(row, Mapping)
        resource = str(row.get("resource", "")) if valid else ""
        state = str(row.get("state", "")) if valid else ""
        valid = bool(valid and resource in _REQUIRED_RESOURCES and resource not in seen)
        if valid:
            seen.add(resource)
            states[resource] = state
        valid = bool(valid and state in _RESOURCE_STATES and row.get("source_sha") == source_sha)
        if state == "EXECUTED":
            valid = bool(
                valid
                and row.get("task_id")
                and row.get("lease_id")
                and row.get("result_digest")
                and row.get("evidence_digest")
                and row.get("verifier_digest")
            )
        else:
            valid = bool(valid and row.get("reason_code") and not row.get("task_id"))
        checks[f"resource_{index}"] = valid
    checks["required_resources_declared"] = seen == _REQUIRED_RESOURCES
    checks["real_execution_present"] = any(state == "EXECUTED" for state in states.values())
    checks["independent_cloud_verifier_executed"] = states.get("cloud_verifier") == "EXECUTED"
    return checks, states


def verify_final_proof(bundle: Mapping[str, Any]) -> dict[str, Any]:
    """Verify a complete fixed-SHA proof bundle without trusting producer claims."""
    if not isinstance(bundle, Mapping):
        raise FinalProofMissionError("proof bundle must be an object")
    source_sha = _sha(bundle.get("source_sha"))
    supervisor = bundle.get("supervisor_ledger")
    performance = bundle.get("mission_control_projection")
    memory = bundle.get("project_memory_projection")
    scheduler = bundle.get("scheduler_snapshot")

    supervisor_verification = (
        verify_ledger(supervisor) if isinstance(supervisor, Mapping) else {"decision": "reject"}
    )
    checks: dict[str, bool] = {
        "schema": bundle.get("schema_version") == SCHEMA,
        "paper_only": bundle.get("paper_only") is True,
        "live_disabled": bundle.get("live_trading_authority") is False,
        "supervisor_verified": supervisor_verification.get("decision") == "pass",
        "supervisor_source_bound": isinstance(supervisor, Mapping)
        and supervisor.get("source_sha") == source_sha,
        "mission_control_bound": isinstance(performance, Mapping)
        and performance.get("paper_only") is True
        and performance.get("live_trading_authority") is False
        and performance.get("supervisor_verification_digest")
        == supervisor_verification.get("verification_digest"),
        "memory_projection_bound": isinstance(memory, Mapping)
        and memory.get("observed_main_sha") == source_sha
        and memory.get("proof_bundle_digest") == bundle.get("unsigned_bundle_digest"),
        "zero_idle": isinstance(scheduler, Mapping)
        and scheduler.get("source_sha") == source_sha
        and scheduler.get("ready_unassigned_count") == 0
        and scheduler.get("idle_with_executable_work_count") == 0,
    }
    resource_checks, resource_states = _validate_resource_rows(
        bundle.get("resource_utilization"), source_sha
    )
    checks.update(resource_checks)
    checks["deepseek_truthful"] = resource_states.get("deepseek") in {"EXECUTED", "UNAVAILABLE"}
    checks["windows_truthful"] = resource_states.get("windows_laptop") in {
        "EXECUTED", "UNAVAILABLE", "BLOCKED"
    }

    passed = all(checks.values())
    core = {
        "schema_version": SCHEMA,
        "source_sha": source_sha,
        "decision": "VERIFIED" if passed else "REJECTED",
        "checks": checks,
        "resource_states": dict(sorted(resource_states.items())),
        "paper_only": True,
        "live_trading_authority": False,
        "independent_verifier": "nexus-final-proof-verifier",
    }
    return {**core, "verification_digest": _digest(core)}


def build_unsigned_bundle(
    *,
    source_sha: str,
    supervisor_ledger: Mapping[str, Any],
    mission_control_projection: Mapping[str, Any],
    scheduler_snapshot: Mapping[str, Any],
    resource_utilization: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Build the canonical producer portion; Memory binding is added afterwards."""
    source_sha = _sha(source_sha)
    core = {
        "schema_version": SCHEMA,
        "source_sha": source_sha,
        "paper_only": True,
        "live_trading_authority": False,
        "supervisor_ledger": dict(supervisor_ledger),
        "mission_control_projection": dict(mission_control_projection),
        "scheduler_snapshot": dict(scheduler_snapshot),
        "resource_utilization": [dict(row) for row in resource_utilization],
    }
    unsigned_digest = _digest(core)
    return {
        **core,
        "unsigned_bundle_digest": unsigned_digest,
        "project_memory_projection": {
            "observed_main_sha": source_sha,
            "proof_bundle_digest": unsigned_digest,
            "status": "candidate_pending_independent_verification",
        },
    }


def save_verified_bundle(path: str | Path, bundle: Mapping[str, Any]) -> dict[str, Any]:
    verification = verify_final_proof(bundle)
    if verification["decision"] != "VERIFIED":
        raise FinalProofMissionError("final Proof Mission evidence was rejected")
    payload = {**dict(bundle), "verification": verification}
    payload["bundle_digest"] = _digest(payload)
    target = Path(path).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, target)
    return payload
