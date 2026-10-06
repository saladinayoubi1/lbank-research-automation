"""Synchronize verified physical composite VAL-40 evidence into durable QA-41 tasks.

GitHub Actions artifacts are evidence transport only.  The latest successful
official physical composite requalification run is verified, bound to trusted
main ancestry, converted into the existing verifier-only QA task contract, and
stored immutably for Agent Manager definition materialization.

This module never dispatches QA, qualifies/registers/activates a strategy,
executes Paper, or grants Live authority.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import stat
import urllib.request
import zipfile
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from agent_transport import _StripAuthorizationRedirectHandler, _api, _bounded_read
from nexus_composite_runtime_independent_qa import build_task, validate_task
from nexus_composite_runtime_requalification import verify_requalification

WORKFLOW = "nexus_composite_runtime_requalification.yml"
ARTIFACT_PREFIX = "nexus-composite-runtime-requalification-"
MAX_ARCHIVE_BYTES = 8_000_000
MAX_UNCOMPRESSED_BYTES = 16_000_000
MAX_ENTRIES = 32
MAX_JSON_BYTES = 4_000_000
SHA40 = re.compile(r"^[0-9a-f]{40}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")


class CompositeRuntimeQaTransportError(RuntimeError):
    pass


Api = Callable[[str, str, dict[str, Any] | None], Any]
Downloader = Callable[[int], bytes]
Verifier = Callable[[Mapping[str, Any]], dict[str, Any]]
Builder = Callable[..., dict[str, Any]]
Validator = Callable[[Mapping[str, Any], str], dict[str, Any]]


def _repo() -> str:
    value = os.environ.get("GITHUB_REPOSITORY", "")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", value):
        raise CompositeRuntimeQaTransportError("trusted repository context unavailable")
    return value


def _download_artifact(artifact_id: int) -> bytes:
    if isinstance(artifact_id, bool) or not isinstance(artifact_id, int) or artifact_id < 1:
        raise CompositeRuntimeQaTransportError("composite runtime artifact id is invalid")
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if not token:
        raise CompositeRuntimeQaTransportError("GitHub token missing")
    request = urllib.request.Request(
        f"https://api.github.com/repos/{_repo()}/actions/artifacts/{artifact_id}/zip",
        method="GET",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
    )
    opener = urllib.request.build_opener(_StripAuthorizationRedirectHandler())
    with opener.open(request, timeout=30) as response:
        return _bounded_read(response, MAX_ARCHIVE_BYTES, "composite runtime QA artifact")


def _regular(info: zipfile.ZipInfo) -> bool:
    mode = (info.external_attr >> 16) & 0xFFFF
    return not info.is_dir() and not stat.S_ISLNK(mode) and not (info.flag_bits & 0x1)


def _json_member(zf: zipfile.ZipFile, basename: str) -> dict[str, Any]:
    matches = [info for info in zf.infolist() if _regular(info) and Path(info.filename).name == basename]
    if len(matches) != 1:
        raise CompositeRuntimeQaTransportError(f"artifact requires exactly one {basename}")
    info = matches[0]
    if info.file_size <= 0 or info.file_size > MAX_JSON_BYTES:
        raise CompositeRuntimeQaTransportError(f"{basename} exceeds bounded size")
    with zf.open(info, "r") as handle:
        raw = _bounded_read(handle, MAX_JSON_BYTES, basename)
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CompositeRuntimeQaTransportError(f"{basename} is malformed") from exc
    if not isinstance(value, dict):
        raise CompositeRuntimeQaTransportError(f"{basename} must be an object")
    return value


def parse_artifact(
    blob: bytes,
    *,
    verifier: Verifier = verify_requalification,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if not isinstance(blob, (bytes, bytearray)) or not blob or len(blob) > MAX_ARCHIVE_BYTES:
        raise CompositeRuntimeQaTransportError("composite runtime artifact archive is outside bounds")
    try:
        with zipfile.ZipFile(io.BytesIO(blob)) as zf:
            infos = zf.infolist()
            if not infos or len(infos) > MAX_ENTRIES:
                raise CompositeRuntimeQaTransportError("composite runtime artifact entry count is outside bounds")
            if sum(info.file_size for info in infos) > MAX_UNCOMPRESSED_BYTES:
                raise CompositeRuntimeQaTransportError("composite runtime artifact expands beyond bounds")
            producer = _json_member(zf, "runtime-requalification.json")
            verification = _json_member(zf, "verification.json")
    except zipfile.BadZipFile as exc:
        raise CompositeRuntimeQaTransportError("composite runtime artifact is not a valid ZIP") from exc

    computed = verifier(producer)
    if computed.get("decision") != "pass" or verification != computed:
        raise CompositeRuntimeQaTransportError("physical composite requalification verification rejected")
    return producer, verification


def _trusted_main_ancestor(source_sha: str, current_sha: str, *, api: Api = _api) -> bool:
    if not SHA40.fullmatch(source_sha) or not SHA40.fullmatch(current_sha):
        raise CompositeRuntimeQaTransportError("source ancestry identity is malformed")
    if source_sha == current_sha:
        return True
    response = api(
        "GET",
        f"https://api.github.com/repos/{_repo()}/compare/{source_sha}...{current_sha}",
        None,
    )
    if not isinstance(response, Mapping):
        raise CompositeRuntimeQaTransportError("source ancestry response is invalid")
    merge_base = response.get("merge_base_commit")
    return bool(
        response.get("status") == "ahead"
        and isinstance(response.get("ahead_by"), int)
        and not isinstance(response.get("ahead_by"), bool)
        and int(response["ahead_by"]) >= 1
        and response.get("behind_by") == 0
        and isinstance(merge_base, Mapping)
        and merge_base.get("sha") == source_sha
    )


def latest_verified_task(
    *,
    current_sha: str,
    api: Api = _api,
    downloader: Downloader = _download_artifact,
    verifier: Verifier = verify_requalification,
    builder: Builder = build_task,
    validator: Validator = validate_task,
) -> tuple[dict[str, Any], dict[str, Any]] | None:
    repo = _repo()
    response = api(
        "GET",
        f"https://api.github.com/repos/{repo}/actions/workflows/{WORKFLOW}/runs?branch=main&per_page=30",
        None,
    )
    runs = response.get("workflow_runs", []) if isinstance(response, Mapping) else []
    if not isinstance(runs, list):
        raise CompositeRuntimeQaTransportError("composite runtime workflow metadata is invalid")

    run = next(
        (
            row for row in runs
            if isinstance(row, Mapping)
            and row.get("conclusion") == "success"
            and row.get("head_branch") == "main"
            and row.get("event") == "workflow_dispatch"
            and isinstance(row.get("id"), int)
            and not isinstance(row.get("id"), bool)
            and SHA40.fullmatch(str(row.get("head_sha", "")))
        ),
        None,
    )
    if run is None:
        return None
    run_id = int(run["id"])
    artifacts = api(
        "GET",
        f"https://api.github.com/repos/{repo}/actions/runs/{run_id}/artifacts?per_page=100",
        None,
    )
    rows = artifacts.get("artifacts", []) if isinstance(artifacts, Mapping) else []
    matches = [
        item for item in rows
        if isinstance(item, Mapping)
        and item.get("name") == f"{ARTIFACT_PREFIX}{run_id}"
        and item.get("expired") is False
        and isinstance(item.get("id"), int)
        and not isinstance(item.get("id"), bool)
        and int(item["id"]) > 0
        and isinstance(item.get("size_in_bytes"), int)
        and not isinstance(item.get("size_in_bytes"), bool)
        and 0 < int(item["size_in_bytes"]) <= MAX_ARCHIVE_BYTES
    ]
    if len(matches) != 1:
        raise CompositeRuntimeQaTransportError("composite runtime artifact identity is missing or ambiguous")

    producer, verification = parse_artifact(downloader(int(matches[0]["id"])), verifier=verifier)
    source_sha = str(producer.get("requalification_source_sha", ""))
    if source_sha != str(run.get("head_sha", "")):
        raise CompositeRuntimeQaTransportError("producer source differs from physical workflow source")
    if not _trusted_main_ancestor(source_sha, current_sha, api=api):
        raise CompositeRuntimeQaTransportError("physical producer source is not trusted main ancestry")

    if producer.get("decision") != "QUALIFIED_FOR_REVIEW" or producer.get("qualified_for_review") is not True:
        return None
    task = builder(producer, verification, producer_workflow_run_id=run_id)
    validated = validator(task, source_sha)
    if validated != task:
        raise CompositeRuntimeQaTransportError("composite QA task validation is not canonical")
    transport = {
        "schema_version": "nexus.composite-runtime-qa-transport.v1",
        "producer_workflow_run_id": run_id,
        "artifact_id": int(matches[0]["id"]),
        "task_digest": task["task_digest"],
        "source_sha": task["source_sha"],
        "candidate_digest": task["candidate_digest"],
        "requalification_digest": task["requalification_digest"],
        "required_verifier": "qa-verifier-agent",
        "paper_only": True,
        "qualification_authority": False,
        "registry_mutation_authority": False,
        "runtime_activation_authority": False,
        "paper_execution_authority": False,
        "automatic_strategy_promotion": False,
        "live_trading_authority": False,
    }
    return task, transport


def _atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(dict(value), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temp, path)


def store_verified_task(store: Path, task: Mapping[str, Any], transport: Mapping[str, Any]) -> Path:
    if store.is_symlink():
        raise CompositeRuntimeQaTransportError("composite QA durable store cannot be a symlink")
    source_sha = str(task.get("source_sha", ""))
    validated = validate_task(task, source_sha)
    if validated != dict(task):
        raise CompositeRuntimeQaTransportError("refused non-canonical composite QA task")
    task_digest = str(task.get("task_digest", ""))
    if not HEX64.fullmatch(task_digest) or transport.get("task_digest") != task_digest:
        raise CompositeRuntimeQaTransportError("composite QA task digest binding is invalid")
    if (
        transport.get("schema_version") != "nexus.composite-runtime-qa-transport.v1"
        or transport.get("source_sha") != source_sha
        or transport.get("candidate_digest") != task.get("candidate_digest")
        or transport.get("requalification_digest") != task.get("requalification_digest")
        or transport.get("required_verifier") != "qa-verifier-agent"
        or transport.get("paper_only") is not True
        or transport.get("qualification_authority") is not False
        or transport.get("registry_mutation_authority") is not False
        or transport.get("runtime_activation_authority") is not False
        or transport.get("paper_execution_authority") is not False
        or transport.get("automatic_strategy_promotion") is not False
        or transport.get("live_trading_authority") is not False
    ):
        raise CompositeRuntimeQaTransportError("composite QA transport authority binding is invalid")
    target = store / task_digest
    if target.exists() and target.is_symlink():
        raise CompositeRuntimeQaTransportError("composite QA task directory cannot be a symlink")
    task_path = target / "qa-task.json"
    transport_path = target / "transport.json"
    if task_path.exists() or transport_path.exists():
        try:
            old_task = json.loads(task_path.read_text(encoding="utf-8"))
            old_transport = json.loads(transport_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise CompositeRuntimeQaTransportError("stored composite QA task is unreadable") from exc
        if old_task != dict(task) or old_transport != dict(transport):
            raise CompositeRuntimeQaTransportError("immutable composite QA task store collision")
        return target
    _atomic_json(task_path, task)
    _atomic_json(transport_path, transport)
    return target


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--store",
        type=Path,
        default=Path("data/agent_coordination/composite_runtime_qa_tasks"),
    )
    args = parser.parse_args()
    current_sha = os.environ.get("GITHUB_SHA", "").strip().lower()
    if os.environ.get("GITHUB_REF") != "refs/heads/main" or not SHA40.fullmatch(current_sha):
        raise CompositeRuntimeQaTransportError("composite QA sync requires exact trusted main")
    result = latest_verified_task(current_sha=current_sha)
    if result is None:
        print(json.dumps({"status": "NO_QUALIFIED_COMPOSITE_RUNTIME_QA_TASK", "paper_only": True, "live": False}, sort_keys=True))
        return 0
    task, transport = result
    target = store_verified_task(args.store, task, transport)
    print(json.dumps({
        "status": "VERIFIED_COMPOSITE_RUNTIME_QA_TASK_STORED",
        "task_id": task["id"],
        "task_digest": task["task_digest"],
        "producer_workflow_run_id": transport["producer_workflow_run_id"],
        "store": str(target),
        "paper_only": True,
        "live": False,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
