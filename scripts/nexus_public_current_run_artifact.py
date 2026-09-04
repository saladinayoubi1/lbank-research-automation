from __future__ import annotations

import argparse
import json
import re
import shutil
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path
from typing import Any

from scripts import nexus_runtime_wheelhouse as wheelhouse
from scripts import nexus_snapshot_artifact as historical_artifact

API_VERSION = "2022-11-28"
_SHA40 = re.compile(r"^[0-9a-f]{40}$")
_SHA64 = re.compile(r"^[0-9a-f]{64}$")


def _headers() -> dict[str, str]:
    return {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": API_VERSION,
        "User-Agent": "nexus-public-current-run-artifact",
    }


def _json_get(url: str) -> dict[str, Any]:
    with urllib.request.urlopen(urllib.request.Request(url, headers=_headers()), timeout=60) as response:
        value = json.load(response)
    if not isinstance(value, dict):
        raise RuntimeError("GitHub public API response is not an object")
    return value


def _require_public_repository(repository: str) -> None:
    value = _json_get(f"https://api.github.com/repos/{repository}")
    if value.get("full_name") != repository or value.get("private") is not False:
        raise RuntimeError("anonymous artifact transport is allowed only for the exact public repository")


def _artifact(repository: str, run_id: str, artifact_name: str, source_sha: str) -> dict[str, Any]:
    _require_public_repository(repository)
    run = _json_get(f"https://api.github.com/repos/{repository}/actions/runs/{run_id}")
    if (
        str(run.get("id")) != str(run_id)
        or run.get("head_sha") != source_sha
        or run.get("head_branch") != "main"
        or run.get("event") not in {"push", "workflow_dispatch"}
    ):
        raise RuntimeError("public artifact run identity does not match exact main source")
    query = urllib.parse.urlencode({"name": artifact_name, "per_page": 100})
    payload = _json_get(
        f"https://api.github.com/repos/{repository}/actions/runs/{run_id}/artifacts?{query}"
    )
    matches = [
        row
        for row in payload.get("artifacts", [])
        if isinstance(row, dict)
        and row.get("name") == artifact_name
        and row.get("expired") is False
        and (row.get("workflow_run") or {}).get("head_sha") == source_sha
    ]
    if len(matches) != 1:
        raise RuntimeError(f"expected exactly one current-run public artifact, got {len(matches)}")
    artifact = matches[0]
    if int(artifact.get("id") or 0) <= 0 or int(artifact.get("size_in_bytes") or 0) <= 0:
        raise RuntimeError("public artifact metadata is invalid")
    return artifact


def _download_outer(repository: str, artifact: dict[str, Any], output: Path) -> None:
    wheelhouse._download_with_redirect_boundary(
        f"https://api.github.com/repos/{repository}/actions/artifacts/{int(artifact['id'])}/zip",
        _headers(),
        output,
        expected_size=int(artifact["size_in_bytes"]),
    )


def _extract_exact_outer(outer: Path, root: Path, expected_names: set[str]) -> dict[str, Path]:
    shutil.rmtree(root, ignore_errors=True)
    root.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(outer) as archive:
        members = archive.infolist()
        names = [member.filename for member in members]
        if len(names) != len(set(names)) or set(names) != expected_names:
            raise RuntimeError("public artifact outer surface mismatch")
        for member in members:
            if member.is_dir() or Path(member.filename).name != member.filename:
                raise RuntimeError("public artifact outer member is unsafe")
            target = root / member.filename
            with archive.open(member) as source, target.open("wb") as destination:
                shutil.copyfileobj(source, destination, length=wheelhouse.COPY_CHUNK_BYTES)
    return {name: root / name for name in expected_names}


def _read_digest(path: Path, expected: str) -> None:
    try:
        value = path.read_text(encoding="ascii").strip().lower()
    except (OSError, UnicodeError) as exc:
        raise RuntimeError("artifact digest sidecar is unreadable") from exc
    if value != expected:
        raise RuntimeError("artifact digest sidecar mismatch")


def restore_wheelhouse(
    *, repository: str, run_id: str, artifact_name: str, source_sha: str,
    expected_sha256: str, repository_lock: Path, destination: Path, work_root: Path,
) -> dict[str, Any]:
    artifact = _artifact(repository, run_id, artifact_name, source_sha)
    work = work_root.resolve()
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True, exist_ok=True)
    outer = work / "artifact.zip"
    _download_outer(repository, artifact, outer)
    inner_name = "nexus-paper-runtime-wheelhouse.zip"
    files = _extract_exact_outer(outer, work / "outer", {inner_name})
    inner = files[inner_name]
    actual = wheelhouse.sha256_file(inner)
    if actual != expected_sha256:
        raise RuntimeError("public wheelhouse deterministic archive SHA-256 mismatch")
    shutil.rmtree(destination, ignore_errors=True)
    destination.mkdir(parents=True, exist_ok=True)
    wheelhouse.safe_extract_flat_archive(inner, destination)
    if (destination / "requirements.lock").read_bytes() != repository_lock.read_bytes():
        raise RuntimeError("public wheelhouse requirements.lock mismatch")
    wheels = sorted(destination.glob("*.whl"))
    if not wheels:
        raise RuntimeError("public wheelhouse contains no wheels")
    return {"artifact_id": int(artifact["id"]), "archive_sha256": actual, "wheel_count": len(wheels)}


def restore_historical(
    *, repository: str, run_id: str, artifact_name: str, source_sha: str,
    expected_sha256: str, expected_snapshot_digest: str, destination: Path, work_root: Path,
) -> dict[str, Any]:
    import nexus_multipair_archive_snapshot as historical

    artifact = _artifact(repository, run_id, artifact_name, source_sha)
    work = work_root.resolve()
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True, exist_ok=True)
    outer = work / "artifact.zip"
    _download_outer(repository, artifact, outer)
    inner_name = historical_artifact.INNER_ARCHIVE_NAME
    sidecar_name = "nexus-multipair-archive-snapshot.sha256"
    files = _extract_exact_outer(outer, work / "outer", {inner_name, sidecar_name})
    _read_digest(files[sidecar_name], expected_sha256)
    actual = historical_artifact._sha256_file(files[inner_name])
    if actual != expected_sha256:
        raise RuntimeError("historical public artifact SHA-256 mismatch")
    historical_artifact._extract_inner(files[inner_name], destination)
    manifest = json.loads((destination / historical_artifact.MANIFEST_NAME).read_text(encoding="utf-8"))
    historical_artifact._validate_manifest(destination.resolve(), source_sha=source_sha, snapshot_digest=expected_snapshot_digest)
    verification = historical.verify_snapshot(destination, manifest)
    if verification.get("decision") != "pass":
        raise RuntimeError("historical snapshot verifier rejected public artifact")
    return {"artifact_id": int(artifact["id"]), "archive_sha256": actual, "snapshot_digest": manifest["snapshot_digest"]}


def restore_recent(
    *, repository: str, run_id: str, artifact_name: str, source_sha: str,
    expected_sha256: str, expected_snapshot_digest: str, expected_acquired_at_ms: int,
    expected_data_as_of_ms: int, now_ms: int, destination: Path, work_root: Path,
) -> dict[str, Any]:
    import nexus_multipair_recent_archive_runtime_snapshot as recent

    artifact = _artifact(repository, run_id, artifact_name, source_sha)
    work = work_root.resolve()
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True, exist_ok=True)
    outer = work / "artifact.zip"
    _download_outer(repository, artifact, outer)
    inner_name = recent.INNER_ARCHIVE_NAME
    sidecar_name = "nexus-multipair-recent-runtime-snapshot.sha256"
    files = _extract_exact_outer(outer, work / "outer", {inner_name, sidecar_name})
    _read_digest(files[sidecar_name], expected_sha256)
    actual = historical_artifact._sha256_file(files[inner_name])
    if actual != expected_sha256:
        raise RuntimeError("recent public artifact SHA-256 mismatch")
    historical_artifact._extract_inner(files[inner_name], destination)
    manifest = json.loads((destination / historical_artifact.MANIFEST_NAME).read_text(encoding="utf-8"))
    if (
        manifest.get("snapshot_digest") != expected_snapshot_digest
        or manifest.get("acquired_at_ms") != expected_acquired_at_ms
        or manifest.get("data_as_of_ms") != expected_data_as_of_ms
        or manifest.get("live_freshness_claimed") is not False
    ):
        raise RuntimeError("recent public artifact identity mismatch")
    verification = recent.verify_recent_archive_runtime_snapshot(
        destination, manifest, source_sha=source_sha, now_ms=now_ms
    )
    if verification.get("decision") != "pass":
        raise RuntimeError("recent snapshot verifier rejected public artifact")
    return {"artifact_id": int(artifact["id"]), "archive_sha256": actual, "snapshot_digest": manifest["snapshot_digest"]}


def _sha(value: str, pattern: re.Pattern[str], name: str) -> str:
    normalized = value.strip().lower()
    if not pattern.fullmatch(normalized):
        raise RuntimeError(f"invalid {name}")
    return normalized


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("wheelhouse", "historical", "recent"))
    parser.add_argument("--repository", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--artifact-name", required=True)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--expected-sha256", required=True)
    parser.add_argument("--expected-snapshot-digest")
    parser.add_argument("--expected-acquired-at-ms", type=int)
    parser.add_argument("--expected-data-as-of-ms", type=int)
    parser.add_argument("--now-ms", type=int)
    parser.add_argument("--repository-lock")
    parser.add_argument("--destination", required=True)
    parser.add_argument("--work-root", required=True)
    args = parser.parse_args()

    source_sha = _sha(args.source_sha, _SHA40, "source SHA")
    expected_sha256 = _sha(args.expected_sha256, _SHA64, "archive SHA-256")
    common = dict(
        repository=args.repository,
        run_id=args.run_id,
        artifact_name=args.artifact_name,
        source_sha=source_sha,
        expected_sha256=expected_sha256,
        destination=Path(args.destination),
        work_root=Path(args.work_root),
    )
    if args.mode == "wheelhouse":
        if not args.repository_lock:
            raise RuntimeError("wheelhouse mode requires --repository-lock")
        result = restore_wheelhouse(repository_lock=Path(args.repository_lock), **common)
    else:
        digest = _sha(args.expected_snapshot_digest or "", _SHA64, "snapshot digest")
        if args.mode == "historical":
            result = restore_historical(expected_snapshot_digest=digest, **common)
        else:
            if not all(isinstance(value, int) and value > 0 for value in (args.expected_acquired_at_ms, args.expected_data_as_of_ms, args.now_ms)):
                raise RuntimeError("recent mode requires positive time boundaries")
            result = restore_recent(
                expected_snapshot_digest=digest,
                expected_acquired_at_ms=int(args.expected_acquired_at_ms),
                expected_data_as_of_ms=int(args.expected_data_as_of_ms),
                now_ms=int(args.now_ms),
                **common,
            )
    print(json.dumps(result, sort_keys=True))
    print(f"public_current_run_artifact_{args.mode}=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
