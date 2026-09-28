"""Stage immutable, official Bybit Research Agent inputs for a bounded lease.

Called only inside the authorized NEXUS Runtime Worker; an ordinary Phase-4 or
Phase-7 test task causes no downloads. Separate QA mode independently downloads
the same semantically verified archive, but receives the producer's *exact*
prior ledger from the producer artifact instead of racing latest state.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

from nexus_composite_strategy_research import ARCHIVE_SHA256, load_ledger
from scripts.agent_task_executor import decode_payload
from scripts.select_nexus_bybit_replay_artifact import restore_matching_artifact, safe_extract

TASK_ID = "P7-RESEARCH-COMPOSITE-001"
REPO = "saladinayoubi1/lbank-research-automation"
ARTIFACT = "nexus-composite-novelty-state"
REPLAY_NAME = "NEXUS_BYBIT_replay_v2_2022-12-01_to_2026-07-31.zip"
DELIVERY_NAME = "NEXUS_BYBIT_replay_v2_delivery.json"
HEX40 = re.compile(r"^[0-9a-f]{40}$")


class ResearchPreparationError(ValueError):
    pass


def _gh_api(path: str) -> dict[str, Any]:
    if not os.environ.get("GH_TOKEN"):
        raise ResearchPreparationError("bounded read-only GitHub token unavailable")
    response = subprocess.run(
        ["gh", "api", f"repos/{REPO}/{path}"],
        capture_output=True, text=True, timeout=90, check=False,
    )
    if response.returncode:
        raise ResearchPreparationError("trusted GitHub metadata unavailable")
    obj = json.loads(response.stdout)
    if not isinstance(obj, dict):
        raise ResearchPreparationError("GitHub metadata must be an object")
    return obj


def _previous_ledger(path: Path) -> tuple[dict[str, Any], int]:
    candidates = _gh_api(f"actions/artifacts?name={ARTIFACT}&per_page=100").get("artifacts", [])
    if not isinstance(candidates, list):
        raise ResearchPreparationError("latest novelty artifacts are malformed")
    main = [
        a for a in candidates
        if isinstance(a, dict)
        and a.get("expired") is False
        and a.get("name") == ARTIFACT
        and isinstance(a.get("workflow_run"), dict)
        and a["workflow_run"].get("head_branch") == "main"
    ]
    if not main:
        raise ResearchPreparationError("no verified prior novelty frontier; refuse implicit restart")
    # Do not silently fall back if the newest main artifact is untrustworthy.
    latest = max(main, key=lambda a: (str(a.get("created_at", "")), int(a.get("id", 0))))
    run_id = latest["workflow_run"].get("id")
    if type(run_id) is not int or run_id <= 0:
        raise ResearchPreparationError("prior novelty run identity invalid")
    run = _gh_api(f"actions/runs/{run_id}")
    if (
        run.get("id") != run_id
        or run.get("name") != "NEXUS multi-timeframe strategy discovery"
        or run.get("conclusion") != "success"
        or run.get("status") != "completed"
        or run.get("head_branch") != "main"
        or run.get("repository", {}).get("full_name") != REPO
        or not HEX40.fullmatch(str(run.get("head_sha", "")))
    ):
        raise ResearchPreparationError("prior novelty producer lacks source-exact successful attestation")
    path.parent.mkdir(parents=True, exist_ok=True)
    with_shipped = path.parent / "prior-artifact"
    if with_shipped.exists():
        raise ResearchPreparationError("prior-artifact stage must be clean")
    response = subprocess.run(
        ["gh", "run", "download", str(run_id), "-R", REPO, "-n", ARTIFACT, "-D", str(with_shipped)],
        capture_output=True, text=True, timeout=180, check=False,
    )
    if response.returncode:
        raise ResearchPreparationError("prior novelty artifact download failed")
    original = with_shipped / "novelty-ledger.json"
    if original.is_symlink() or not original.is_file():
        raise ResearchPreparationError("prior novelty ledger missing or linked")
    ledger = load_ledger(original)
    if not ledger["config_fingerprints_evaluated"]:
        raise ResearchPreparationError("prior novelty ledger unexpectedly empty")
    shutil.copyfile(original, path)
    return ledger, run_id


def _exact_producer_proof(root: Path, payload: dict[str, Any]) -> dict[str, Any]:
    producer_lease = payload["research_producer_lease_id"]
    expected_digest = payload["research_producer_receipt_digest"]
    producer_source = payload["research_producer_source_sha"]
    if producer_source != os.environ["GITHUB_SHA"]:
        raise ResearchPreparationError("QA worker source SHA differs from producer")
    name = "nexus-agent-research-" + producer_lease
    artifacts = _gh_api(f"actions/artifacts?name={name}&per_page=100").get("artifacts", [])
    matches = [
        a for a in artifacts
        if isinstance(a, dict) and a.get("expired") is False
        and a.get("name") == name and isinstance(a.get("workflow_run"), dict)
        and a["workflow_run"].get("head_branch") == "main"
        and a["workflow_run"].get("head_sha") == producer_source
    ]
    if len(matches) != 1:
        raise ResearchPreparationError("producer proof missing or ambiguous for exact lease")
    run_id = matches[0]["workflow_run"].get("id")
    if type(run_id) is not int or run_id < 1:
        raise ResearchPreparationError("producer workflow identity invalid")
    run = _gh_api(f"actions/runs/{run_id}")
    if (
        run.get("id") != run_id
        or run.get("name") != "NEXUS Runtime Worker"
        or run.get("event") != "workflow_dispatch"
        or run.get("conclusion") != "success"
        or run.get("status") != "completed"
        or run.get("head_sha") != producer_source
        or run.get("head_branch") != "main"
        or run.get("repository", {}).get("full_name") != REPO
    ):
        raise ResearchPreparationError("producer run not source-exact or incomplete")
    location = root / "producer"
    proc = subprocess.run(
        ["gh", "run", "download", str(run_id), "-R", REPO, "-n", name, "-D", str(location)],
        capture_output=True, text=True, timeout=180, check=False,
    )
    if proc.returncode:
        raise ResearchPreparationError("independent QA cannot download exact producer artifact")
    receipt_file = location / "result" / "agent-receipt.json"
    prior_file = location / "result" / "previous-ledger.json"
    if receipt_file.is_symlink() or prior_file.is_symlink() or not receipt_file.is_file():
        raise ResearchPreparationError("producer receipt missing or linked")
    receipt = json.loads(receipt_file.read_text(encoding="utf-8"))
    if (
        receipt.get("schema") != "nexus.agent-composite-execution.v1"
        or receipt.get("receipt_digest") != expected_digest
        or receipt.get("source_sha") != producer_source
        or receipt.get("lease_id") != producer_lease
        or receipt.get("archive_sha256") != ARCHIVE_SHA256
        or receipt.get("independent_qa_complete") is not False
        or receipt.get("auto_demo_promotion") is not False
        or receipt.get("live_enabled") is not False
    ):
        raise ResearchPreparationError("QA producer proof identity or authority mismatch")
    old = load_ledger(prior_file)
    if old["ledger_digest"] != receipt.get("prior_ledger_digest"):
        raise ResearchPreparationError("QA producer's immutable previous ledger digest mismatch")
    return {
        "producer_lease_id": producer_lease,
        "producer_receipt_digest": expected_digest,
        "prior_ledger_digest": old["ledger_digest"],
        "producer_run_id": run_id,
    }


def prepare(mode: str, root: Path) -> dict[str, Any]:
    token = os.environ.get("NEXUS_TASK_PAYLOAD_B64", "")
    if not token:
        return {"research_task": False}
    payload = decode_payload(token)
    if payload["task_id"] != TASK_ID:
        return {"research_task": False}
    if (
        payload["phase"] != 7
        or payload["transport"] != "github-cloud"
        or payload["worker_id"] not in {"research-agent", "qa-verifier-agent"}
        or os.environ.get("GITHUB_REPOSITORY") != REPO
        or not HEX40.fullmatch(os.environ.get("GITHUB_SHA", ""))
    ):
        raise ResearchPreparationError("untrusted Research Agent task context")
    if mode == "auto":
        mode = "independent-qa" if payload["worker_id"] == "qa-verifier-agent" else "producer"
    if mode not in ("producer", "independent-qa"):
        raise ResearchPreparationError("unsupported preparation mode")
    if (
        (mode == "producer" and payload["worker_id"] != "research-agent")
        or (mode == "independent-qa" and payload["worker_id"] != "qa-verifier-agent")
    ):
        raise ResearchPreparationError("untrusted Research Agent role")
    if root.exists():
        raise ResearchPreparationError("refuse dirty or pre-existing research staging root")
    root.mkdir(parents=True)
    destination = root / "download"
    restored = restore_matching_artifact(
        repository=REPO, token=os.environ.get("GH_TOKEN", ""),
        output_dir=destination,
        expected_file_name=REPLAY_NAME,
        expected_semantic_sha256=ARCHIVE_SHA256,
        delivery_name=DELIVERY_NAME,
        prefix="bybit-full-history-final-",
    )
    # The selector checks the outer delivery, ZIP SHA and internal replay-v2
    # manifest, and safe_extract rejects path traversal and symlink members.
    safe_extract(Path(restored["replay_file"]), root / "archive")
    info: dict[str, Any] = {
        "research_task": True,
        "archive_sha256": ARCHIVE_SHA256,
        "source_sha": os.environ["GITHUB_SHA"],
        "lease_id": payload["lease_id"],
        "replay_artifact_id": restored["artifact_id"],
        "mode": mode,
        "auto_demo_promotion": False,
        "live_enabled": False,
    }
    if mode == "producer":
        ledger, run_id = _previous_ledger(root / "previous-ledger.json")
        info.update({"prior_ledger_digest": ledger["ledger_digest"], "prior_run_id": run_id})
    else:
        info.update(_exact_producer_proof(root, payload))
    from nexus_composite_strategy_research import safe_write
    safe_write(root / "preparation.json", info)
    return info


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("auto", "producer", "independent-qa"), default="auto")
    parser.add_argument("--root", type=Path, default=Path("build/agent-research"))
    args = parser.parse_args()
    info = prepare(args.mode, args.root)
    # Workflow step outputs are flags only; no tokens or private directories.
    if os.environ.get("GITHUB_OUTPUT"):
        with Path(os.environ["GITHUB_OUTPUT"]).open("a", encoding="utf-8") as handle:
            handle.write("research_task=" + str(info["research_task"]).lower() + "\n")
            handle.write("research_role=" + str(info.get("mode", "none")) + "\n")
    print(json.dumps(info, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
