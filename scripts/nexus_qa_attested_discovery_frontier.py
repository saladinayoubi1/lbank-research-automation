"""Select the exact independently QA-approved prior Research Agent frontier.

Never advance an Agent mission from the latest standalone discovery artifact:
a standalone experiment can already have consumed the next causal mechanism.
Only the matching actual cloud producer, independent numeric QA, and durable
main-branch Agent Manager DONE receipt can authorize the next input bundle.
Read-only GitHub Actions artifacts are bounded *transport*, NOT a runtime DB.
"""
from __future__ import annotations

import argparse
from io import BytesIO
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Any
from urllib.parse import quote
import zipfile

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from nexus_composite_strategy_research import ARCHIVE_SHA256, digest, load_ledger, safe_write
from nexus_research_missions import FIRST, PREDECESSOR, attested_predecessor

REPO = "saladinayoubi1/lbank-research-automation"
COORDINATOR_WORKFLOW_PATH = ".github/workflows/fast-agent-coordinator.yml"
HEX40 = re.compile(r"^[0-9a-f]{40}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")
MAX_ZIP_BYTES = 2_000_000


class QaFrontierError(ValueError):
    pass


def api(endpoint: str, *, binary: bool = False) -> Any:
    if not os.environ.get("GH_TOKEN"):
        raise QaFrontierError("authorized actions-read GitHub token unavailable")
    response = subprocess.run(
        ["gh", "api", endpoint], capture_output=True, timeout=55, check=False,
    )
    if response.returncode or len(response.stdout) > MAX_ZIP_BYTES:
        raise QaFrontierError("GitHub research proof artifact lookup failed or exceeded bound")
    if binary:
        return response.stdout
    try:
        obj = json.loads(response.stdout)
    except ValueError as exc:
        raise QaFrontierError("GitHub research proof API response invalid") from exc
    if not isinstance(obj, dict):
        raise QaFrontierError("GitHub proof metadata is not an object")
    return obj


def archive_json(raw: bytes, expected: str) -> dict[str, Any]:
    if not isinstance(raw, bytes) or len(raw) > MAX_ZIP_BYTES:
        raise QaFrontierError("GitHub proof archive outside approved byte bound")
    try:
        with zipfile.ZipFile(BytesIO(raw)) as archive:
            names = [part.filename for part in archive.infolist()]
            if len(names) != len(set(names)) or expected not in names:
                raise QaFrontierError("required independent research proof absent or duplicated")
            info = archive.getinfo(expected)
            if info.is_dir() or info.file_size > MAX_ZIP_BYTES:
                raise QaFrontierError("research proof member is not bounded data")
            payload = json.loads(archive.read(info))
    except (OSError, zipfile.BadZipFile, UnicodeError, ValueError) as exc:
        if isinstance(exc, QaFrontierError):
            raise
        raise QaFrontierError("invalid independent research proof ZIP/JSON") from exc
    if not isinstance(payload, dict):
        raise QaFrontierError("independent research proof is not an object")
    return payload


def active_coordinator_workflow_id(repo: str) -> int:
    """Resolve the one active Coordinator workflow by exact path, not filename alias."""
    if repo != REPO:
        raise QaFrontierError("coordinator lookup repository is not authorized")
    matches: set[int] = set()
    for page in range(1, 6):
        data = api(f"repos/{repo}/actions/workflows?per_page=100&page={page}")
        workflows = data.get("workflows")
        if not isinstance(workflows, list) or len(workflows) > 100:
            raise QaFrontierError("untrusted bounded workflow index")
        for workflow in workflows:
            if not isinstance(workflow, dict):
                raise QaFrontierError("malformed workflow index entry")
            if workflow.get("path") != COORDINATOR_WORKFLOW_PATH:
                continue
            if workflow.get("state") != "active":
                continue
            workflow_id = workflow.get("id")
            if type(workflow_id) is not int or workflow_id < 1:
                raise QaFrontierError("active Coordinator workflow has invalid identity")
            matches.add(workflow_id)
        if len(workflows) < 100:
            break
    if len(matches) != 1:
        raise QaFrontierError("active Coordinator workflow is missing or ambiguous")
    return next(iter(matches))


def latest_coordinator(
    repo: str, *, required_task_id: str | None = None,
) -> tuple[int, dict[str, Any]]:
    """Find recent successful main Coordinator proofs without a global artifact scan.

    The repository-wide artifact index grows with unrelated triage workflows
    and can exceed hosted Actions API limits. Resolve the active workflow's
    immutable numeric identity first, because GitHub may retain historical
    workflow records for the same filename. Then inspect only that workflow's
    recent successful runs and exact same-run output.
    """
    workflow_id = active_coordinator_workflow_id(repo)
    data = api(
        f"repos/{repo}/actions/workflows/{workflow_id}/"
        "runs?branch=main&per_page=12"
    )
    runs = data.get("workflow_runs")
    if not isinstance(runs, list) or len(runs) > 12:
        raise QaFrontierError("untrusted bounded coordinator workflow run index")
    current_sha = os.environ.get("GITHUB_SHA", "")
    if current_sha and not HEX40.fullmatch(current_sha):
        raise QaFrontierError("current discovery source SHA is malformed")
    # Prefer an exact-current-source Coordinator proof over a later-finishing
    # stale-source run during main transitions. Creation time is only the
    # secondary ordering key; source identity is the primary trust boundary.
    ordered = sorted(
        runs,
        key=lambda row: (
            bool(current_sha and isinstance(row, dict)
                 and row.get("head_sha") == current_sha),
            str(row.get("created_at", "")) if isinstance(row, dict) else "",
        ),
        reverse=True,
    )
    for run in ordered:
        if not isinstance(run, dict):
            raise QaFrontierError("malformed coordinator workflow run")
        run_id = run.get("id")
        source = run.get("head_sha")
        if (
            type(run_id) is not int or run_id < 1
            or run.get("head_branch") != "main"
            or run.get("event") not in {"workflow_dispatch", "push", "schedule"}
            or run.get("status") != "completed"
            or run.get("conclusion") != "success"
            or not HEX40.fullmatch(str(source))
        ):
            continue
        if run.get("path") not in {None, COORDINATOR_WORKFLOW_PATH}:
            raise QaFrontierError("coordinator workflow source path changed")
        for key in ("repository", "head_repository"):
            value = run.get(key)
            if value is not None and (
                not isinstance(value, dict) or value.get("full_name") != repo
            ):
                raise QaFrontierError("untrusted coordinator workflow repository")
        artifacts = api(f"repos/{repo}/actions/runs/{run_id}/artifacts?per_page=30").get("artifacts")
        if not isinstance(artifacts, list) or len(artifacts) > 30:
            raise QaFrontierError("untrusted bounded coordinator run artifact index")
        exact = [item for item in artifacts
                 if isinstance(item, dict)
                 and item.get("name") == f"fast-agent-status-{run_id}"
                 and item.get("expired") is False]
        if len(exact) > 1:
            raise QaFrontierError("ambiguous exact Coordinator runtime proof")
        if not exact:
            continue
        artifact = exact[0]
        binding = artifact.get("workflow_run")
        if (
            type(artifact.get("id")) is not int or artifact["id"] < 1
            or type(artifact.get("size_in_bytes")) is not int
            or not 0 < artifact["size_in_bytes"] <= MAX_ZIP_BYTES
            or not isinstance(binding, dict)
            or binding.get("id") != run_id
            or binding.get("head_branch") != "main"
            or binding.get("head_sha") != source
        ):
            raise QaFrontierError("Coordinator proof metadata does not bind to its run")
        raw = api(f"repos/{repo}/actions/artifacts/{artifact['id']}/zip", binary=True)
        manager = archive_json(raw, "agent_manager_runtime.json")
        if required_task_id is not None:
            tasks = manager.get("tasks")
            if not isinstance(tasks, list):
                # A source-transition snapshot without a durable task ledger
                # cannot seed Research; continue to another bounded proof.
                continue
            matching = [
                task for task in tasks
                if isinstance(task, dict) and task.get("id") == required_task_id
            ]
            if len(matching) > 1:
                raise QaFrontierError("ambiguous predecessor Research mission in Coordinator proof")
            if not matching:
                # Older Coordinator schema may not yet know the newly appended
                # successor chain. It is proof transport, not authoritative
                # runtime state; only a snapshot containing the exact required
                # predecessor can be selected.
                continue
        return artifact["id"], manager
    raise QaFrontierError("no verified successful main Coordinator runtime proof available")


def exact_artifact_json(repo: str, name: str, sha: str, member: str) -> tuple[int, dict[str, Any]]:
    data = api(f"repos/{repo}/actions/artifacts?name={quote(name)}&per_page=100")
    items = data.get("artifacts", [])
    found = [x for x in items if isinstance(x, dict)
             and x.get("name") == name and x.get("expired") is False
             and (x.get("workflow_run") or {}).get("head_sha") == sha]
    if len(found) != 1:
        raise QaFrontierError("original QA or numerical producer proof is missing/ambiguous")
    artifact = found[0]
    if not isinstance(artifact.get("id"), int) or artifact["id"] <= 0:
        raise QaFrontierError("invalid exact producer or QA artifact identity")
    return artifact["id"], archive_json(
        api(f"repos/{repo}/actions/artifacts/{artifact['id']}/zip", binary=True), member
    )


def _independently_pinned_historical_qa(
    repo: str, task: dict[str, Any], source: str,
    producer_lease: str, producer_digest: str, qa_lease: str,
) -> tuple[int, dict[str, Any]]:
    """Allow ONLY the documented fifth incident's independently source-pinned QA.

    GitHub run head is the later trusted main event, NEVER presented as the
    original numerical source. Both the separate attestation and actual Git
    ancestry must bind the two; no unauthenticated SHA substitution.
    """
    from nexus_research_missions import FIFTH

    incident = task.get("research_qa_incident_recovery")
    if (task.get("id") != FIFTH or not isinstance(incident, dict)
            or incident.get("reason") != "verified_failed_source_epoch_new_independent_qa_only"
            or incident.get("original_producer_source_sha") != source
            or incident.get("original_producer_receipt_digest") != producer_digest
            or incident.get("original_producer_lease_id") != producer_lease
            or incident.get("new_qa_lease_id") != qa_lease
            or incident.get("independent_qa_complete") is not False
            or incident.get("automatic_demo_promotion") is not False
            or incident.get("live_enabled") is not False):
        raise QaFrontierError("unreviewed historical QA recovery cannot seed research")

    def one_artifact(name: str) -> dict[str, Any]:
        rows = api(f"repos/{repo}/actions/artifacts?name={quote(name)}&per_page=100").get("artifacts")
        if not isinstance(rows, list):
            raise QaFrontierError("historical QA artifact index is malformed")
        exact = [a for a in rows if isinstance(a, dict)
                 and a.get("name") == name and a.get("expired") is False]
        if len(exact) != 1:
            raise QaFrontierError("historical QA artifact absent or ambiguous")
        artifact = exact[0]
        if type(artifact.get("id")) is not int or artifact["id"] < 1:
            raise QaFrontierError("historical QA artifact has invalid identity")
        return artifact

    proof_art = one_artifact("nexus-agent-research-qa-" + qa_lease)
    bound = proof_art.get("workflow_run")
    if (not isinstance(bound, dict)
            or type(bound.get("id")) is not int or bound["id"] < 1
            or bound.get("head_branch") != "main"
            or not HEX40.fullmatch(str(bound.get("head_sha", "")))
            or bound["head_sha"] == source):
        raise QaFrontierError("historical QA must come from a distinct trusted main event")
    run_id, event_sha = bound["id"], bound["head_sha"]
    run = api(f"repos/{repo}/actions/runs/{run_id}")
    if (run.get("id") != run_id or run.get("head_sha") != event_sha
            or run.get("head_branch") != "main"
            or run.get("path") != ".github/workflows/nexus-runtime-worker.yml"
            or run.get("name") != "NEXUS Runtime Worker"
            or run.get("event") != "workflow_dispatch"
            or run.get("status") != "completed" or run.get("conclusion") != "success"
            or (run.get("actor") or {}).get("login") != "github-actions[bot]"
            or (run.get("repository") or {}).get("full_name") != repo
            or (run.get("head_repository") or {}).get("full_name") != repo):
        raise QaFrontierError("historical QA execution run is untrusted")
    comparison = api(f"repos/{repo}/compare/{quote(source)}...{quote(event_sha)}?per_page=1")
    if (comparison.get("status") != "ahead"
            or type(comparison.get("ahead_by")) is not int or comparison["ahead_by"] < 1
            or comparison.get("behind_by") != 0
            or (comparison.get("base_commit") or {}).get("sha") != source
            or (comparison.get("merge_base_commit") or {}).get("sha") != source):
        raise QaFrontierError("historical QA is not a proven original main ancestor")
    pin_art = one_artifact("nexus-agent-qa-source-pin-" + qa_lease)
    pin_bound = pin_art.get("workflow_run")
    if (not isinstance(pin_bound, dict) or pin_bound.get("id") != run_id
            or pin_bound.get("head_sha") != event_sha
            or pin_bound.get("head_branch") != "main"):
        raise QaFrontierError("original-source QA pin must belong to exact proof run")
    attestation = archive_json(
        api(f"repos/{repo}/actions/artifacts/{pin_art['id']}/zip", binary=True),
        "pinned-qa-attestation.json",
    )
    attestation_core = {k: v for k, v in attestation.items() if k != "attestation_sha256"}
    if (attestation.get("attestation_sha256") != digest(attestation_core)
            or attestation.get("schema") != "nexus.original-source-research-qa-ancestry.v1"
            or attestation.get("repository") != repo
            or attestation.get("run_id") != str(run_id)
            or attestation.get("trusted_main_event_sha") != event_sha
            or attestation.get("verified_main_ancestor_sha") != source
            or attestation.get("original_source_checkout_verified") is not True
            or attestation.get("independent_research_qa_only") is not True
            or attestation.get("auto_demo_promotion") is not False
            or attestation.get("live_enabled") is not False):
        raise QaFrontierError("independent source-pin attestation failed")
    proof = archive_json(
        api(f"repos/{repo}/actions/artifacts/{proof_art['id']}/zip", binary=True),
        "qa-evidence.json",
    )
    return proof_art["id"], proof


def verified_frontier(repo: str) -> dict[str, Any]:
    # The latest reviewed Mission schema names the NEXT dependent task.
    # Its predecessor is the only admissible QA-attested transport source.
    expected_id = PREDECESSOR[list(PREDECESSOR)[-1]]
    manager_artifact_id, manager = latest_coordinator(
        repo, required_task_id=expected_id,
    )
    tasks = manager.get("tasks")
    if not isinstance(tasks, list):
        raise QaFrontierError("coordinator does not contain a durable task ledger")
    matching = [task for task in tasks
                if isinstance(task, dict) and task.get("id") == expected_id]
    if len(matching) != 1:
        raise QaFrontierError("no unambiguous latest predecessor Research mission")
    task = matching[0]
    try:
        attested = attested_predecessor(task)
    except ValueError as exc:
        raise QaFrontierError("the predecessor did not complete real independent QA") from exc
    production = task["result_evidence"]
    checked = task["verification_evidence"]
    lease = task.get("research_producer_lease_id")
    qa_lease = task.get("lease_id")
    source = attested["research_predecessor_source_sha"]
    if not all(isinstance(x, str) and re.fullmatch(r"[0-9a-f-]{12,100}", x)
               for x in (lease, qa_lease)):
        raise QaFrontierError("original producer or independent QA lease is missing")
    producer_id, receipt = exact_artifact_json(
        repo, "nexus-agent-research-" + lease, source, "result/agent-receipt.json"
    )
    _, raw_ledger = exact_artifact_json(
        repo, "nexus-agent-research-" + lease, source, "result/novelty-ledger.json"
    )
    if task.get("research_qa_incident_recovery") is not None:
        qa_id, proof = _independently_pinned_historical_qa(
            repo, task, source, lease, production["receipt_digest"], qa_lease,
        )
    else:
        qa_id, proof = exact_artifact_json(
            repo, "nexus-agent-research-qa-" + qa_lease, source, "qa-evidence.json"
        )
    receipt_core = {k: v for k, v in receipt.items() if k != "receipt_digest"}
    qa_core = {k: v for k, v in proof.items() if k != "qa_digest"}
    ledger_core = {k: v for k, v in raw_ledger.items() if k != "ledger_digest"}
    if (
        receipt.get("receipt_digest") != digest(receipt_core)
        or receipt.get("receipt_digest") != production["receipt_digest"]
        or receipt.get("lease_id") != lease
        or receipt.get("source_sha") != source
        or receipt.get("ledger_digest") != production["ledger_digest"]
        or receipt.get("archive_sha256") != ARCHIVE_SHA256
        or proof.get("qa_digest") != digest(qa_core)
        or proof.get("qa_digest") != checked["qa_digest"]
        or proof.get("independent_replay_matches") is not True
        or proof.get("producer_receipt_digest") != production["receipt_digest"]
        or proof.get("lease_id") != lease
        or proof.get("source_sha") != source
        or proof.get("auto_demo_promotion") is not False
        or proof.get("live_enabled") is not False
        or raw_ledger.get("ledger_digest") != digest(ledger_core)
        or raw_ledger.get("archive_sha256") != ARCHIVE_SHA256
        or raw_ledger.get("ledger_digest") != production["ledger_digest"]
        or raw_ledger.get("research_only") is not True
        or raw_ledger.get("auto_demo_promotion") is not False
        or raw_ledger.get("live_enabled") is not False
    ):
        raise QaFrontierError("independent numerical QA and signed Research frontier disagree")
    return {
        "ledger": raw_ledger, "predecessor": expected_id,
        "manager_artifact_id": manager_artifact_id,
        "producer_artifact_id": producer_id, "qa_artifact_id": qa_id,
        "predecessor_ledger_digest": raw_ledger["ledger_digest"],
        "predecessor_qa_digest": proof["qa_digest"],
        "predecessor_receipt_digest": receipt["receipt_digest"],
        "research_only": True, "auto_demo_promotion": False, "live_enabled": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if (
        args.repository != REPO
        or os.environ.get("GITHUB_REPOSITORY") != REPO
        or os.environ.get("GITHUB_REF") != "refs/heads/main"
        or not HEX40.fullmatch(os.environ.get("GITHUB_SHA", ""))
    ):
        raise QaFrontierError("only authorized exact-main discovery can select the QA frontier")
    binding = verified_frontier(REPO)
    target = args.output
    if target.is_symlink():
        raise QaFrontierError("reviewed research frontier path must not be a symlink")
    safe_write(target, binding["ledger"])
    # Validate serialized bytes with the same source-bound worker ledger parser.
    assert load_ledger(target)["ledger_digest"] == binding["predecessor_ledger_digest"]
    print(json.dumps({key: value for key, value in binding.items() if key != "ledger"},
                     sort_keys=True))


if __name__ == "__main__":
    main()
