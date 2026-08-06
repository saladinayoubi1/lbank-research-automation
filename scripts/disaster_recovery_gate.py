#!/usr/bin/env python3
"""Fail-closed validation for bounded disaster-recovery exercise evidence."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

MAX_EVIDENCE_BYTES = 1_000_000
MAX_EVIDENCE_AGE_DAYS = 30
REQUIRED_SCENARIOS = {
    "primary-region-loss",
    "backup-corruption",
    "credential-loss",
    "dependency-outage",
}
REQUIRED_OWNER_KEYS = (
    "incident_commander",
    "recovery_operator",
    "security_approver",
)


def fail(message: str) -> None:
    raise ValueError(message)


def load_json(path: Path) -> Any:
    if not path.is_file() or path.is_symlink():
        fail(f"missing or unsafe evidence file: {path.name}")
    if path.stat().st_size > MAX_EVIDENCE_BYTES:
        fail("evidence file exceeds maximum size")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        fail(f"invalid JSON: {exc.msg}")


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def require_bool(obj: dict[str, Any], key: str) -> None:
    if obj.get(key) is not True:
        fail(f"{key} must be explicitly true")


def require_positive_number(obj: dict[str, Any], key: str) -> float:
    value = obj.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        fail(f"{key} must be a positive number")
    return float(value)


def parse_utc(value: Any, key: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        fail(f"{key} must be a UTC timestamp ending in Z")
    try:
        return datetime.fromisoformat(value[:-1] + "+00:00").astimezone(timezone.utc)
    except ValueError:
        fail(f"{key} must be a valid UTC timestamp")


def safe_relative_path(value: Any) -> PurePosixPath:
    if not isinstance(value, str) or not value.strip():
        fail("scenario evidence_ref is required")
    if "\\" in value:
        fail("scenario evidence_ref must use canonical forward slashes")
    ref = PurePosixPath(value)
    if ref.is_absolute() or ".." in ref.parts or "." in ref.parts or str(ref) != value:
        fail("scenario evidence_ref must be a safe canonical relative path")
    return ref


def verify_scenario_evidence(root: Path, exercise_id: str, scenario: dict[str, Any]) -> None:
    ref = safe_relative_path(scenario.get("evidence_ref"))
    expected = scenario.get("evidence_sha256")
    if not isinstance(expected, str) or len(expected) != 64 or any(c not in "0123456789abcdef" for c in expected):
        fail("scenario evidence_sha256 must be lowercase SHA-256")
    candidate = root.joinpath(*ref.parts)
    if not candidate.is_file() or candidate.is_symlink():
        fail("scenario evidence artifact is missing or unsafe")
    try:
        candidate.resolve(strict=True).relative_to(root.resolve(strict=True))
    except (OSError, ValueError):
        fail("scenario evidence artifact escapes evidence root")
    if candidate.stat().st_size > MAX_EVIDENCE_BYTES:
        fail("scenario evidence artifact exceeds maximum size")
    if sha256(candidate) != expected:
        fail("scenario evidence digest mismatch")
    record = load_json(candidate)
    if not isinstance(record, dict):
        fail("scenario evidence artifact must be an object")
    if record.get("exercise_id") != exercise_id:
        fail("scenario evidence exercise mismatch")
    if record.get("scenario") != scenario.get("name"):
        fail("scenario evidence name mismatch")
    require_bool(record, "observed")
    require_bool(record, "recovery_verified")


def validate(evidence_path: Path, *, now: datetime | None = None) -> list[str]:
    evidence = load_json(evidence_path)
    if not isinstance(evidence, dict):
        fail("evidence root must be an object")
    if evidence.get("schema_version") != 2:
        fail("unsupported schema_version")
    if evidence.get("production_authorized") is not False:
        fail("production_authorized must be explicitly false")
    if "max_evidence_age_days" in evidence:
        fail("evidence cannot override verifier freshness policy")

    exercise_id = evidence.get("exercise_id")
    if not isinstance(exercise_id, str) or not exercise_id.strip():
        fail("exercise_id is required")
    source_commit = evidence.get("source_commit")
    workflow_run_id = evidence.get("workflow_run_id")
    policy_version = evidence.get("policy_version")
    if not isinstance(source_commit, str) or len(source_commit) != 40 or any(c not in "0123456789abcdef" for c in source_commit):
        fail("source_commit must be lowercase 40-character SHA")
    if not isinstance(workflow_run_id, int) or workflow_run_id <= 0:
        fail("workflow_run_id must be a positive integer")
    if policy_version != "ADR-0013-v1":
        fail("unsupported policy_version")

    started = parse_utc(evidence.get("started_at"), "started_at")
    completed = parse_utc(evidence.get("completed_at"), "completed_at")
    if completed <= started:
        fail("completed_at must be after started_at")
    current = now or datetime.now(timezone.utc)
    if completed > current:
        fail("completed_at cannot be in the future")
    if (current - completed).total_seconds() > MAX_EVIDENCE_AGE_DAYS * 86400:
        fail("disaster-recovery evidence is stale")

    objectives = evidence.get("objectives")
    if not isinstance(objectives, dict):
        fail("objectives must be an object")
    if require_positive_number(objectives, "measured_rpo_minutes") > require_positive_number(objectives, "target_rpo_minutes"):
        fail("measured RPO exceeds target")
    if require_positive_number(objectives, "measured_rto_minutes") > require_positive_number(objectives, "target_rto_minutes"):
        fail("measured RTO exceeds target")

    for key in ("clean_environment", "independent_backup_source", "target_side_verification", "rollback_tested", "restore_tested", "corruption_rejected", "missing_backup_rejected", "runbook_followed", "audit_log_preserved"):
        require_bool(evidence, key)

    owners = evidence.get("owners")
    if not isinstance(owners, dict):
        fail("owners must be an object")
    owner_values = []
    for key in REQUIRED_OWNER_KEYS:
        value = owners.get(key)
        if not isinstance(value, str) or not value.strip():
            fail(f"owners.{key} is required")
        owner_values.append(value.strip())
    if len(set(owner_values)) != len(owner_values):
        fail("separation of duties requires distinct owners")

    scenarios = evidence.get("scenarios")
    if not isinstance(scenarios, list):
        fail("scenarios must be a list")
    seen: set[str] = set()
    for scenario in scenarios:
        if not isinstance(scenario, dict):
            fail("scenario entries must be objects")
        name = scenario.get("name")
        if not isinstance(name, str) or name not in REQUIRED_SCENARIOS:
            fail("unsupported disaster scenario")
        if name in seen:
            fail(f"duplicate disaster scenario: {name}")
        seen.add(name)
        require_bool(scenario, "executed")
        require_bool(scenario, "expected_failure_observed")
        require_bool(scenario, "recovery_verified")
        verify_scenario_evidence(evidence_path.parent, exercise_id, scenario)
    missing = REQUIRED_SCENARIOS - seen
    if missing:
        fail("missing required disaster scenarios: " + ",".join(sorted(missing)))
    if evidence.get("open_critical_findings") not in (0, 0.0):
        fail("open_critical_findings must be zero")

    return ["freshness", "rpo-rto", "restore", "rollback", "negative-drills", "separation-of-duties", "scenario-coverage", "evidence-artifact-binding", "source-workflow-binding", "production-deny"]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("evidence", type=Path)
    args = parser.parse_args()
    try:
        checks = validate(args.evidence)
    except ValueError as exc:
        print(f"DISASTER_RECOVERY_GATE=BLOCKED reason={exc}", file=sys.stderr)
        return 1
    print("DISASTER_RECOVERY_GATE=PASS checks=" + ",".join(checks))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
