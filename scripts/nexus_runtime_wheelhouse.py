from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path


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


def _download_with_redirect_boundary(url: str, headers: dict[str, str], output: Path, *, timeout: int) -> None:
    opener = urllib.request.build_opener(NoRedirect)
    try:
        with opener.open(urllib.request.Request(url, headers=headers), timeout=60) as response, output.open("wb") as handle:
            if response.status != 200:
                raise RuntimeError(f"unexpected artifact response: {response.status}")
            shutil.copyfileobj(response, handle)
    except urllib.error.HTTPError as exc:
        if exc.code not in (301, 302, 303, 307, 308):
            raise
        location = exc.headers.get("Location")
        if not location:
            raise RuntimeError("artifact redirect missing Location") from exc
        parsed = urllib.parse.urlparse(location)
        if parsed.scheme != "https" or not parsed.hostname:
            raise RuntimeError("artifact redirect must be absolute HTTPS") from exc
        # Signed object storage is a separate trust boundary. Never forward the
        # GitHub bearer token to the redirected storage request.
        storage_request = urllib.request.Request(
            location,
            headers={"User-Agent": "nexus-runtime-wheelhouse"},
        )
        with urllib.request.urlopen(storage_request, timeout=timeout) as response, output.open("wb") as handle:
            shutil.copyfileobj(response, handle)


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
    outer_zip = work_root / "runtime-wheelhouse-artifact.zip"
    outer_root = work_root / "outer"
    inner_zip = outer_root / "nexus-paper-runtime-wheelhouse.zip"
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
    with urllib.request.urlopen(urllib.request.Request(list_url, headers=headers), timeout=60) as response:
        payload = json.load(response)
    artifacts = [
        artifact
        for artifact in (payload.get("artifacts") or [])
        if artifact.get("name") == artifact_name and not artifact.get("expired", False)
    ]
    if len(artifacts) != 1:
        raise RuntimeError(f"expected exactly one current-run runtime wheelhouse artifact, got {len(artifacts)}")

    artifact_id = int(artifacts[0]["id"])
    download_url = f"https://api.github.com/repos/{repository}/actions/artifacts/{artifact_id}/zip"
    _download_with_redirect_boundary(download_url, headers, outer_zip, timeout=180)
    safe_extract_flat_archive(outer_zip, outer_root, allow_zip_only=True)
    extracted = sorted(path for path in outer_root.iterdir() if path.is_file())
    if extracted != [inner_zip]:
        raise RuntimeError("runtime wheelhouse artifact must contain exactly one inner archive")

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
    return {
        "artifact_id": artifact_id,
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
    print(f"runtime_wheelhouse_archive_sha256={result['archive_sha256']}")
    print(f"runtime_wheelhouse_wheel_count={result['wheel_count']}")
    print("runtime_wheelhouse_verification=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
