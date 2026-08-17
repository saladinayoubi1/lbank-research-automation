"""Repository workflow trust-boundary regression checks.

This module is deliberately outside the frozen Phase 3 Gate 4 control-plane tuple.
The frozen permission policy remains authoritative and unchanged; these checks provide
additional required-Test regression coverage for unsafe GitHub Actions patterns.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

UNTRUSTED_INPUT_IN_RUN = re.compile(r"\$\{\{\s*(?:github\.event\.inputs|inputs)\.", re.IGNORECASE)
SECRET_EXPRESSION = re.compile(r"\$\{\{[^}]*\bsecrets\.", re.IGNORECASE)


def _trigger_names(workflow: dict[str, Any]) -> set[str]:
    # PyYAML 1.1 may parse the unquoted key `on` as boolean True.
    value = workflow.get("on")
    if value is None and True in workflow:
        value = workflow[True]
    if isinstance(value, str):
        return {value}
    if isinstance(value, list):
        return {item for item in value if isinstance(item, str)}
    if isinstance(value, dict):
        return {str(key) for key in value}
    return set()


def _is_self_hosted(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() == "self-hosted"
    if isinstance(value, list):
        return any(isinstance(item, str) and item.strip().lower() == "self-hosted" for item in value)
    return False


def _compact_condition(value: Any) -> str:
    return " ".join(value.split()) if isinstance(value, str) else ""


def _condition_excludes_untrusted_pr(value: Any) -> bool:
    compact = _compact_condition(value)
    if not compact:
        return False
    explicitly_not_pr = (
        "github.event_name != 'pull_request'" in compact
        or 'github.event_name != "pull_request"' in compact
        or "github.event_name == 'workflow_dispatch'" in compact
        or 'github.event_name == "workflow_dispatch"' in compact
    )
    owner_same_repo = (
        "github.event.pull_request.head.repo.full_name == github.repository" in compact
        and "github.actor == github.repository_owner" in compact
    )
    return explicitly_not_pr or owner_same_repo


def _condition_pins_or_excludes_manual_dispatch(value: Any) -> bool:
    compact = _compact_condition(value)
    if not compact:
        return False
    excludes_dispatch = (
        "github.event_name != 'workflow_dispatch'" in compact
        or 'github.event_name != "workflow_dispatch"' in compact
        or "github.event_name == 'pull_request'" in compact
        or 'github.event_name == "pull_request"' in compact
        or "github.event_name == 'push'" in compact
        or 'github.event_name == "push"' in compact
        or "github.event_name == 'schedule'" in compact
        or 'github.event_name == "schedule"' in compact
    )
    trusted_ref = (
        "github.ref_name == github.event.repository.default_branch" in compact
        or "github.ref == 'refs/heads/main'" in compact
        or 'github.ref == "refs/heads/main"' in compact
    )
    return excludes_dispatch or trusted_ref


def _contains_secret_expression(value: Any) -> bool:
    if isinstance(value, str):
        return bool(SECRET_EXPRESSION.search(value))
    if isinstance(value, dict):
        return any(_contains_secret_expression(item) for item in value.values())
    if isinstance(value, list):
        return any(_contains_secret_expression(item) for item in value)
    return False


def validate_workflow_trust_boundaries(path: Path, workflow: dict[str, Any]) -> None:
    """Fail closed on the trust-boundary classes found during the post-Phase4 audit."""
    triggers = _trigger_names(workflow)
    pull_request_enabled = "pull_request" in triggers
    manual_enabled = "workflow_dispatch" in triggers
    for job_name, job in workflow["jobs"].items():
        if not isinstance(job, dict):
            raise ValueError(f"{path}: job {job_name} must be a mapping")
        self_hosted = _is_self_hosted(job.get("runs-on"))
        job_guard = _condition_excludes_untrusted_pr(job.get("if"))
        if pull_request_enabled and self_hosted and not job_guard:
            raise ValueError(
                f"{path}: self-hosted job {job_name} may execute pull_request code "
                "without an owner/same-repo or no-PR guard"
            )
        if manual_enabled and self_hosted and not _condition_pins_or_excludes_manual_dispatch(job.get("if")):
            raise ValueError(
                f"{path}: self-hosted job {job_name} may execute workflow_dispatch code "
                "from an arbitrary ref"
            )
        if pull_request_enabled and _contains_secret_expression(job.get("env")) and not job_guard:
            raise ValueError(f"{path}: job {job_name} exposes a secret to pull_request code")
        steps = job.get("steps", [])
        if not isinstance(steps, list):
            raise ValueError(f"{path}: job {job_name} steps must be a list")
        for index, step in enumerate(steps):
            if not isinstance(step, dict):
                raise ValueError(f"{path}: job {job_name} step {index} must be a mapping")
            run_text = step.get("run")
            if isinstance(run_text, str) and UNTRUSTED_INPUT_IN_RUN.search(run_text):
                raise ValueError(
                    f"{path}: job {job_name} step {index} interpolates workflow input "
                    "directly into run shell source"
                )
            step_guard = job_guard or _condition_excludes_untrusted_pr(step.get("if"))
            if (
                pull_request_enabled
                and isinstance(run_text, str)
                and _contains_secret_expression(step.get("env"))
                and not step_guard
            ):
                raise ValueError(
                    f"{path}: job {job_name} step {index} exposes a secret to pull_request run code"
                )
