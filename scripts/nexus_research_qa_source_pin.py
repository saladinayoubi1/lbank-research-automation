"""Select an immutable original source for *independent Research QA only*.

The workflow must additionally prove the selected commit is a genuine
ancestor of the event's trusted main SHA before checking out its code.
Selection by a task payload alone is never authority to run another ref.
"""
from __future__ import annotations

import os
import re
from typing import Any

from nexus_research_missions import TASKS
from scripts.agent_task_executor import decode_payload

REPO = "saladinayoubi1/lbank-research-automation"
SHA40 = re.compile(r"[0-9a-f]{40}\Z")
SHA64 = re.compile(r"[0-9a-f]{64}\Z")


class ResearchQaPinError(ValueError):
    pass


def select_source(payload: dict[str, Any], *, repository: str, main_sha: str,
                  ref_name: str, default_branch: str, actor: str,
                  owner: str, input_lease: str, input_transport: str) -> dict[str, Any]:
    if (repository != REPO or ref_name != "main" or default_branch != "main"
            or not owner or not re.fullmatch(r"[A-Za-z0-9-]{1,39}", owner)
            or not actor or actor not in {owner, "github-actions[bot]"}
            or not SHA40.fullmatch(main_sha)):
        raise ResearchQaPinError("untrusted main Research QA source-pin context")
    if (payload.get("lease_id") != input_lease
            or payload.get("transport") != "github-cloud"
            or input_transport != "github-cloud"
            or payload.get("phase") not in (4, 7)):
        raise ResearchQaPinError("Research QA source pin requires exact authorized cloud task")
    is_qa = payload.get("task_id") in TASKS and payload.get("worker_id") == "qa-verifier-agent"
    is_strategy_qa = (
        isinstance(payload.get("task_id"), str)
        and payload.get("task_id", "").startswith("STRATEGY-QA-")
        and payload.get("worker_id") == "qa-verifier-agent"
    )
    if is_strategy_qa:
        strategy_task = payload.get("strategy_qa_task")
        if payload.get("phase") != 7 or not isinstance(strategy_task, dict):
            raise ResearchQaPinError("immutable Strategy QA source identity is incomplete")
        from nexus_strategy_independent_qa import (
            StrategyIndependentQaError,
            validate_task,
        )
        source = str(strategy_task.get("source_sha", ""))
        try:
            validate_task(strategy_task, source)
        except StrategyIndependentQaError as exc:
            raise ResearchQaPinError("immutable Strategy QA task binding is invalid") from exc
        if (
            not SHA40.fullmatch(source)
            or strategy_task.get("id") != payload.get("task_id")
            or strategy_task.get("required_verifier") != "qa-verifier-agent"
        ):
            raise ResearchQaPinError("immutable Strategy QA source identity is incomplete")
    elif is_qa:
        source = payload.get("research_producer_source_sha")
        receipt = payload.get("research_producer_receipt_digest")
        producer_lease = payload.get("research_producer_lease_id")
        if (payload.get("phase") != 7
                or not isinstance(source, str) or not SHA40.fullmatch(source)
                or not isinstance(receipt, str) or not SHA64.fullmatch(receipt)
                or not isinstance(producer_lease, str)
                or not re.fullmatch(r"[a-zA-Z0-9_-]{1,160}", producer_lease)):
            raise ResearchQaPinError("immutable Research QA producer identity is incomplete")
    else:
        source = main_sha
    independent_qa = is_qa or is_strategy_qa
    return {
        "execution_source_sha": source,
        "requested_ancestor_pin": bool(independent_qa and source != main_sha),
        "source_role": (
            "independent-strategy-qa" if is_strategy_qa
            else "independent-research-qa" if is_qa
            else "normal-cloud-task"
        ),
        "live_authority": False,
        "auto_demo_promotion": False,
    }


def main() -> None:
    import json
    from pathlib import Path

    encoded = os.environ.get("NEXUS_TASK_PAYLOAD_B64", "")
    if not encoded:
        raise ResearchQaPinError("source pin requires a bounded task payload")
    payload = decode_payload(encoded)
    result = select_source(
        payload,
        repository=os.environ.get("GITHUB_REPOSITORY", ""),
        main_sha=os.environ.get("GITHUB_SHA", ""),
        ref_name=os.environ.get("GITHUB_REF_NAME", ""),
        default_branch=os.environ.get("NEXUS_DEFAULT_BRANCH", ""),
        actor=os.environ.get("GITHUB_ACTOR", ""),
        owner=os.environ.get("GITHUB_REPOSITORY_OWNER", ""),
        input_lease=os.environ.get("NEXUS_DISPATCH_LEASE", ""),
        input_transport=os.environ.get("NEXUS_DISPATCH_TRANSPORT", ""),
    )
    output = os.environ.get("GITHUB_OUTPUT")
    if not output:
        raise ResearchQaPinError("GitHub output contract unavailable")
    with Path(output).open("a", encoding="utf-8") as handle:
        handle.write("execution_source_sha=" + result["execution_source_sha"] + "\n")
        handle.write("requested_ancestor_pin=" +
                     str(result["requested_ancestor_pin"]).lower() + "\n")
    print(result["execution_source_sha"])


if __name__ == "__main__":
    main()
