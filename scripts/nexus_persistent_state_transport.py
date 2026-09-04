"""Read-only GitHub Actions artifact restore for persistent NEXUS Paper state.

The physical runtime state is authoritative on the external runner path. This
helper is only a bounded recovery/seed transport. It never writes GitHub state,
forwards the GitHub bearer token to signed object storage, or touches Live/secret
exchange authority.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any


API_ROOT = "https://api.github.com"
MAX_ARTIFACT_BYTES = 100_000_000
MAX_FILES = 20_000


class PersistentStateTransportError(RuntimeError):
    pass


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _headers(token: str) -> dict[str, str]:
    if not token:
        raise PersistentStateTransportError("GH_TOKEN is required")
    return {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "nexus-persistent-paper-state-restore",
    }


def _safe_members(archive: zipfile.ZipFile) -> list[zipfile.ZipInfo]:
    members = archive.infolist()
    if len(members) > MAX_FILES:
        raise PersistentStateTransportError("state artifact file count exceeds bound")
    total = 0
    for member in members:
        pure = PurePosixPath(member.filename)
        if (
            pure.is_absolute()
            or not pure.parts
            or any(part in {"", ".", ".."} for part in pure.parts)
            or member.filename.endswith("/") and member.file_size != 0
        ):
            raise PersistentStateTransportError(f"unsafe state artifact path: {member.filename}")
        mode = (member.external_attr >> 16) & 0o170000
        if mode == 0o120000:
            raise PersistentStateTransportError("state artifact symlink is forbidden")
        total += member.file_size
        if total > MAX_ARTIFACT_BYTES:
            raise PersistentStateTransportError("state artifact expanded size exceeds bound")
    return members


def _request_json(url: str, *, token: str) -> dict[str, Any]:
    with urllib.request.urlopen(
        urllib.request.Request(url, headers=_headers(token)), timeout=60
    ) as response:
        if response.status != 200:
            raise PersistentStateTransportError(
                f"GitHub artifact list returned {response.status}"
            )
        value = json.load(response)
    if not isinstance(value, dict):
        raise PersistentStateTransportError("GitHub artifact list is not an object")
    return value


def _download_artifact(
    repository: str,
    artifact_id: int,
    *,
    token: str,
    destination: Path,
) -> None:
    api_url = f"{API_ROOT}/repos/{repository}/actions/artifacts/{artifact_id}/zip"
    opener = urllib.request.build_opener(NoRedirect)
    try:
        with opener.open(
            urllib.request.Request(api_url, headers=_headers(token)), timeout=60
        ) as response:
            location = response.headers.get("Location")
            if response.status == 200:
                with destination.open("wb") as output:
                    shutil.copyfileobj(response, output)
                return
            if not location:
                raise PersistentStateTransportError(
                    f"unexpected artifact response: {response.status}"
                )
    except urllib.error.HTTPError as exc:
        if exc.code not in (301, 302, 303, 307, 308):
            raise
        location = exc.headers.get("Location")
        if not location:
            raise PersistentStateTransportError("artifact redirect missing Location") from exc

    parsed = urllib.parse.urlparse(str(location))
    if parsed.scheme != "https" or not parsed.hostname:
        raise PersistentStateTransportError("artifact redirect must be absolute HTTPS")
    request = urllib.request.Request(
        str(location),
        headers={"User-Agent": "nexus-persistent-paper-state-restore"},
    )
    with urllib.request.urlopen(request, timeout=120) as response, destination.open("wb") as output:
        length = response.headers.get("Content-Length")
        if length is not None and int(length) > MAX_ARTIFACT_BYTES:
            raise PersistentStateTransportError("state artifact download exceeds bound")
        shutil.copyfileobj(response, output, length=1024 * 1024)
    if destination.stat().st_size > MAX_ARTIFACT_BYTES:
        raise PersistentStateTransportError("state artifact download exceeds bound")


def restore_latest(
    *,
    repository: str,
    artifact_name: str,
    destination: str | Path,
    token: str,
    work_root: str | Path,
    only_if_empty: bool = True,
) -> dict[str, Any]:
    if "/" not in repository or not artifact_name:
        raise PersistentStateTransportError("repository/artifact identity is invalid")
    root = Path(destination).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    if only_if_empty and any(root.iterdir()):
        return {"decision": "skip", "reason": "external_state_already_present", "artifact_id": None}

    query = urllib.parse.urlencode({"name": artifact_name, "per_page": 10})
    payload = _request_json(
        f"{API_ROOT}/repos/{repository}/actions/artifacts?{query}", token=token
    )
    rows = payload.get("artifacts")
    if not isinstance(rows, list):
        raise PersistentStateTransportError("GitHub artifact list omitted artifacts")
    eligible = [
        row for row in rows
        if isinstance(row, dict)
        and row.get("name") == artifact_name
        and row.get("expired") is False
        and isinstance(row.get("id"), int)
    ]
    if not eligible:
        return {"decision": "skip", "reason": "no_prior_state_artifact", "artifact_id": None}
    artifact = eligible[0]

    work = Path(work_root).expanduser().resolve()
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True, exist_ok=True)
    archive_path = work / "persistent-state.zip"
    extract = work / "extract"
    extract.mkdir()
    _download_artifact(
        repository,
        int(artifact["id"]),
        token=token,
        destination=archive_path,
    )
    try:
        with zipfile.ZipFile(archive_path) as archive:
            members = _safe_members(archive)
            for member in members:
                archive.extract(member, extract)
    except (OSError, zipfile.BadZipFile) as exc:
        raise PersistentStateTransportError("persistent state artifact is not a valid ZIP") from exc

    if any(root.iterdir()):
        raise PersistentStateTransportError("external state changed during restore")
    for source in sorted(extract.iterdir()):
        os.replace(source, root / source.name)
    return {
        "decision": "pass",
        "reason": "restored_latest_backup",
        "artifact_id": int(artifact["id"]),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    restore = sub.add_parser("restore-latest")
    restore.add_argument("--repository", required=True)
    restore.add_argument("--artifact-name", required=True)
    restore.add_argument("--destination", type=Path, required=True)
    restore.add_argument("--work-root", type=Path, required=True)
    restore.add_argument("--token", default=os.environ.get("GH_TOKEN", ""))
    restore.add_argument("--allow-nonempty", action="store_true")
    args = parser.parse_args()
    result = restore_latest(
        repository=args.repository,
        artifact_name=args.artifact_name,
        destination=args.destination,
        token=args.token,
        work_root=args.work_root,
        only_if_empty=not args.allow_nonempty,
    )
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
