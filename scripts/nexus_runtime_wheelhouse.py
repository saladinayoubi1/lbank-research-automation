from __future__ import annotations

import argparse
import hashlib
import http.client
import json
import os
import re
import shutil
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path


STORAGE_RETRY_DELAYS_SECONDS = (2.0, 5.0, 10.0, 20.0)
STORAGE_READ_TIMEOUT_SECONDS = 90
MAX_ARTIFACT_BYTES = 250 * 1024 * 1024
COPY_CHUNK_BYTES = 1024 * 1024


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_extract_flat_archive(archive_path: Path, destination: Path, *, allow_zip_only: bool = False) -> None:
    root = destination.resolve()
    with zipfile.ZipFile(archive_path) as archive:
        for member in archive.infolist():
            target = (destination / member.filename).resolve()
            if target != root and root not in target.parents:
                raise RuntimeError(f"unsafe archive path: {member.filename}")
            if Path(member.filename).name != member.filename:
                raise RuntimeError(f"nested archive member forbidden: {member.filename}")
            if allow_zip_only:
                if not member.filename.endswith(".zip"):
                    raise RuntimeError(f"unexpected outer artifact member: {member.filename}")
            elif member.filename != "requirements.lock" and not member.filename.endswith(".whl"):
                raise RuntimeError(f"unexpected wheelhouse member: {member.filename}")
        archive.extractall(destination)


def deterministic_pack(root: Path, output: Path) -> str:
    files = sorted(path for path in root.iterdir() if path.is_file())
    if not files or not any(path.suffix == ".whl" for path in files):
        raise RuntimeError("runtime wheelhouse is empty")
    if not (root / "requirements.lock").is_file():
        raise RuntimeError("runtime wheelhouse requirements.lock missing")
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_STORED) as archive:
        for path in files:
            info = zipfile.ZipInfo(path.name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_STORED
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            archive.writestr(info, path.read_bytes())
    return sha256_file(output)


def _validate_content_range(value: str | None, *, expected_start: int, expected_total: int) -> None:
    if not value:
        raise RuntimeError("resumed artifact response missing Content-Range")
    match = re.fullmatch(r"bytes (\d+)-(\d+)/(\d+)", value.strip())
    if not match:
        raise RuntimeError("invalid artifact Content-Range")
    start, end, total = (int(part) for part in match.groups())
    if start != expected_start:
        raise RuntimeError("artifact Content-Range start mismatch")
    if end < start:
        raise RuntimeError("artifact Content-Range end precedes start")
    if total != expected_total:
        raise RuntimeError("artifact Content-Range total mismatch")


def _stream_to_file(response, output: Path, *, mode: str, expected_size: int) -> None:
    with output.open(mode) as handle:
        while True:
            chunk = response.read(COPY_CHUNK_BYTES)
            if not chunk:
                break
            handle.write(chunk)
            if handle.tell() > expected_size:
                raise RuntimeError("artifact download exceeds declared size")


def _download_with_redirect_boundary(
    url: str,
    headers: dict[str, str],
    output: Path,
    *,
    expected_size: int,
    timeout: int = STORAGE_READ_TIMEOUT_SECONDS,
    retry_delays: tuple[float, ...] = STORAGE_RETRY_DELAYS_SECONDS,
    preserve_existing: bool = False,
) -> None:
    if expected_size <= 0 or expected_size > MAX_ARTIFACT_BYTES:
        raise RuntimeError("runtime wheelhouse artifact size is outside bounds")

    output.parent.mkdir(parents=True, exist_ok=True)
    if output.is_symlink():
        raise RuntimeError("runtime wheelhouse resume cache must not be a symlink")
    if not preserve_existing:
        output.unlink(missing_ok=True)
    elif output.exists() and not output.is_file():
        raise RuntimeError("runtime wheelhouse resume cache must be a regular file")
    opener = urllib.request.build_opener(NoRedirect)
    retryable_errors = (
        TimeoutError,
        socket.timeout,
        ConnectionResetError,
        http.client.IncompleteRead,
        urllib.error.URLError,
    )
    last_error: BaseException | None = None

    for attempt in range(len(retry_delays) + 1):
        offset = output.stat().st_size if output.exists() else 0
        if offset > expected_size:
            raise RuntimeError("partial artifact exceeds declared size")
        if offset == expected_size:
            return

        try:
            try:
                direct_response = opener.open(
                    urllib.request.Request(url, headers=headers),
                    timeout=60,
                )
            except urllib.error.HTTPError as exc:
                if exc.code not in (301, 302, 303, 307, 308):
                    raise
                location = exc.headers.get("Location")
                if not location:
                    raise RuntimeError("artifact redirect missing Location") from exc
                parsed = urllib.parse.urlparse(location)
                if parsed.scheme != "https" or not parsed.hostname:
                    raise RuntimeError("artifact redirect must be absolute HTTPS") from exc

                storage_headers = {"User-Agent": "nexus-runtime-wheelhouse"}
                mode = "wb"
                if offset:
                    storage_headers["Range"] = f"bytes={offset}-"
                    mode = "ab"

                # Signed object storage is a separate trust boundary. Never
                # forward the GitHub bearer token to the redirected request.
                storage_request = urllib.request.Request(location, headers=storage_headers)
                with urllib.request.urlopen(storage_request, timeout=timeout) as response:
                    if offset:
                        if response.status != 206:
                            raise RuntimeError("resumed artifact request requires HTTP 206")
                        _validate_content_range(
                            response.headers.get("Content-Range"),
                            expected_start=offset,
                            expected_total=expected_size,
                        )
                    else:
                        if response.status not in (200, 206):
                            raise RuntimeError(f"unexpected artifact storage response: {response.status}")
                        if response.status == 206:
                            _validate_content_range(
                                response.headers.get("Content-Range"),
                                expected_start=0,
                                expected_total=expected_size,
                            )
                    _stream_to_file(
                        response,
                        output,
                        mode=mode,
                        expected_size=expected_size,
                    )
            else:
                with direct_response as response:
                    if response.status != 200:
                        raise RuntimeError(f"unexpected artifact response: {response.status}")
                    # Direct GitHub responses are trusted, but resumability is
                    # defined only across the signed object-storage boundary.
                    output.unlink(missing_ok=True)
                    _stream_to_file(
                        response,
                        output,
                        mode="wb",
                        expected_size=expected_size,
                    )

            actual_size = output.stat().st_size if output.exists() else 0
            if actual_size == expected_size:
                return
            if actual_size > expected_size:
                raise RuntimeError("artifact download exceeds declared size")
            last_error = RuntimeError(
                f"artifact download ended early at {actual_size}/{expected_size} bytes"
            )
        except retryable_errors as exc:
            last_error = exc

        if attempt >= len(retry_delays):
            break
        time.sleep(retry_delays[attempt])

    actual_size = output.stat().st_size if output.exists() else 0
    raise RuntimeError(
        "runtime wheelhouse artifact download failed after bounded resumable retries "
        f"({actual_size}/{expected_size} bytes)"
    ) from last_error


def _cross_attempt_resume_path(*, run_id: str, artifact_id: int, expected_sha256: str) -> Path:
    cache_root = Path.home() / ".cache" / "nexus-paper-runtime-wheelhouse"
    cache_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        cache_root.chmod(0o700)
    except OSError:
        pass
    current = cache_root / f"{run_id}-{artifact_id}-{expected_sha256}.zip.part"
    for stale in cache_root.glob("*.zip.part"):
        if stale != current and stale.is_file() and not stale.is_symlink():
            stale.unlink(missing_ok=True)
    return current


def restore_current_run_artifact(
    *,
    repository: str,
    run_id: str,
    token: str,
    artifact_name: str,
    expected_sha256: str,
    repository_lock: Path,
    destination: Path,
    work_root: Path,
) -> dict[str, object]:
    expected_sha256 = expected_sha256.strip().lower()
    if len(expected_sha256) != 64 or any(ch not in "0123456789abcdef" for ch in expected_sha256):
        raise RuntimeError("invalid runtime wheelhouse expected SHA-256")

    work_root.mkdir(parents=True, exist_ok=True)
    outer_root = work_root / "outer"
    shutil.rmtree(outer_root, ignore_errors=True)
    shutil.rmtree(destination, ignore_errors=True)
    outer_root.mkdir(parents=True, exist_ok=True)
    destination.mkdir(parents=True, exist_ok=True)

    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "nexus-runtime-wheelhouse",
    }
    query = urllib.parse.urlencode({"name": artifact_name, "per_page": 100})
    list_url = f"https://api.github.com/repos/{repository}/actions/runs/{run_id}/artifacts?{query}"
    with urllib.request.urlopen(
        urllib.request.Request(list_url, headers=headers), timeout=60
    ) as response:
        payload = json.load(response)
    artifacts = [
        artifact
        for artifact in (payload.get("artifacts") or [])
        if artifact.get("name") == artifact_name and not artifact.get("expired", False)
    ]
    if len(artifacts) != 1:
        raise RuntimeError(
            f"expected exactly one current-run runtime wheelhouse artifact, got {len(artifacts)}"
        )

    artifact_id = int(artifacts[0]["id"])
    artifact_size = int(artifacts[0].get("size_in_bytes") or 0)
    outer_zip = _cross_attempt_resume_path(
        run_id=run_id,
        artifact_id=artifact_id,
        expected_sha256=expected_sha256,
    )
    download_url = f"https://api.github.com/repos/{repository}/actions/artifacts/{artifact_id}/zip"
    try:
        _download_with_redirect_boundary(
            download_url,
            headers,
            outer_zip,
            expected_size=artifact_size,
            preserve_existing=True,
        )
        safe_extract_flat_archive(outer_zip, outer_root, allow_zip_only=True)
        extracted = sorted(path for path in outer_root.iterdir() if path.is_file())
        if len(extracted) != 1 or extracted[0].suffix.lower() != ".zip":
            raise RuntimeError("runtime wheelhouse artifact must contain exactly one inner archive")
        inner_zip = extracted[0]

        actual_sha256 = sha256_file(inner_zip)
        if actual_sha256 != expected_sha256:
            raise RuntimeError("runtime wheelhouse archive SHA-256 mismatch")
        safe_extract_flat_archive(inner_zip, destination)

        embedded_lock = destination / "requirements.lock"
        if embedded_lock.read_bytes() != repository_lock.read_bytes():
            raise RuntimeError("runtime wheelhouse requirements.lock mismatch")
        wheels = sorted(destination.glob("*.whl"))
        if not wheels:
            raise RuntimeError("runtime wheelhouse contains no wheels")
    except Exception:
        if outer_zip.exists() and outer_zip.stat().st_size >= artifact_size > 0:
            outer_zip.unlink(missing_ok=True)
        raise
    else:
        outer_zip.unlink(missing_ok=True)
        try:
            outer_zip.parent.rmdir()
        except OSError:
            pass

    return {
        "artifact_id": artifact_id,
        "artifact_size": artifact_size,
        "archive_sha256": actual_sha256,
        "wheel_count": len(wheels),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    pack = subparsers.add_parser("pack")
    pack.add_argument("--root", required=True)
    pack.add_argument("--output", required=True)
    pack.add_argument("--digest-output")

    restore = subparsers.add_parser("restore-current-run")
    restore.add_argument("--repository", required=True)
    restore.add_argument("--run-id", required=True)
    restore.add_argument("--artifact-name", required=True)
    restore.add_argument("--expected-sha256", required=True)
    restore.add_argument("--repository-lock", required=True)
    restore.add_argument("--destination", required=True)
    restore.add_argument("--work-root", required=True)
    restore.add_argument("--token-env", default="GH_TOKEN")

    args = parser.parse_args()
    if args.command == "pack":
        digest = deterministic_pack(Path(args.root), Path(args.output))
        if args.digest_output:
            Path(args.digest_output).write_text(digest + "\n", encoding="ascii")
        print(f"runtime_wheelhouse_archive_sha256={digest}")
        return 0

    token = os.environ.get(args.token_env, "")
    if not token:
        raise RuntimeError(f"missing token environment variable: {args.token_env}")
    result = restore_current_run_artifact(
        repository=args.repository,
        run_id=args.run_id,
        token=token,
        artifact_name=args.artifact_name,
        expected_sha256=args.expected_sha256,
        repository_lock=Path(args.repository_lock),
        destination=Path(args.destination),
        work_root=Path(args.work_root),
    )
    print(f"runtime_wheelhouse_artifact_id={result['artifact_id']}")
    print(f"runtime_wheelhouse_artifact_size={result['artifact_size']}")
    print(f"runtime_wheelhouse_archive_sha256={result['archive_sha256']}")
    print(f"runtime_wheelhouse_wheel_count={result['wheel_count']}")
    print("runtime_wheelhouse_verification=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())