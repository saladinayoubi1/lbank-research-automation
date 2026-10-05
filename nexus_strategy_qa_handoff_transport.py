"""Synchronize verified Strategy QA handoff evidence into durable coordinator state.

GitHub Actions artifacts are evidence transport only.  This module accepts only
a successful official runtime-requalification workflow artifact, verifies the
QA handoff cryptographically, proves its source is on trusted main ancestry,
and stores an immutable verified copy for Agent Manager definition materialization.
"""
from __future__ import annotations

import argparse
import io
import json
import os
import re
import stat
import urllib.request
import zipfile
from pathlib import Path
from typing import Any, Callable, Mapping

from agent_transport import _StripAuthorizationRedirectHandler, _api, _bounded_read
from nexus_strategy_review_qa_handoff import verify_handoff

WORKFLOW = "nexus_strategy_proposal_runtime_requalification.yml"
ARTIFACT_PREFIX = "nexus-strategy-proposal-runtime-requalification-"
MAX_ARCHIVE_BYTES = 8_000_000
MAX_UNCOMPRESSED_BYTES = 16_000_000
MAX_ENTRIES = 64
MAX_JSON_BYTES = 4_000_000
SHA40 = re.compile(r"^[0-9a-f]{40}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")


class StrategyQaTransportError(RuntimeError):
    pass


Api = Callable[[str, str, dict[str, Any] | None], Any]
Downloader = Callable[[int], bytes]


def _repo() -> str:
    value = os.environ.get("GITHUB_REPOSITORY", "")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", value):
        raise StrategyQaTransportError("trusted repository context unavailable")
    return value


def _download_artifact(artifact_id: int) -> bytes:
    if isinstance(artifact_id, bool) or not isinstance(artifact_id, int) or artifact_id < 1:
        raise StrategyQaTransportError("Strategy QA artifact id is invalid")
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if not token:
        raise StrategyQaTransportError("GitHub token missing")
    req = urllib.request.Request(
        f"https://api.github.com/repos/{_repo()}/actions/artifacts/{artifact_id}/zip",
        method="GET",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
    )
    opener = urllib.request.build_opener(_StripAuthorizationRedirectHandler())
    with opener.open(req, timeout=30) as response:
        return _bounded_read(response, MAX_ARCHIVE_BYTES, "Strategy QA handoff artifact")


def _regular_member(info: zipfile.ZipInfo) -> bool:
    mode = (info.external_attr >> 16) & 0xFFFF
    return not stat.S_ISLNK(mode) and not info.is_dir()


def _json_member(zf: zipfile.ZipFile, basename: str) -> dict[str, Any] | None:
    matches = [
        info for info in zf.infolist()
        if _regular_member(info) and Path(info.filename).name == basename
    ]
    if not matches:
        return None
    if len(matches) != 1:
        raise StrategyQaTransportError(f"artifact contains ambiguous {basename}")
    info = matches[0]
    if info.file_size > MAX_JSON_BYTES:
        raise StrategyQaTransportError(f"{basename} exceeds bounded size")
    with zf.open(info, "r") as handle:
        raw = _bounded_read(handle, MAX_JSON_BYTES, basename)
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise StrategyQaTransportError(f"{basename} is malformed") from exc
    if not isinstance(value, dict):
        raise StrategyQaTransportError(f"{basename} must be a JSON object")
    return value


def parse_artifact(blob: bytes) -> tuple[dict[str, Any], dict[str, Any]] | None:
    if not isinstance(blob, (bytes, bytearray)) or not blob or len(blob) > MAX_ARCHIVE_BYTES:
        raise StrategyQaTransportError("Strategy QA artifact archive is outside bounds")
    try:
        with zipfile.ZipFile(io.BytesIO(blob)) as zf:
            infos = zf.infolist()
            if not infos or len(infos) > MAX_ENTRIES:
                raise StrategyQaTransportError("Strategy QA artifact entry count is outside bounds")
            if sum(info.file_size for info in infos) > MAX_UNCOMPRESSED_BYTES:
                raise StrategyQaTransportError("Strategy QA artifact expands beyond bounds")
            handoff = _json_member(zf, "qa-handoff.json")
            verification = _json_member(zf, "qa-handoff-verification.json")
            no_work = _json_member(zf, "runtime-requalification-no-work.json")
    except zipfile.BadZipFile as exc:
        raise StrategyQaTransportError("Strategy QA artifact is not a valid ZIP") from exc

    if handoff is None and verification is None:
        if no_work is not None and no_work.get("status") == "NO_WORK":
            return None
        raise StrategyQaTransportError("official requalification artifact has no QA handoff or verified no-work evidence")
    if handoff is None or verification is None or no_work is not None:
        raise StrategyQaTransportError("Strategy QA artifact has an ambiguous handoff state")
    computed = verify_handoff(handoff)
    if computed.get("decision") != "pass" or verification != computed:
        raise StrategyQaTransportError("Strategy QA handoff verification rejected")
    return handoff, verification


def latest_verified_handoff(
    *,
    current_sha: str,
    api: Api = _api,
    downloader: Downloader = _download_artifact,
) -> tuple[dict[str, Any], dict[str, Any], int] | None:
    repo = _repo()
    runs = api(
        "GET",
        f"https://api.github.com/repos/{repo}/actions/workflows/{WORKFLOW}/runs?branch=main&per_page=30",
        None,
    )
    rows = runs.get("workflow_runs", []) if isinstance(runs, Mapping) else []
    if not isinstance(rows, list):
        raise StrategyQaTransportError("runtime-requalification workflow metadata is invalid")
    for run in rows:
        if (
            not isinstance(run, Mapping)
            or run.get("conclusion") != "success"
            or run.get("head_branch") != "main"
            or run.get("event") != "workflow_run"
            or isinstance(run.get("id"), bool)
            or not isinstance(run.get("id"), int)
        ):
            continue
        run_id = int(run["id"])
        artifacts = api(
            "GET",
            f"https://api.github.com/repos/{repo}/actions/runs/{run_id}/artifacts?per_page=100",
            None,
        )
        candidates = [
            item for item in (artifacts.get("artifacts", []) if isinstance(artifacts, Mapping) else [])
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
        if not candidates:
            continue
        if len(candidates) != 1:
            raise StrategyQaTransportError("runtime-requalification artifact identity is ambiguous")
        parsed = parse_artifact(downloader(int(candidates[0]["id"])))
        if parsed is None:
            return None
        handoff, verification = parsed
        source_sha = str(handoff.get("source_sha", ""))
        if not SHA40.fullmatch(source_sha):
            raise StrategyQaTransportError("Strategy QA handoff source identity is malformed")
        # First admission is exact-current-main only.  Once durably stored, a
        # later main commit may advance while the already-admitted task keeps
        # its immutable source and uses the separately verified source-pin path.
        if source_sha != current_sha:
            return None
        return handoff, verification, run_id
    return None


def _atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(dict(value), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def store_verified_handoff(
    store: Path,
    handoff: Mapping[str, Any],
    verification: Mapping[str, Any],
) -> Path:
    if store.is_symlink():
        raise StrategyQaTransportError("Strategy QA durable store cannot be a symlink")
    computed = verify_handoff(handoff)
    if computed.get("decision") != "pass" or dict(verification) != computed:
        raise StrategyQaTransportError("refused unverified Strategy QA handoff")
    digest_value = str(handoff.get("handoff_digest", ""))
    if not HEX64.fullmatch(digest_value):
        raise StrategyQaTransportError("Strategy QA handoff digest is invalid")
    target = store / digest_value
    if target.exists() and target.is_symlink():
        raise StrategyQaTransportError("Strategy QA handoff directory cannot be a symlink")
    handoff_path = target / "qa-handoff.json"
    verification_path = target / "qa-handoff-verification.json"
    if handoff_path.exists() or verification_path.exists():
        try:
            old_handoff = json.loads(handoff_path.read_text(encoding="utf-8"))
            old_verification = json.loads(verification_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise StrategyQaTransportError("stored Strategy QA handoff is unreadable") from exc
        if old_handoff != dict(handoff) or old_verification != dict(verification):
            raise StrategyQaTransportError("immutable Strategy QA handoff store collision")
        return target
    _atomic_json(handoff_path, handoff)
    _atomic_json(verification_path, verification)
    return target


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store", type=Path, default=Path("data/agent_coordination/strategy_qa_handoffs"))
    args = parser.parse_args()
    current_sha = os.environ.get("GITHUB_SHA", "").strip().lower()
    if os.environ.get("GITHUB_REF") != "refs/heads/main" or not SHA40.fullmatch(current_sha):
        raise StrategyQaTransportError("Strategy QA sync requires exact trusted main")
    result = latest_verified_handoff(current_sha=current_sha)
    if result is None:
        print(json.dumps({"status": "NO_CURRENT_QA_HANDOFF", "paper_only": True, "live": False}, sort_keys=True))
        return 0
    handoff, verification, run_id = result
    target = store_verified_handoff(args.store, handoff, verification)
    print(json.dumps({
        "status": "VERIFIED_QA_HANDOFF_STORED",
        "run_id": run_id,
        "handoff_digest": handoff["handoff_digest"],
        "task_count": handoff["task_count"],
        "store": str(target),
        "paper_only": True,
        "live": False,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
