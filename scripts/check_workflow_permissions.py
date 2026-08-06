#!/usr/bin/env python3
"""Fail-closed GitHub Actions permission policy validation."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import yaml
from yaml.events import AliasEvent, NodeEvent

WORKFLOW_DIR = Path(".github/workflows")
POLICY_PATH = Path("security/workflow-permissions-policy-v1.json")
ALLOWED_LEVELS = {"read", "write", "none"}
ALLOWED_SCOPES = {
    "actions", "attestations", "checks", "contents", "deployments",
    "discussions", "id-token", "issues", "models", "packages", "pages",
    "pull-requests", "security-events", "statuses",
}


class UniqueKeySafeLoader(yaml.SafeLoader):
    pass


def construct_mapping(loader: UniqueKeySafeLoader, node: yaml.MappingNode, deep: bool = False) -> dict[Any, Any]:
    mapping: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in mapping:
            raise ValueError(f"duplicate YAML key: {key!r}")
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


UniqueKeySafeLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, construct_mapping)


def reject_duplicate_json_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate policy key: {key!r}")
        result[key] = value
    return result


def load_policy(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=reject_duplicate_json_keys)
    except (json.JSONDecodeError, ValueError) as exc:
        raise ValueError(f"unsafe or malformed policy JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("policy root must be a mapping")
    return data


def load_yaml(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    try:
        for event in yaml.parse(text, Loader=UniqueKeySafeLoader):
            if isinstance(event, AliasEvent):
                raise ValueError("YAML aliases are forbidden")
            if isinstance(event, NodeEvent) and event.anchor is not None:
                raise ValueError("YAML anchors are forbidden")
        data = yaml.load(text, Loader=UniqueKeySafeLoader)
    except (yaml.YAMLError, ValueError) as exc:
        raise ValueError(f"unsafe or malformed YAML: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("workflow root must be a mapping")
    if "jobs" not in data or not isinstance(data["jobs"], dict) or not data["jobs"]:
        raise ValueError("workflow jobs must be a non-empty mapping")
    if any(not isinstance(name, str) or not name for name in data["jobs"]):
        raise ValueError("workflow job names must be non-empty strings")
    return data


def normalize_permissions(value: Any, where: str) -> dict[str, str]:
    if isinstance(value, str):
        raise ValueError(f"{where}: scalar permissions such as {value!r} are forbidden")
    if not isinstance(value, dict) or not value:
        raise ValueError(f"{where}: permissions must be a non-empty explicit mapping")
    result: dict[str, str] = {}
    for scope, level in value.items():
        if not isinstance(scope, str) or not isinstance(level, str):
            raise ValueError(f"{where}: permission scopes and levels must be strings")
        if scope not in ALLOWED_SCOPES:
            raise ValueError(f"{where}: unknown permission scope {scope!r}")
        if level not in ALLOWED_LEVELS:
            raise ValueError(f"{where}: invalid level {level!r} for {scope}")
        result[scope] = level
    return result


def validate_policy(policy: Any) -> dict[str, Any]:
    if not isinstance(policy, dict) or policy.get("version") != 1:
        raise ValueError("policy must be an object with version 1")
    allowed_root = {"policy_name", "version", "workflows"}
    if not set(policy).issubset(allowed_root) or not {"version", "workflows"}.issubset(policy):
        raise ValueError("policy root contains missing or unexpected fields")
    if "policy_name" in policy and policy["policy_name"] != "ADR-0016-v1":
        raise ValueError("unsupported policy_name")
    workflows = policy.get("workflows")
    if not isinstance(workflows, dict) or not workflows:
        raise ValueError("policy workflows must be a non-empty mapping")
    return workflows


def inventory_rule(path: Path, workflow: dict[str, Any]) -> dict[str, Any]:
    jobs: dict[str, Any] = {}
    for name, job in workflow["jobs"].items():
        if not isinstance(job, dict):
            raise ValueError(f"{path}: job {name} must be a mapping")
        rule: dict[str, Any] = {"policy_version": 1}
        if "permissions" in job:
            rule["permissions"] = normalize_permissions(job["permissions"], f"{path}: job {name}")
        jobs[name] = rule
    return {
        "policy_version": 1,
        "workflow_permissions": normalize_permissions(workflow.get("permissions"), f"{path}: workflow"),
        "jobs": jobs,
    }


def validate_workflow(path: Path, workflow: dict[str, Any], rule: dict[str, Any]) -> None:
    if not isinstance(rule, dict) or rule.get("policy_version") != 1:
        raise ValueError(f"{path}: missing versioned workflow policy")
    allowed_rule_fields = {"policy_version", "workflow_permissions", "jobs", "write_justification"}
    if not set(rule).issubset(allowed_rule_fields):
        raise ValueError(f"{path}: workflow policy contains unexpected fields")
    allowed_workflow = rule.get("workflow_permissions")
    if not isinstance(allowed_workflow, dict):
        raise ValueError(f"{path}: workflow_permissions policy must be a mapping")
    actual_workflow = normalize_permissions(workflow.get("permissions"), f"{path}: workflow")
    allowed_workflow = normalize_permissions(allowed_workflow, f"{path}: workflow policy")
    if actual_workflow != allowed_workflow:
        raise ValueError(f"{path}: workflow permissions differ from policy")
    if any(level == "write" for level in actual_workflow.values()):
        justification = rule.get("write_justification")
        if not isinstance(justification, str) or not justification.strip():
            raise ValueError(f"{path}: workflow write scope lacks justification")
    jobs_policy = rule.get("jobs")
    jobs = workflow["jobs"]
    if not isinstance(jobs_policy, dict) or set(jobs) != set(jobs_policy):
        raise ValueError(f"{path}: job inventory differs from policy")
    for job_name, job in jobs.items():
        if not isinstance(job, dict):
            raise ValueError(f"{path}: job {job_name} must be a mapping")
        job_rule = jobs_policy[job_name]
        if not isinstance(job_rule, dict) or job_rule.get("policy_version") != 1:
            raise ValueError(f"{path}: job {job_name} lacks versioned policy")
        allowed_job_fields = {"policy_version", "permissions", "write_justification"}
        if not set(job_rule).issubset(allowed_job_fields):
            raise ValueError(f"{path}: job {job_name} policy contains unexpected fields")
        if "permissions" in job:
            actual_job = normalize_permissions(job["permissions"], f"{path}: job {job_name}")
            allowed_job = job_rule.get("permissions")
            if not isinstance(allowed_job, dict):
                raise ValueError(f"{path}: job {job_name} permissions differ from policy")
            allowed_job = normalize_permissions(allowed_job, f"{path}: job {job_name} policy")
            if actual_job != allowed_job:
                raise ValueError(f"{path}: job {job_name} permissions differ from policy")
            for scope, level in actual_job.items():
                if level == "write" and actual_workflow.get(scope, "none") != "write":
                    raise ValueError(f"{path}: job {job_name} widens {scope} to write")
                if level == "write":
                    justification = job_rule.get("write_justification")
                    if not isinstance(justification, str) or not justification.strip():
                        raise ValueError(f"{path}: job {job_name} write scope lacks justification")
        elif job_rule.get("permissions") not in (None, actual_workflow):
            raise ValueError(f"{path}: job {job_name} policy expects explicit permissions")


def run(workflow_dir: Path = WORKFLOW_DIR, policy_path: Path = POLICY_PATH) -> list[str]:
    rules = validate_policy(load_policy(policy_path))
    paths = sorted([*workflow_dir.glob("*.yml"), *workflow_dir.glob("*.yaml")])
    actual = {p.as_posix() for p in paths}
    expected = set(rules)
    if actual != expected:
        snapshot = {p.as_posix(): inventory_rule(p, load_yaml(p)) for p in paths}
        raise ValueError(
            "workflow inventory mismatch "
            f"missing_policy={sorted(actual - expected)} stale_policy={sorted(expected - actual)} "
            f"inventory_json={json.dumps(snapshot, sort_keys=True, separators=(',', ':'))}"
        )
    for path in paths:
        validate_workflow(path, load_yaml(path), rules[path.as_posix()])
    return sorted(actual)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workflow-dir", type=Path, default=WORKFLOW_DIR)
    parser.add_argument("--policy", type=Path, default=POLICY_PATH)
    args = parser.parse_args()
    try:
        checked = run(args.workflow_dir, args.policy)
    except (OSError, ValueError) as exc:
        print(f"WORKFLOW_PERMISSIONS_GATE=BLOCKED reason={exc}", file=sys.stderr)
        return 1
    print(f"WORKFLOW_PERMISSIONS_GATE=PASS workflows={len(checked)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
