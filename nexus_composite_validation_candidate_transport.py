"""Synchronize independently QA-attested composite Research into durable VAL-40 evidence.

GitHub artifacts are evidence transport only.  The coordinator reads its own
persisted Agent Manager state, resolves the exact source-bound producer artifact
by the durable producer lease, verifies the artifact file hashes, rebuilds the
self-contained VAL-40 candidate, and stores only an immutable verified copy.

This module never selects/ranks strategies, performs fresh runtime validation,
qualifies/registers/activates a strategy, executes Paper, or grants Live authority.
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
from urllib.parse import quote

from agent_transport import _StripAuthorizationRedirectHandler, _api, _bounded_read
from nexus_composite_validation_candidate import build_candidate, digest, verify_candidate

ARTIFACT_PREFIX = "nexus-agent-research-"
TASK_PREFIX = "P7-RESEARCH-COMPOSITE-"
MIN_VAL40_TASK_SEQUENCE = 15
_TASK_ID = re.compile(r"^P7-RESEARCH-COMPOSITE-(\d{3})$")
MAX_ARCHIVE_BYTES = 8_000_000
MAX_UNCOMPRESSED_BYTES = 20_000_000
MAX_ENTRIES = 64
MAX_JSON_BYTES = 8_000_000
HEX64 = re.compile(r"^[0-9a-f]{64}$")
LEASE = re.compile(r"^[A-Za-z0-9_-]{1,160}$")


class CompositeVal40TransportError(RuntimeError):
    pass


Api = Callable[[str, str, dict[str, Any] | None], Any]
Downloader = Callable[[int], bytes]
Builder = Callable[[Mapping[str, Any], Mapping[str, Any], Mapping[str, Any]], dict[str, Any]]
Verifier = Callable[[Mapping[str, Any]], dict[str, Any]]


def _repo() -> str:
    value = os.environ.get("GITHUB_REPOSITORY", "")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", value):
        raise CompositeVal40TransportError("trusted repository context unavailable")
    return value


def _download_artifact(artifact_id: int) -> bytes:
    if isinstance(artifact_id, bool) or not isinstance(artifact_id, int) or artifact_id < 1:
        raise CompositeVal40TransportError("composite producer artifact id is invalid")
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if not token:
        raise CompositeVal40TransportError("GitHub token missing")
    request = urllib.request.Request(
        f"https://api.github.com/repos/{_repo()}/actions/artifacts/{artifact_id}/zip",
        method="GET",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
    )
    opener = urllib.request.build_opener(_StripAuthorizationRedirectHandler())
    with opener.open(request, timeout=30) as response:
        return _bounded_read(response, MAX_ARCHIVE_BYTES, "composite producer artifact")


def _regular(info: zipfile.ZipInfo) -> bool:
    mode = (info.external_attr >> 16) & 0xFFFF
    return not info.is_dir() and not stat.S_ISLNK(mode) and not (info.flag_bits & 0x1)


def _json_raw(zf: zipfile.ZipFile, basename: str) -> tuple[dict[str, Any], bytes]:
    matches = [
        info for info in zf.infolist()
        if _regular(info) and Path(info.filename).name == basename
    ]
    if len(matches) != 1:
        raise CompositeVal40TransportError(f"producer artifact requires exactly one {basename}")
    info = matches[0]
    if info.file_size <= 0 or info.file_size > MAX_JSON_BYTES:
        raise CompositeVal40TransportError(f"{basename} size is outside bounds")
    with zf.open(info, "r") as handle:
        raw = _bounded_read(handle, MAX_JSON_BYTES, basename)
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CompositeVal40TransportError(f"{basename} is malformed") from exc
    if not isinstance(value, dict):
        raise CompositeVal40TransportError(f"{basename} must be a JSON object")
    return value, raw


def _validate_ledger(value: Mapping[str, Any], expected_digest: str, label: str) -> None:
    core = dict(value)
    claimed = core.pop("ledger_digest", None)
    if (
        not HEX64.fullmatch(str(expected_digest))
        or claimed != expected_digest
        or digest(core) != claimed
        or value.get("research_only") is not True
        or value.get("auto_demo_promotion") is not False
        or value.get("live_enabled") is not False
    ):
        raise CompositeVal40TransportError(f"{label} ledger binding or authority is invalid")


def parse_producer_artifact(blob: bytes) -> tuple[dict[str, Any], dict[str, Any]]:
    if not isinstance(blob, (bytes, bytearray)) or not blob or len(blob) > MAX_ARCHIVE_BYTES:
        raise CompositeVal40TransportError("producer artifact archive is outside bounds")
    try:
        with zipfile.ZipFile(io.BytesIO(blob)) as zf:
            infos = zf.infolist()
            if not infos or len(infos) > MAX_ENTRIES:
                raise CompositeVal40TransportError("producer artifact entry count is outside bounds")
            if sum(info.file_size for info in infos) > MAX_UNCOMPRESSED_BYTES:
                raise CompositeVal40TransportError("producer artifact expands beyond bounds")
            receipt, _receipt_raw = _json_raw(zf, "agent-receipt.json")
            report, report_raw = _json_raw(zf, "research-report.json")
            ledger, ledger_raw = _json_raw(zf, "novelty-ledger.json")
            prior, prior_raw = _json_raw(zf, "previous-ledger.json")
    except zipfile.BadZipFile as exc:
        raise CompositeVal40TransportError("producer artifact is not a valid ZIP") from exc

    for field in ("report_file_sha256", "ledger_file_sha256", "prior_ledger_file_sha256"):
        if not HEX64.fullmatch(str(receipt.get(field, ""))):
            raise CompositeVal40TransportError("producer receipt file hash is invalid")
    if hashlib.sha256(report_raw).hexdigest() != receipt["report_file_sha256"]:
        raise CompositeVal40TransportError("research report file hash mismatch")
    if hashlib.sha256(ledger_raw).hexdigest() != receipt["ledger_file_sha256"]:
        raise CompositeVal40TransportError("novelty ledger file hash mismatch")
    if hashlib.sha256(prior_raw).hexdigest() != receipt["prior_ledger_file_sha256"]:
        raise CompositeVal40TransportError("previous ledger file hash mismatch")
    _validate_ledger(ledger, str(receipt.get("ledger_digest", "")), "current")
    _validate_ledger(prior, str(receipt.get("prior_ledger_digest", "")), "previous")
    return receipt, report


def _artifact_id_for_lease(lease_id: str, *, api: Api = _api) -> int | None:
    if not LEASE.fullmatch(str(lease_id)):
        raise CompositeVal40TransportError("producer lease identity is invalid")
    name = ARTIFACT_PREFIX + lease_id
    response = api(
        "GET",
        f"https://api.github.com/repos/{_repo()}/actions/artifacts?name={quote(name)}&per_page=100",
        None,
    )
    rows = response.get("artifacts", []) if isinstance(response, Mapping) else []
    if not isinstance(rows, list):
        raise CompositeVal40TransportError("producer artifact metadata is invalid")
    matches = [
        row for row in rows
        if isinstance(row, Mapping)
        and row.get("name") == name
        and row.get("expired") is False
        and isinstance(row.get("id"), int)
        and not isinstance(row.get("id"), bool)
        and int(row["id"]) > 0
        and isinstance(row.get("size_in_bytes"), int)
        and not isinstance(row.get("size_in_bytes"), bool)
        and 0 < int(row["size_in_bytes"]) <= MAX_ARCHIVE_BYTES
    ]
    if not matches:
        return None
    if len(matches) != 1:
        raise CompositeVal40TransportError("producer artifact identity is ambiguous")
    return int(matches[0]["id"])


def _atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(dict(value), indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def store_candidate(
    store: Path,
    candidate: Mapping[str, Any],
    verification: Mapping[str, Any],
    *,
    artifact_id: int,
) -> Path:
    if store.is_symlink():
        raise CompositeVal40TransportError("composite VAL-40 store cannot be a symlink")
    computed = verify_candidate(candidate)
    if computed.get("decision") != "pass" or dict(verification) != computed:
        raise CompositeVal40TransportError("refused unverified composite VAL-40 candidate")
    candidate_digest = str(candidate.get("candidate_digest", ""))
    if not HEX64.fullmatch(candidate_digest):
        raise CompositeVal40TransportError("candidate digest is invalid")
    target = store / candidate_digest
    if target.exists() and target.is_symlink():
        raise CompositeVal40TransportError("candidate directory cannot be a symlink")
    candidate_path = target / "candidate.json"
    verification_path = target / "verification.json"
    transport_path = target / "transport.json"
    transport = {
        "schema_version": "nexus.composite-validation-candidate-transport.v1",
        "artifact_id": artifact_id,
        "research_task_id": candidate.get("research_task_id"),
        "producer_lease_id": candidate.get("producer_lease_id"),
        "candidate_digest": candidate_digest,
        "decision": candidate.get("decision"),
        "eligible_for_fresh_runtime_requalification":
            candidate.get("eligible_for_fresh_runtime_requalification"),
        "paper_only": True,
        "qualification_authority": False,
        "registry_mutation_authority": False,
        "paper_execution_authority": False,
        "live_trading_authority": False,
    }
    if candidate_path.exists() or verification_path.exists() or transport_path.exists():
        try:
            old_candidate = json.loads(candidate_path.read_text(encoding="utf-8"))
            old_verification = json.loads(verification_path.read_text(encoding="utf-8"))
            old_transport = json.loads(transport_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise CompositeVal40TransportError("stored candidate evidence is unreadable") from exc
        if (
            old_candidate != dict(candidate)
            or old_verification != dict(verification)
            or old_transport != transport
        ):
            raise CompositeVal40TransportError("immutable candidate store collision")
        return target
    _atomic_json(candidate_path, candidate)
    _atomic_json(verification_path, verification)
    _atomic_json(transport_path, transport)
    return target


def _load_runtime(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CompositeVal40TransportError("Agent Manager runtime is unavailable") from exc
    if not isinstance(value, dict) or not isinstance(value.get("tasks"), list):
        raise CompositeVal40TransportError("Agent Manager runtime schema is invalid")
    return value


def sync_verified_candidates(
    runtime: Mapping[str, Any],
    store: Path,
    *,
    api: Api = _api,
    downloader: Downloader = _download_artifact,
    builder: Builder = build_candidate,
    verifier: Verifier = verify_candidate,
) -> dict[str, Any]:
    rows = []
    for task in runtime.get("tasks", []):
        if not isinstance(task, Mapping):
            continue
        task_id = str(task.get("id", ""))
        qa = task.get("verification_evidence")
        production = task.get("result_evidence")
        match = _TASK_ID.fullmatch(task_id)
        if (
            match is None
            or task.get("status") != "DONE"
            or task.get("producer") != "research-agent"
            or task.get("verifier") != "qa-verifier-agent"
            or not isinstance(qa, Mapping)
            or qa.get("independent_qa_complete") is not True
            or qa.get("qualification_authority") is not False
            or qa.get("auto_demo_promotion") is not False
            or qa.get("live_enabled") is not False
            or not isinstance(production, Mapping)
            or production.get("independent_qa_complete") is not False
            or production.get("qualification_authority") is not False
            or production.get("auto_demo_promotion") is not False
            or production.get("live_enabled") is not False
        ):
            continue
        sequence = int(match.group(1))
        if sequence < MIN_VAL40_TASK_SEQUENCE:
            rows.append({
                "task_id": task_id,
                "status": "LEGACY_PRE_VAL40_CONTRACT",
                "eligible": False,
                "paper_only": True,
                "live": False,
            })
            continue

        lease_id = str(task.get("research_producer_lease_id", ""))
        artifact_id = _artifact_id_for_lease(lease_id, api=api)
        if artifact_id is None:
            rows.append({
                "task_id": task_id,
                "status": "EVIDENCE_UNAVAILABLE",
                "producer_lease_id": lease_id,
                "paper_only": True,
                "live": False,
            })
            continue
        receipt, report = parse_producer_artifact(downloader(artifact_id))
        candidate = builder(task, receipt, report)
        verification = verifier(candidate)
        if verification.get("decision") != "pass":
            raise CompositeVal40TransportError("composite VAL-40 candidate verification rejected")
        target = store_candidate(store, candidate, verification, artifact_id=artifact_id)
        rows.append({
            "task_id": task_id,
            "status": "STORED",
            "decision": candidate["decision"],
            "eligible": candidate["eligible_for_fresh_runtime_requalification"],
            "candidate_digest": candidate["candidate_digest"],
            "store": str(target),
            "paper_only": True,
            "live": False,
        })
    return {
        "schema_version": "nexus.composite-validation-candidate-sync.v1",
        "processed": len(rows),
        "stored": sum(row["status"] == "STORED" for row in rows),
        "legacy_skipped": sum(
            row["status"] == "LEGACY_PRE_VAL40_CONTRACT" for row in rows
        ),
        "eligible": sum(row.get("eligible") is True for row in rows),
        "rows": rows,
        "qualification_authority": False,
        "registry_mutation_authority": False,
        "paper_execution_authority": False,
        "automatic_strategy_promotion": False,
        "live_trading_authority": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--runtime",
        type=Path,
        default=Path("data/agent_coordination/agent_manager_runtime.json"),
    )
    parser.add_argument(
        "--store",
        type=Path,
        default=Path("data/agent_coordination/composite_val40_candidates"),
    )
    args = parser.parse_args()
    current_sha = os.environ.get("GITHUB_SHA", "").strip().lower()
    if (
        os.environ.get("GITHUB_REF") != "refs/heads/main"
        or not re.fullmatch(r"[0-9a-f]{40}", current_sha)
    ):
        raise CompositeVal40TransportError("composite VAL-40 sync requires exact trusted main")
    result = sync_verified_candidates(_load_runtime(args.runtime), args.store)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
