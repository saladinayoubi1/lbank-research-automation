from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import urllib.parse
import zipfile
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts import nexus_snapshot_artifact as base  # noqa: E402
import nexus_multipair_runtime_requalification_snapshot as runtime_snapshot  # noqa: E402


MANIFEST_NAME = "snapshot-manifest.json"
INNER_ARCHIVE_NAME = runtime_snapshot.INNER_ARCHIVE_NAME
_SHA40 = re.compile(r"^[0-9a-f]{40}$")
_SHA64 = re.compile(r"^[0-9a-f]{64}$")


def _extract_outer(outer_zip: Path, work_root: Path) -> Path:
    with zipfile.ZipFile(outer_zip) as archive:
        members = archive.infolist()
        if len(members) != 1 or members[0].filename != INNER_ARCHIVE_NAME:
            raise RuntimeError("runtime snapshot artifact must contain exactly one deterministic inner archive")
        member = members[0]
        if (
            not base._zip_member_is_regular(member)
            or member.file_size <= 0
            or member.file_size > base.MAX_INNER_ARCHIVE_BYTES
        ):
            raise RuntimeError("runtime snapshot inner archive member is unsafe")
        target = work_root / INNER_ARCHIVE_NAME
        with archive.open(member) as source, target.open("wb") as output:
            shutil.copyfileobj(source, output, length=base.COPY_CHUNK_BYTES)
    return target


def _validate_manifest(
    destination: Path,
    *,
    source_sha: str,
    snapshot_digest: str,
    expected_as_of_ms: int,
    now_ms: int,
) -> dict[str, Any]:
    try:
        value = json.loads((destination / MANIFEST_NAME).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("runtime snapshot manifest is unavailable after extraction") from exc
    if not isinstance(value, dict):
        raise RuntimeError("runtime snapshot manifest must be an object")
    if (
        value.get("snapshot_digest") != snapshot_digest
        or value.get("as_of_ms") != expected_as_of_ms
        or value.get("history_limit") != runtime_snapshot.HISTORY_LIMIT
    ):
        raise RuntimeError("runtime snapshot identity contract mismatch")
    verification = runtime_snapshot.verify_fresh_runtime_snapshot(
        destination,
        value,
        source_sha=source_sha,
        now_ms=now_ms,
    )
    if verification.get("decision") != "pass":
        raise RuntimeError("runtime snapshot freshness or authority contract rejected after transport")
    return value


def restore_current_run_runtime_snapshot(
    *,
    repository: str,
    run_id: str,
    token: str,
    artifact_name: str,
    expected_sha256: str,
    expected_source_sha: str,
    expected_snapshot_digest: str,
    expected_as_of_ms: int,
    now_ms: int,
    destination: Path,
    work_root: Path,
) -> dict[str, Any]:
    expected_sha256 = expected_sha256.strip().lower()
    expected_source_sha = expected_source_sha.strip().lower()
    expected_snapshot_digest = expected_snapshot_digest.strip().lower()
    if (
        not _SHA64.fullmatch(expected_sha256)
        or not _SHA40.fullmatch(expected_source_sha)
        or not _SHA64.fullmatch(expected_snapshot_digest)
    ):
        raise RuntimeError("invalid runtime snapshot artifact identity digest")
    if (
        isinstance(expected_as_of_ms, bool)
        or not isinstance(expected_as_of_ms, int)
        or expected_as_of_ms <= 0
        or isinstance(now_ms, bool)
        or not isinstance(now_ms, int)
        or now_ms <= 0
    ):
        raise RuntimeError("runtime snapshot time identity is invalid")

    headers = base._headers(token)
    run = base._json_get(
        f"https://api.github.com/repos/{repository}/actions/runs/{run_id}",
        headers,
    )
    if (
        str(run.get("id")) != str(run_id)
        or run.get("head_sha") != expected_source_sha
        or run.get("head_branch") != "main"
        or run.get("event") not in {"push", "workflow_dispatch"}
    ):
        raise RuntimeError("current workflow run identity does not match expected main source")

    query = urllib.parse.urlencode({"name": artifact_name, "per_page": 100})
    payload = base._json_get(
        f"https://api.github.com/repos/{repository}/actions/runs/{run_id}/artifacts?{query}",
        headers,
    )
    artifacts = [
        row
        for row in payload.get("artifacts", [])
        if isinstance(row, dict)
        and row.get("name") == artifact_name
        and not row.get("expired", False)
    ]
    if len(artifacts) != 1:
        raise RuntimeError(
            f"expected exactly one current-run runtime snapshot artifact, got {len(artifacts)}"
        )
    artifact = artifacts[0]
    artifact_id = int(artifact.get("id") or 0)
    artifact_size = int(artifact.get("size_in_bytes") or 0)

    work = work_root.resolve()
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True, exist_ok=True)
    outer_zip = work / "artifact.zip"
    base._download(
        f"https://api.github.com/repos/{repository}/actions/artifacts/{artifact_id}/zip",
        headers,
        outer_zip,
        expected_size=artifact_size,
    )
    inner_zip = _extract_outer(outer_zip, work)
    actual_sha256 = base._sha256_file(inner_zip)
    if actual_sha256 != expected_sha256:
        raise RuntimeError("runtime snapshot deterministic archive SHA-256 mismatch")

    base._extract_inner(inner_zip, destination)
    manifest = _validate_manifest(
        destination.resolve(),
        source_sha=expected_source_sha,
        snapshot_digest=expected_snapshot_digest,
        expected_as_of_ms=expected_as_of_ms,
        now_ms=now_ms,
    )
    return {
        "artifact_id": artifact_id,
        "artifact_size": artifact_size,
        "archive_sha256": actual_sha256,
        "snapshot_digest": manifest["snapshot_digest"],
        "snapshot_as_of_ms": manifest["as_of_ms"],
        "cell_count": manifest["cell_count"],
        "history_limit": manifest["history_limit"],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--artifact-name", required=True)
    parser.add_argument("--expected-sha256", required=True)
    parser.add_argument("--expected-source-sha", required=True)
    parser.add_argument("--expected-snapshot-digest", required=True)
    parser.add_argument("--expected-as-of-ms", type=int, required=True)
    parser.add_argument("--now-ms", type=int, required=True)
    parser.add_argument("--destination", required=True)
    parser.add_argument("--work-root", required=True)
    parser.add_argument("--token-env", default="GH_TOKEN")
    args = parser.parse_args()
    token = os.environ.get(args.token_env, "")
    if not token:
        raise RuntimeError(f"missing token environment variable: {args.token_env}")
    result = restore_current_run_runtime_snapshot(
        repository=args.repository,
        run_id=args.run_id,
        token=token,
        artifact_name=args.artifact_name,
        expected_sha256=args.expected_sha256,
        expected_source_sha=args.expected_source_sha,
        expected_snapshot_digest=args.expected_snapshot_digest,
        expected_as_of_ms=args.expected_as_of_ms,
        now_ms=args.now_ms,
        destination=Path(args.destination),
        work_root=Path(args.work_root),
    )
    for key in (
        "artifact_id",
        "artifact_size",
        "archive_sha256",
        "snapshot_digest",
        "snapshot_as_of_ms",
        "cell_count",
        "history_limit",
    ):
        print(f"runtime_snapshot_artifact_{key}={result[key]}")
    print("runtime_snapshot_artifact_verification=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
