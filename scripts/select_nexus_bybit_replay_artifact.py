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
REPLAY_V2_MANIFEST = "REPLAY_DATASET_MANIFEST.json"


class ReplayArtifactError(RuntimeError):
    pass


class _CrossHostAuthStrippingRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Preserve GitHub auth on same-origin redirects, never forward it to blob hosts."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        redirected = super().redirect_request(req, fp, code, msg, headers, newurl)
        if redirected is None:
            return None
        source = urllib.parse.urlsplit(req.full_url)
        target = urllib.parse.urlsplit(newurl)
        if (source.scheme.lower(), source.netloc.lower()) != (
            target.scheme.lower(),
            target.netloc.lower(),
        ):
            redirected.remove_header("Authorization")
        return redirected


_ARTIFACT_OPENER = urllib.request.build_opener(_CrossHostAuthStrippingRedirectHandler())


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_json_bytes(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


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
    with _ARTIFACT_OPENER.open(request, timeout=180) as response:
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


def _validate_v2_semantic_identity(
    replay_zip: Path,
    delivery: dict[str, Any],
    expected_semantic_sha256: str,
) -> str:
    expected = expected_semantic_sha256.lower()
    if str(delivery.get("semantic_dataset_sha256", "")).lower() != expected:
        raise ReplayArtifactError("delivery manifest semantic replay SHA mismatch")
    if (
        delivery.get("paper_replay_only") is not True
        or delivery.get("live_trading_authority") is not False
        or delivery.get("private_credentials_used") is not False
    ):
        raise ReplayArtifactError("delivery manifest replay authority mismatch")
    claimed_zip_sha = str(delivery.get("sha256", "")).lower()
    if len(claimed_zip_sha) != 64 or any(ch not in "0123456789abcdef" for ch in claimed_zip_sha):
        raise ReplayArtifactError("delivery manifest replay ZIP SHA is invalid")
    actual_zip_sha = sha256_file(replay_zip)
    if actual_zip_sha != claimed_zip_sha:
        raise ReplayArtifactError("replay ZIP SHA mismatch")
    try:
        with zipfile.ZipFile(replay_zip) as handle:
            names = handle.namelist()
            if names.count(REPLAY_V2_MANIFEST) != 1:
                raise ReplayArtifactError("replay v2 dataset manifest is missing or ambiguous")
            manifest = json.loads(handle.read(REPLAY_V2_MANIFEST))
    except zipfile.BadZipFile as exc:
        raise ReplayArtifactError("replay v2 ZIP is invalid") from exc
    except json.JSONDecodeError as exc:
        raise ReplayArtifactError("replay v2 dataset manifest is invalid JSON") from exc
    if not isinstance(manifest, dict) or manifest.get("schema_version") != 2:
        raise ReplayArtifactError("replay v2 dataset manifest schema mismatch")
    if str(manifest.get("semantic_dataset_sha256", "")).lower() != expected:
        raise ReplayArtifactError("replay v2 semantic dataset SHA mismatch")
    claimed_manifest_sha = str(manifest.get("manifest_sha256", "")).lower()
    if claimed_manifest_sha != str(delivery.get("dataset_manifest_sha256", "")).lower():
        raise ReplayArtifactError("replay v2 dataset manifest delivery SHA mismatch")
    manifest_core = dict(manifest)
    manifest_core.pop("manifest_sha256", None)
    if hashlib.sha256(_canonical_json_bytes(manifest_core)).hexdigest() != claimed_manifest_sha:
        raise ReplayArtifactError("replay v2 dataset manifest SHA mismatch")
    if manifest.get("series_count") != delivery.get("series_count"):
        raise ReplayArtifactError("replay v2 series_count mismatch")
    return actual_zip_sha


def validate_candidate(
    extracted_root: Path,
    expected_file_name: str,
    expected_sha256: str | None = None,
    *,
    expected_semantic_sha256: str | None = None,
    delivery_name: str = DELIVERY_NAME,
) -> tuple[Path, Path]:
    if bool(expected_sha256) == bool(expected_semantic_sha256):
        raise ReplayArtifactError("exactly one replay identity mode is required")
    archive_matches = list(extracted_root.rglob(expected_file_name))
    delivery_matches = list(extracted_root.rglob(delivery_name))
    if len(archive_matches) != 1 or len(delivery_matches) != 1:
        raise ReplayArtifactError(
            "candidate must contain exactly one replay ZIP and one delivery manifest"
        )
    replay_zip = archive_matches[0]
    delivery_path = delivery_matches[0]
    delivery = json.loads(delivery_path.read_text(encoding="utf-8"))
    if str(delivery.get("file_name", "")) != expected_file_name:
        raise ReplayArtifactError("delivery manifest file_name mismatch")
    if expected_sha256:
        manifest_digest = str(delivery.get("sha256", "")).lower()
        expected = expected_sha256.lower()
        if manifest_digest != expected:
            raise ReplayArtifactError("delivery manifest replay SHA mismatch")
        if sha256_file(replay_zip) != expected:
            raise ReplayArtifactError("replay ZIP SHA mismatch")
    else:
        assert expected_semantic_sha256 is not None
        _validate_v2_semantic_identity(replay_zip, delivery, expected_semantic_sha256)
    return replay_zip, delivery_path


def restore_matching_artifact(
    repository: str,
    token: str,
    output_dir: Path,
    expected_file_name: str,
    expected_sha256: str | None = None,
    *,
    expected_semantic_sha256: str | None = None,
    delivery_name: str = DELIVERY_NAME,
    prefix: str = DEFAULT_PREFIX,
    max_candidates: int = 20,
) -> dict[str, Any]:
    if bool(expected_sha256) == bool(expected_semantic_sha256):
        raise ReplayArtifactError("exactly one replay identity mode is required")
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
                    expected_semantic_sha256=expected_semantic_sha256,
                    delivery_name=delivery_name,
                )
            except (ReplayArtifactError, urllib.error.URLError, zipfile.BadZipFile, json.JSONDecodeError) as exc:
                errors.append(f"{artifact_id}:{type(exc).__name__}:{exc}")
                continue
            target_zip = output_dir / expected_file_name
            target_delivery = output_dir / delivery_name
            shutil.copyfile(replay_zip, target_zip)
            shutil.copyfile(delivery, target_delivery)
            result = {
                "artifact_id": artifact_id,
                "artifact_name": str(artifact.get("name", "")),
                "artifact_created_at": str(artifact.get("created_at", "")),
                "replay_file": target_zip.as_posix(),
                "replay_sha256": sha256_file(target_zip),
                "semantic_dataset_sha256": (expected_semantic_sha256 or "").lower(),
                "delivery_manifest": target_delivery.as_posix(),
                "candidate_failures": len(errors),
            }
            print(json.dumps(result, sort_keys=True))
            return result
    identity = expected_semantic_sha256 or expected_sha256 or "unknown"
    detail = "; ".join(errors[-5:]) if errors else "no candidates inspected"
    raise ReplayArtifactError(
        f"no unexpired artifact matched replay identity {identity}: {detail}"
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", default=os.environ.get("GITHUB_REPOSITORY", ""))
    parser.add_argument("--token", default=os.environ.get("GH_TOKEN", ""))
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--expected-file-name", required=True)
    identity = parser.add_mutually_exclusive_group(required=True)
    identity.add_argument("--expected-sha256")
    identity.add_argument("--expected-semantic-sha256")
    parser.add_argument("--delivery-name", default=DELIVERY_NAME)
    parser.add_argument("--artifact-prefix", default=DEFAULT_PREFIX)
    parser.add_argument("--max-candidates", type=int, default=20)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.token:
        raise ReplayArtifactError("GitHub token is required")
    expected_identity = args.expected_semantic_sha256 or args.expected_sha256
    if len(expected_identity) != 64 or any(ch not in "0123456789abcdefABCDEF" for ch in expected_identity):
        raise ReplayArtifactError("expected replay identity must be 64 hex characters")
    restore_matching_artifact(
        repository=args.repository,
        token=args.token,
        output_dir=args.output_dir,
        expected_file_name=args.expected_file_name,
        expected_sha256=args.expected_sha256,
        expected_semantic_sha256=args.expected_semantic_sha256,
        delivery_name=args.delivery_name,
        prefix=args.artifact_prefix,
        max_candidates=args.max_candidates,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
