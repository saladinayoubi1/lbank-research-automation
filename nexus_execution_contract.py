"""Machine-enforced execution completeness contract for NEXUS tasks."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
DEFAULT_CONTRACT = ROOT / "config" / "nexus-execution-contract.json"
MAX_BYTES = 128_000
ROOT_KEYS = {
    "version", "purpose", "requiredBeforeExecution", "requiredPerTask",
    "resourceRouting", "omissionGuards", "phaseCloseChecklist", "statusVocabulary",
}
EXPECTED_TASK_FIELDS = {
    "task_id", "lane", "deliverable_or_gate", "acceptance_criterion", "assigned_resource",
    "dependencies", "execution_action", "verification_method", "durable_evidence_location", "status",
}
EXPECTED_PRE_EXECUTION = {
    "recover_current_repository_state", "read_OPERATING_RULES", "identify_phase_and_frozen_exit_gates",
    "enumerate_available_resources", "enumerate_executable_independent_tasks",
    "map_each_task_to_acceptance_criterion", "map_each_task_to_best_resource",
    "record_dependencies_and_blockers", "confirm_authority_boundary",
}


class ExecutionContractError(ValueError):
    pass


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ExecutionContractError(f"duplicate JSON key: {key!r}")
        result[key] = value
    return result


def _string_list(value: Any, path: str, *, allow_empty: bool = False) -> list[str]:
    if not isinstance(value, list) or (not value and not allow_empty):
        raise ExecutionContractError(f"{path} must be a {'possibly empty' if allow_empty else 'non-empty'} string list")
    if any(not isinstance(item, str) or not item for item in value):
        raise ExecutionContractError(f"{path} contains an invalid value")
    if len(value) != len(set(value)):
        raise ExecutionContractError(f"{path} contains duplicates")
    return value


def validate_contract(contract: Any) -> dict[str, Any]:
    if not isinstance(contract, dict):
        raise ExecutionContractError("contract must be an object")
    missing, unknown = ROOT_KEYS - set(contract), set(contract) - ROOT_KEYS
    if missing or unknown:
        raise ExecutionContractError(f"contract schema mismatch; missing={sorted(missing)}, unknown={sorted(unknown)}")
    if contract["version"] != 1:
        raise ExecutionContractError("contract version must equal 1")
    if set(_string_list(contract["requiredBeforeExecution"], "requiredBeforeExecution")) != EXPECTED_PRE_EXECUTION:
        raise ExecutionContractError("requiredBeforeExecution is incomplete or changed")
    if set(_string_list(contract["requiredPerTask"], "requiredPerTask")) != EXPECTED_TASK_FIELDS:
        raise ExecutionContractError("requiredPerTask is incomplete or changed")
    statuses = set(_string_list(contract["statusVocabulary"], "statusVocabulary"))
    if not {"QUEUED", "ACTIVE", "VERIFIED", "UNVERIFIED", "BLOCKED", "BACKLOG", "UNAVAILABLE"} <= statuses:
        raise ExecutionContractError("statusVocabulary is incomplete")
    routing = contract["resourceRouting"]
    if not isinstance(routing, dict) or not routing:
        raise ExecutionContractError("resourceRouting must be a non-empty object")
    for name, resources in routing.items():
        if not isinstance(name, str) or not name:
            raise ExecutionContractError("resourceRouting contains invalid route")
        _string_list(resources, f"resourceRouting.{name}")
    guards = contract["omissionGuards"]
    if not isinstance(guards, dict) or not guards or any(value is not True for value in guards.values()):
        raise ExecutionContractError("every omission guard must be enabled")
    _string_list(contract["phaseCloseChecklist"], "phaseCloseChecklist")
    if not isinstance(contract["purpose"], str) or not contract["purpose"]:
        raise ExecutionContractError("purpose must be non-empty")
    return contract


def load_contract(path: Path = DEFAULT_CONTRACT) -> dict[str, Any]:
    if not path.is_file() or path.is_symlink():
        raise ExecutionContractError("execution contract must be a regular non-symlink file")
    raw = path.read_bytes()
    if len(raw) > MAX_BYTES:
        raise ExecutionContractError(f"execution contract exceeds {MAX_BYTES}-byte limit")
    try:
        parsed = json.loads(raw, object_pairs_hook=_unique_object)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ExecutionContractError(f"invalid execution contract JSON: {exc}") from exc
    return validate_contract(parsed)


def validate_task_record(task: Any, contract: dict[str, Any] | None = None) -> dict[str, Any]:
    active_contract = validate_contract(contract) if contract is not None else load_contract()
    if not isinstance(task, dict):
        raise ExecutionContractError("task record must be an object")
    required = set(active_contract["requiredPerTask"])
    missing = required - set(task)
    if missing:
        raise ExecutionContractError(f"task record missing required fields: {sorted(missing)}")
    for field in required - {"dependencies"}:
        if not isinstance(task[field], str) or not task[field].strip():
            raise ExecutionContractError(f"task.{field} must be a non-empty string")
    _string_list(task["dependencies"], "task.dependencies", allow_empty=True)
    if task["status"] not in active_contract["statusVocabulary"]:
        raise ExecutionContractError("task.status is unsupported")
    all_resources = {
        resource
        for resources in active_contract["resourceRouting"].values()
        for resource in resources
    }
    if task["assigned_resource"] not in all_resources:
        raise ExecutionContractError("task.assigned_resource is not registered")
    if task["status"] == "VERIFIED" and not task["durable_evidence_location"].strip():
        raise ExecutionContractError("VERIFIED task requires durable evidence")
    return task


def validate_pre_execution_record(record: Any, contract: dict[str, Any] | None = None) -> dict[str, bool]:
    active_contract = validate_contract(contract) if contract is not None else load_contract()
    if not isinstance(record, dict):
        raise ExecutionContractError("pre-execution record must be an object")
    required = set(active_contract["requiredBeforeExecution"])
    missing, unknown = required - set(record), set(record) - required
    if missing or unknown:
        raise ExecutionContractError(f"pre-execution record mismatch; missing={sorted(missing)}, unknown={sorted(unknown)}")
    failed = sorted(key for key, value in record.items() if value is not True)
    if failed:
        raise ExecutionContractError(f"pre-execution requirements not satisfied: {failed}")
    return record
