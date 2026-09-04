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
import nexus_multipair_recent_archive_runtime_snapshot as recent  # noqa: E402


MANIFEST_NAME = "snapshot-manifest.json"
INNER_ARCHIVE_NAME = recent.INNER_ARCHIVE_NAME
_SHA40 = re.compile(r"^[0-9a-f]{40}$")
_SHA64 = re.compile(r"^[0-9a-f]{64}$")


def _extract_outer(outer_zip: Path, work_root: Path) -> Path:
    with zipfile.ZipFile(outer_zip) as archive:
        members = archive.infolist()
        if len(members) != 1 or members[0].filename != INNER_ARCHIVE_NAME:
            raise RuntimeError("recent archive runtime artifact must contain exactly one deterministic inner archive")
        member = members[0]
        if (
            not base._zip_member_is_regular(member)
            or member.file_size <= 0
            or member.file_size > base.MAX_INNER_ARCHIVE_BYTES
        ):
            raise RuntimeError("recent archive runtime inner archive member is unsafe")
        target = work_root / INNER_ARCHIVE_NAME
        with archive.open(member) as source, target.open("wb") as output:
            shutil.copyfileobj(source, output, length=base.COPY_CHUNK_BYTES)
    return target


def _validate_manifest(
    destination: Path,
    *,
    source_sha: str,
    snapshot_digest: str,
    expected_acquired_at_ms: int,
    expected_data_as_of_ms: int,
    now_ms: int,
) -> dict[str, Any]:
    try:
        value = json.loads((destination / MANIFEST_NAME).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("recent archive runtime snapshot manifest is unavailable after extraction") from exc
    if not isinstance(value, dict):
        raise RuntimeError("recent archive runtime snapshot manifest must be an object")
    if (
        value.get("schema_version") != recent.SCHEMA
        or value.get("snapshot_digest") != snapshot_digest
        or value.get("as_of_ms") != expected_acquired_at_ms
        or value.get("acquired_at_ms") != expected_acquired_at_ms
        or value.get("data_as_of_ms") != expected_data_as_of_ms
        or value.get("history_limit") != recent.HISTORY_LIMIT
        or value.get("data_origin") != recent.DATA_ORIGIN
        or value.get("runtime_requalification_recency_verified") is not True
        or value.get("live_freshness_claimed") is not False
    ):
        raise RuntimeError("recent archive runtime snapshot identity contract mismatch")
    verification = recent.verify_recent_archive_runtime_snapshot(
        destination,
        value,
        source_sha=source_sha,
        now_ms=now_ms,
    )
    if verification.get("decision") != "pass":
        raise RuntimeError("recent archive runtime snapshot recency or authority contract rejected after transport")
    return value


def restore_current_run_recent_archive_runtime_snapshot(
    *,
    repository: str,
    run_id: str,
    token: str,
    artifact_name: str,
    expected_sha256: str,
    expected_source_sha: str,
    expected_snapshot_digest: str,
    expected_acquired_at_ms: int,
    expected_data_as_of_ms: int,
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
        raise RuntimeError("invalid recent archive runtime artifact identity digest")
    for name, value in (
        ("expected_acquired_at_ms", expected_acquired_at_ms),
        ("expected_data_as_of_ms", expected_data_as_of_ms),
        ("now_ms", now_ms),
    ):
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise RuntimeError(f"recent archive runtime {name} is invalid")
    if expected_data_as_of_ms > expected_acquired_at_ms or expected_acquired_at_ms > now_ms:
        raise RuntimeError("recent archive runtime time ordering is invalid")

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
            f"expected exactly one current-run recent archive runtime snapshot artifact, got {len(artifacts)}"
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
        raise RuntimeError("recent archive runtime deterministic archive SHA-256 mismatch")

    base._extract_inner(inner_zip, destination)
    manifest = _validate_manifest(
        destination.resolve(),
        source_sha=expected_source_sha,
        snapshot_digest=expected_snapshot_digest,
        expected_acquired_at_ms=expected_acquired_at_ms,
        expected_data_as_of_ms=expected_data_as_of_ms,
        now_ms=now_ms,
    )
    return {
        "artifact_id": artifact_id,
        "artifact_size": artifact_size,
        "archive_sha256": actual_sha256,
        "snapshot_digest": manifest["snapshot_digest"],
        "snapshot_acquired_at_ms": manifest["acquired_at_ms"],
        "snapshot_data_as_of_ms": manifest["data_as_of_ms"],
        "snapshot_source_lag_ms": now_ms - int(manifest["data_as_of_ms"]),
        "latest_common_complete_date": manifest["latest_common_complete_date"],
        "cell_count": manifest["cell_count"],
        "history_limit": manifest["history_limit"],
        "live_freshness_claimed": manifest["live_freshness_claimed"],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--artifact-name", required=True)
    parser.add_argument("--expected-sha256", required=True)
    parser.add_argument("--expected-source-sha", required=True)
    parser.add_argument("--expected-snapshot-digest", required=True)
    parser.add_argument("--expected-acquired-at-ms", type=int, required=True)
    parser.add_argument("--expected-data-as-of-ms", type=int, required=True)
    parser.add_argument("--now-ms", type=int, required=True)
    parser.add_argument("--destination", required=True)
    parser.add_argument("--work-root", required=True)
    parser.add_argument("--token-env", default="GH_TOKEN")
    args = parser.parse_args()
    token = os.environ.get(args.token_env, "")
    if not token:
        raise RuntimeError(f"missing token environment variable: {args.token_env}")
    result = restore_current_run_recent_archive_runtime_snapshot(
        repository=args.repository,
        run_id=args.run_id,
        token=token,
        artifact_name=args.artifact_name,
        expected_sha256=args.expected_sha256,
        expected_source_sha=args.expected_source_sha,
        expected_snapshot_digest=args.expected_snapshot_digest,
        expected_acquired_at_ms=args.expected_acquired_at_ms,
        expected_data_as_of_ms=args.expected_data_as_of_ms,
        now_ms=args.now_ms,
        destination=Path(args.destination),
        work_root=Path(args.work_root),
    )
    for key in (
        "artifact_id",
        "artifact_size",
        "archive_sha256",
        "snapshot_digest",
        "snapshot_acquired_at_ms",
        "snapshot_data_as_of_ms",
        "snapshot_source_lag_ms",
        "latest_common_complete_date",
        "cell_count",
        "history_limit",
        "live_freshness_claimed",
    ):
        print(f"recent_archive_runtime_snapshot_artifact_{key}={result[key]}")
    print("recent_archive_runtime_snapshot_artifact_verification=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
