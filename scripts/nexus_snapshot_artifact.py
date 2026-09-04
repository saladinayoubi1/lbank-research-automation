from __future__ import annotations

import argparse
import hashlib
import http.client
import json
import os
import re
import shutil
import socket
import stat
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any


API_VERSION = "2022-11-28"
SCHEMA = "nexus.multipair-discovery-archive-snapshot.v1"
SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT")
TIMEFRAMES = ("minute15", "hour1", "hour4")
INNER_ARCHIVE_NAME = "nexus-multipair-archive-snapshot.zip"
MANIFEST_NAME = "snapshot-manifest.json"
MAX_OUTER_ARTIFACT_BYTES = 50 * 1024 * 1024
MAX_INNER_ARCHIVE_BYTES = 50 * 1024 * 1024
MAX_EXTRACTED_BYTES = 100 * 1024 * 1024
MAX_MEMBER_BYTES = 20 * 1024 * 1024
COPY_CHUNK_BYTES = 1024 * 1024
READ_TIMEOUT_SECONDS = 90
RETRY_DELAYS_SECONDS = (2.0, 5.0, 10.0, 20.0)
_SHA40 = re.compile(r"^[0-9a-f]{40}$")
_SHA64 = re.compile(r"^[0-9a-f]{64}$")


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(COPY_CHUNK_BYTES), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _headers(token: str) -> dict[str, str]:
    return {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": API_VERSION,
        "User-Agent": "nexus-snapshot-artifact",
    }


def _json_get(url: str, headers: dict[str, str]) -> dict[str, Any]:
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=60) as response:
        value = json.load(response)
    if not isinstance(value, dict):
        raise RuntimeError("GitHub API response is not an object")
    return value


def _validate_content_range(value: str | None, *, expected_start: int, expected_total: int) -> None:
    match = re.fullmatch(r"bytes (\d+)-(\d+)/(\d+)", (value or "").strip())
    if not match:
        raise RuntimeError("invalid artifact Content-Range")
    start, end, total = (int(part) for part in match.groups())
    if start != expected_start or end < start or total != expected_total:
        raise RuntimeError("artifact Content-Range mismatch")


def _stream(response, output: Path, *, mode: str, expected_size: int) -> None:
    with output.open(mode) as handle:
        while True:
            chunk = response.read(COPY_CHUNK_BYTES)
            if not chunk:
                break
            handle.write(chunk)
            if handle.tell() > expected_size:
                raise RuntimeError("artifact download exceeds declared size")


def _download(url: str, headers: dict[str, str], output: Path, *, expected_size: int) -> None:
    if expected_size <= 0 or expected_size > MAX_OUTER_ARTIFACT_BYTES:
        raise RuntimeError("snapshot artifact size is outside bounds")
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.is_symlink():
        raise RuntimeError("snapshot artifact cache must not be a symlink")
    output.unlink(missing_ok=True)
    opener = urllib.request.build_opener(NoRedirect)
    retryable = (TimeoutError, socket.timeout, ConnectionResetError, http.client.IncompleteRead, urllib.error.URLError)
    last_error: BaseException | None = None

    for attempt in range(len(RETRY_DELAYS_SECONDS) + 1):
        offset = output.stat().st_size if output.exists() else 0
        if offset > expected_size:
            raise RuntimeError("partial artifact exceeds declared size")
        if offset == expected_size:
            return
        try:
            try:
                direct = opener.open(urllib.request.Request(url, headers=headers), timeout=60)
            except urllib.error.HTTPError as exc:
                if exc.code not in (301, 302, 303, 307, 308):
                    raise
                location = exc.headers.get("Location")
                parsed = urllib.parse.urlparse(location or "")
                if parsed.scheme != "https" or not parsed.hostname:
                    raise RuntimeError("artifact redirect must be absolute HTTPS") from exc
                storage_headers = {"User-Agent": "nexus-snapshot-artifact"}
                mode = "wb"
                if offset:
                    storage_headers["Range"] = f"bytes={offset}-"
                    mode = "ab"
                with urllib.request.urlopen(
                    urllib.request.Request(location, headers=storage_headers), timeout=READ_TIMEOUT_SECONDS
                ) as response:
                    if offset:
                        if response.status != 206:
                            raise RuntimeError("resumed artifact request requires HTTP 206")
                        _validate_content_range(response.headers.get("Content-Range"), expected_start=offset, expected_total=expected_size)
                    elif response.status not in (200, 206):
                        raise RuntimeError(f"unexpected artifact storage response: {response.status}")
                    elif response.status == 206:
                        _validate_content_range(response.headers.get("Content-Range"), expected_start=0, expected_total=expected_size)
                    _stream(response, output, mode=mode, expected_size=expected_size)
            else:
                with direct as response:
                    if response.status != 200:
                        raise RuntimeError(f"unexpected artifact response: {response.status}")
                    output.unlink(missing_ok=True)
                    _stream(response, output, mode="wb", expected_size=expected_size)
            if output.stat().st_size == expected_size:
                return
            last_error = RuntimeError("artifact download ended early")
        except retryable as exc:
            last_error = exc
        if attempt >= len(RETRY_DELAYS_SECONDS):
            break
        time.sleep(RETRY_DELAYS_SECONDS[attempt])
    raise RuntimeError("snapshot artifact download failed after bounded retries") from last_error


def _zip_member_is_regular(member: zipfile.ZipInfo) -> bool:
    if member.is_dir():
        return False
    mode = (member.external_attr >> 16) & 0xFFFF
    return mode == 0 or stat.S_ISREG(mode)


def _extract_outer(outer_zip: Path, work_root: Path) -> Path:
    with zipfile.ZipFile(outer_zip) as archive:
        members = archive.infolist()
        if len(members) != 1 or members[0].filename != INNER_ARCHIVE_NAME:
            raise RuntimeError("snapshot artifact must contain exactly one deterministic inner archive")
        member = members[0]
        if not _zip_member_is_regular(member) or member.file_size <= 0 or member.file_size > MAX_INNER_ARCHIVE_BYTES:
            raise RuntimeError("snapshot inner archive member is unsafe")
        target = work_root / INNER_ARCHIVE_NAME
        with archive.open(member) as source, target.open("wb") as output:
            shutil.copyfileobj(source, output, length=COPY_CHUNK_BYTES)
    return target


def _expected_members() -> set[str]:
    return {MANIFEST_NAME} | {
        f"bybit_market/{symbol}/{timeframe}.parquet"
        for symbol in SYMBOLS
        for timeframe in TIMEFRAMES
    }


def _extract_inner(inner_zip: Path, destination: Path) -> None:
    root = destination.resolve()
    shutil.rmtree(root, ignore_errors=True)
    root.mkdir(parents=True, exist_ok=True)
    expected = _expected_members()
    with zipfile.ZipFile(inner_zip) as archive:
        members = archive.infolist()
        names = [member.filename for member in members]
        if len(names) != len(set(names)) or set(names) != expected:
            raise RuntimeError("snapshot inner archive surface is not the exact 12-cell contract")
        total = 0
        for member in members:
            if not _zip_member_is_regular(member):
                raise RuntimeError(f"snapshot member is not a regular file: {member.filename}")
            pure = PurePosixPath(member.filename)
            if pure.is_absolute() or ".." in pure.parts or "\\" in member.filename:
                raise RuntimeError(f"unsafe snapshot member path: {member.filename}")
            if member.file_size <= 0 or member.file_size > MAX_MEMBER_BYTES:
                raise RuntimeError(f"snapshot member size is outside bounds: {member.filename}")
            total += member.file_size
            if total > MAX_EXTRACTED_BYTES:
                raise RuntimeError("snapshot extracted size exceeds bounds")
            target = (root / Path(*pure.parts)).resolve()
            if root not in target.parents:
                raise RuntimeError(f"unsafe snapshot extraction path: {member.filename}")
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(member) as source, target.open("wb") as output:
                shutil.copyfileobj(source, output, length=COPY_CHUNK_BYTES)


def _validate_manifest(destination: Path, *, source_sha: str, snapshot_digest: str) -> dict[str, Any]:
    try:
        value = json.loads((destination / MANIFEST_NAME).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("snapshot manifest is unavailable after extraction") from exc
    if not isinstance(value, dict):
        raise RuntimeError("snapshot manifest must be an object")
    if (
        value.get("schema_version") != SCHEMA
        or value.get("source_sha") != source_sha
        or value.get("snapshot_digest") != snapshot_digest
        or value.get("symbols") != list(SYMBOLS)
        or value.get("timeframes") != list(TIMEFRAMES)
        or value.get("archive_source_count") != 12
        or value.get("cell_count") != 12
        or value.get("history_limit") != 500
        or value.get("data_origin") != "official_public_bybit_spot_trade_archive_aggregated"
        or value.get("runtime_freshness_claimed") is not False
        or value.get("research_only") is not True
        or value.get("paper_execution_started") is not False
        or value.get("live_trading_authority") is not False
        or value.get("private_credentials_used") is not False
        or value.get("real_exchange_orders") is not False
        or value.get("automatic_strategy_promotion") is not False
        or value.get("silent_exchange_substitution") is not False
        or value.get("third_party_proxy_used") is not False
        or value.get("issue_984_state_touched") is not False
        or value.get("persistent_runtime_database_on_github") is not False
    ):
        raise RuntimeError("snapshot manifest boundary contract mismatch")
    return value


def restore_current_run_snapshot(
    *, repository: str, run_id: str, token: str, artifact_name: str,
    expected_sha256: str, expected_source_sha: str, expected_snapshot_digest: str,
    destination: Path, work_root: Path,
) -> dict[str, Any]:
    expected_sha256 = expected_sha256.strip().lower()
    expected_source_sha = expected_source_sha.strip().lower()
    expected_snapshot_digest = expected_snapshot_digest.strip().lower()
    if not _SHA64.fullmatch(expected_sha256) or not _SHA40.fullmatch(expected_source_sha) or not _SHA64.fullmatch(expected_snapshot_digest):
        raise RuntimeError("invalid snapshot artifact identity digest")
    headers = _headers(token)
    run = _json_get(f"https://api.github.com/repos/{repository}/actions/runs/{run_id}", headers)
    if (
        str(run.get("id")) != str(run_id)
        or run.get("head_sha") != expected_source_sha
        or run.get("head_branch") != "main"
        or run.get("event") not in {"push", "workflow_dispatch"}
    ):
        raise RuntimeError("current workflow run identity does not match expected main source")

    query = urllib.parse.urlencode({"name": artifact_name, "per_page": 100})
    payload = _json_get(f"https://api.github.com/repos/{repository}/actions/runs/{run_id}/artifacts?{query}", headers)
    artifacts = [row for row in payload.get("artifacts", []) if isinstance(row, dict) and row.get("name") == artifact_name and not row.get("expired", False)]
    if len(artifacts) != 1:
        raise RuntimeError(f"expected exactly one current-run snapshot artifact, got {len(artifacts)}")
    artifact = artifacts[0]
    artifact_id = int(artifact.get("id") or 0)
    artifact_size = int(artifact.get("size_in_bytes") or 0)
    work = work_root.resolve()
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True, exist_ok=True)
    outer_zip = work / "artifact.zip"
    _download(
        f"https://api.github.com/repos/{repository}/actions/artifacts/{artifact_id}/zip",
        headers,
        outer_zip,
        expected_size=artifact_size,
    )
    inner_zip = _extract_outer(outer_zip, work)
    actual_sha256 = _sha256_file(inner_zip)
    if actual_sha256 != expected_sha256:
        raise RuntimeError("snapshot deterministic archive SHA-256 mismatch")
    _extract_inner(inner_zip, destination)
    manifest = _validate_manifest(destination.resolve(), source_sha=expected_source_sha, snapshot_digest=expected_snapshot_digest)
    return {
        "artifact_id": artifact_id,
        "artifact_size": artifact_size,
        "archive_sha256": actual_sha256,
        "snapshot_digest": manifest["snapshot_digest"],
        "cell_count": manifest["cell_count"],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--artifact-name", required=True)
    parser.add_argument("--expected-sha256", required=True)
    parser.add_argument("--expected-source-sha", required=True)
    parser.add_argument("--expected-snapshot-digest", required=True)
    parser.add_argument("--destination", required=True)
    parser.add_argument("--work-root", required=True)
    parser.add_argument("--token-env", default="GH_TOKEN")
    args = parser.parse_args()
    token = os.environ.get(args.token_env, "")
    if not token:
        raise RuntimeError(f"missing token environment variable: {args.token_env}")
    result = restore_current_run_snapshot(
        repository=args.repository,
        run_id=args.run_id,
        token=token,
        artifact_name=args.artifact_name,
        expected_sha256=args.expected_sha256,
        expected_source_sha=args.expected_source_sha,
        expected_snapshot_digest=args.expected_snapshot_digest,
        destination=Path(args.destination),
        work_root=Path(args.work_root),
    )
    for key in ("artifact_id", "artifact_size", "archive_sha256", "snapshot_digest", "cell_count"):
        print(f"snapshot_artifact_{key}={result[key]}")
    print("snapshot_artifact_verification=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
