#!/usr/bin/env python3
"""Fail-closed validation for disaster-recovery exercise evidence.

This module validates supplied, offline evidence only. It does not create backups,
credentials, recovery infrastructure, production authorization, or a claim that
an organization is disaster-recovery ready.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

MAX_EVIDENCE_BYTES = 1_000_000
REQUIRED_SCENARIOS = {
    "primary-region-loss",
    "backup-corruption",
    "credential-loss",
    "dependency-outage",
}


def fail(message: str) -> None:
    raise ValueError(message)


def load_json(path: Path) -> Any:
    if not path.is_file():
        fail(f"missing evidence file: {path.name}")
    if path.stat().st_size > MAX_EVIDENCE_BYTES:
        fail("evidence file exceeds maximum size")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        fail(f"invalid JSON: {exc.msg}")


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
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        fail(f"{key} must be a valid UTC timestamp")
    return parsed.astimezone(timezone.utc)


def validate(evidence_path: Path, *, now: datetime | None = None) -> list[str]:
    evidence = load_json(evidence_path)
    if not isinstance(evidence, dict):
        fail("evidence root must be an object")

    if evidence.get("schema_version") != 1:
        fail("unsupported schema_version")
    if evidence.get("production_authorized") is not False:
        fail("production_authorized must be explicitly false")

    exercise_id = evidence.get("exercise_id")
    if not isinstance(exercise_id, str) or not exercise_id.strip():
        fail("exercise_id is required")

    started = parse_utc(evidence.get("started_at"), "started_at")
    completed = parse_utc(evidence.get("completed_at"), "completed_at")
    if completed <= started:
        fail("completed_at must be after started_at")
    current = now or datetime.now(timezone.utc)
    if completed > current:
        fail("completed_at cannot be in the future")

    max_age_days = require_positive_number(evidence, "max_evidence_age_days")
    if (current - completed).total_seconds() > max_age_days * 86400:
        fail("disaster-recovery evidence is stale")

    objectives = evidence.get("objectives")
    if not isinstance(objectives, dict):
        fail("objectives must be an object")
    target_rpo = require_positive_number(objectives, "target_rpo_minutes")
    target_rto = require_positive_number(objectives, "target_rto_minutes")
    measured_rpo = require_positive_number(objectives, "measured_rpo_minutes")
    measured_rto = require_positive_number(objectives, "measured_rto_minutes")
    if measured_rpo > target_rpo:
        fail("measured RPO exceeds target")
    if measured_rto > target_rto:
        fail("measured RTO exceeds target")

    require_bool(evidence, "clean_environment")
    require_bool(evidence, "independent_backup_source")
    require_bool(evidence, "target_side_verification")
    require_bool(evidence, "rollback_tested")
    require_bool(evidence, "restore_tested")
    require_bool(evidence, "corruption_rejected")
    require_bool(evidence, "missing_backup_rejected")
    require_bool(evidence, "runbook_followed")
    require_bool(evidence, "audit_log_preserved")

    owners = evidence.get("owners")
    if not isinstance(owners, dict):
        fail("owners must be an object")
    for key in ("incident_commander", "recovery_operator", "security_approver"):
        value = owners.get(key)
        if not isinstance(value, str) or not value.strip():
            fail(f"owners.{key} is required")
    if len(set(owners.values())) != len(owners.values()):
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
        if not isinstance(scenario.get("evidence_ref"), str) or not scenario["evidence_ref"].strip():
            fail("scenario evidence_ref is required")
    missing = REQUIRED_SCENARIOS - seen
    if missing:
        fail("missing required disaster scenarios: " + ",".join(sorted(missing)))

    if evidence.get("open_critical_findings") not in (0, 0.0):
        fail("open_critical_findings must be zero")

    return [
        "freshness",
        "rpo-rto",
        "restore",
        "rollback",
        "negative-drills",
        "separation-of-duties",
        "scenario-coverage",
        "production-deny",
    ]


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
