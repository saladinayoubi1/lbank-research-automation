from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import stat
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any


API_VERSION = "2022-11-28"
DEFAULT_PREFIX = "bybit-full-history-final-"
DELIVERY_NAME = "BYBIT_full_history_delivery.json"


class ReplayArtifactError(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _request_json(url: str, token: str) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": API_VERSION,
            "User-Agent": "nexus-bybit-replay-selector",
        },
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.load(response)


def _download(url: str, token: str, destination: Path) -> None:
    request = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": API_VERSION,
            "User-Agent": "nexus-bybit-replay-selector",
        },
    )
    with urllib.request.urlopen(request, timeout=180) as response:
        destination.write_bytes(response.read())


def list_candidate_artifacts(
    repository: str,
    token: str,
    prefix: str = DEFAULT_PREFIX,
    max_pages: int = 10,
) -> list[dict[str, Any]]:
    if "/" not in repository:
        raise ReplayArtifactError("repository must be owner/name")
    candidates: list[dict[str, Any]] = []
    for page in range(1, max_pages + 1):
        query = urllib.parse.urlencode({"per_page": 100, "page": page})
        payload = _request_json(
            f"https://api.github.com/repos/{repository}/actions/artifacts?{query}",
            token,
        )
        batch = payload.get("artifacts", [])
        if not isinstance(batch, list):
            raise ReplayArtifactError("GitHub artifact response is malformed")
        for artifact in batch:
            name = str(artifact.get("name", ""))
            if artifact.get("expired") is True or not name.startswith(prefix):
                continue
            if not artifact.get("id"):
                continue
            candidates.append(artifact)
        if len(batch) < 100:
            break
    candidates.sort(
        key=lambda item: (str(item.get("created_at", "")), int(item.get("id", 0))),
        reverse=True,
    )
    return candidates


def safe_extract(archive: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as handle:
        for info in handle.infolist():
            member = PurePosixPath(info.filename)
            if member.is_absolute() or ".." in member.parts:
                raise ReplayArtifactError(f"unsafe artifact member: {info.filename}")
            mode = (info.external_attr >> 16) & 0xFFFF
            if stat.S_ISLNK(mode):
                raise ReplayArtifactError(f"symlink artifact member forbidden: {info.filename}")
        handle.extractall(destination)


def validate_candidate(
    extracted_root: Path,
    expected_file_name: str,
    expected_sha256: str,
) -> tuple[Path, Path]:
    archive_matches = list(extracted_root.rglob(expected_file_name))
    delivery_matches = list(extracted_root.rglob(DELIVERY_NAME))
    if len(archive_matches) != 1 or len(delivery_matches) != 1:
        raise ReplayArtifactError(
            "candidate must contain exactly one replay ZIP and one delivery manifest"
        )
    replay_zip = archive_matches[0]
    delivery_path = delivery_matches[0]
    delivery = json.loads(delivery_path.read_text(encoding="utf-8"))
    if str(delivery.get("file_name", "")) != expected_file_name:
        raise ReplayArtifactError("delivery manifest file_name mismatch")
    manifest_digest = str(delivery.get("sha256", "")).lower()
    expected = expected_sha256.lower()
    if manifest_digest != expected:
        raise ReplayArtifactError("delivery manifest replay SHA mismatch")
    actual = sha256_file(replay_zip)
    if actual != expected:
        raise ReplayArtifactError("replay ZIP SHA mismatch")
    return replay_zip, delivery_path


def restore_matching_artifact(
    repository: str,
    token: str,
    output_dir: Path,
    expected_file_name: str,
    expected_sha256: str,
    prefix: str = DEFAULT_PREFIX,
    max_candidates: int = 20,
) -> dict[str, Any]:
    candidates = list_candidate_artifacts(repository, token, prefix=prefix)
    if not candidates:
        raise ReplayArtifactError("no unexpired replay artifacts found")
    output_dir.mkdir(parents=True, exist_ok=True)
    errors: list[str] = []
    for artifact in candidates[:max_candidates]:
        artifact_id = int(artifact["id"])
        with tempfile.TemporaryDirectory(prefix="nexus-replay-") as temp_dir:
            temp = Path(temp_dir)
            outer_zip = temp / "artifact.zip"
            extracted = temp / "artifact"
            try:
                _download(
                    f"https://api.github.com/repos/{repository}/actions/artifacts/{artifact_id}/zip",
                    token,
                    outer_zip,
                )
                safe_extract(outer_zip, extracted)
                replay_zip, delivery = validate_candidate(
                    extracted,
                    expected_file_name=expected_file_name,
                    expected_sha256=expected_sha256,
                )
            except (ReplayArtifactError, urllib.error.URLError, zipfile.BadZipFile, json.JSONDecodeError) as exc:
                errors.append(f"{artifact_id}:{type(exc).__name__}:{exc}")
                continue
            target_zip = output_dir / expected_file_name
            target_delivery = output_dir / DELIVERY_NAME
            shutil.copyfile(replay_zip, target_zip)
            shutil.copyfile(delivery, target_delivery)
            result = {
                "artifact_id": artifact_id,
                "artifact_name": str(artifact.get("name", "")),
                "artifact_created_at": str(artifact.get("created_at", "")),
                "replay_file": target_zip.as_posix(),
                "replay_sha256": expected_sha256.lower(),
                "delivery_manifest": target_delivery.as_posix(),
                "candidate_failures": len(errors),
            }
            print(json.dumps(result, sort_keys=True))
            return result
    detail = "; ".join(errors[-5:]) if errors else "no candidates inspected"
    raise ReplayArtifactError(
        f"no unexpired artifact matched immutable replay SHA {expected_sha256}: {detail}"
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", default=os.environ.get("GITHUB_REPOSITORY", ""))
    parser.add_argument("--token", default=os.environ.get("GH_TOKEN", ""))
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--expected-file-name", required=True)
    parser.add_argument("--expected-sha256", required=True)
    parser.add_argument("--artifact-prefix", default=DEFAULT_PREFIX)
    parser.add_argument("--max-candidates", type=int, default=20)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.token:
        raise ReplayArtifactError("GitHub token is required")
    if len(args.expected_sha256) != 64:
        raise ReplayArtifactError("expected SHA-256 must be 64 hex characters")
    restore_matching_artifact(
        repository=args.repository,
        token=args.token,
        output_dir=args.output_dir,
        expected_file_name=args.expected_file_name,
        expected_sha256=args.expected_sha256,
        prefix=args.artifact_prefix,
        max_candidates=args.max_candidates,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
