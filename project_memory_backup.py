from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Mapping


MANIFEST_SCHEMA = "nexus.project-memory-backup-manifest.v1"
DOCUMENT_SCHEMA = "nexus.project-memory-backup-document.v1"
PRIVACY_POLICY_VERSION = "nexus.project-memory-backup-privacy.v1"
DEFAULT_MAX_AGE = timedelta(hours=24)
DEFAULT_FUTURE_SKEW = timedelta(minutes=5)
MAX_DOCUMENT_BYTES = 2_000_000
MAX_SOURCE_FILES = 64

_MANIFEST_KEYS = {
    "schema_version", "repository", "source_sha", "generated_at", "provider",
    "document", "source_files", "aggregate_source_digest", "privacy",
}
_DOCUMENT_META_KEYS = {"object_id", "revision_id", "name", "modified_at", "content_sha256", "size_bytes"}
_PRIVACY_KEYS = {"policy_version", "scanned_bytes", "forbidden_findings"}
_SOURCE_FILE_KEYS = {"path", "size_bytes", "sha256"}
_SNAPSHOT_KEYS = {"schema_version", "repository", "source_sha", "generated_at", "files"}

_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_SECRET_PATTERNS = (
    ("private_key", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")),
    ("github_token", re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b")),
    ("aws_access_key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("openai_style_key", re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b")),
    ("credential_assignment", re.compile(
        r"(?i)\b(?:password|passwd|api[_-]?key|access[_-]?token|client[_-]?secret)\s*[:=]\s*[\"']?[^\s\"']{8,}"
    )),
)
_TRANSCRIPT_MARKERS = (
    "User messages are delimited by",
    "Assistant messages are delimited by",
    "Project Conversation Content",
    "Recent Conversation Content",
    "# User Knowledge Memories",
)


class BackupVerificationError(ValueError):
    pass


def _parse_time(value: str, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception as exc:
        raise BackupVerificationError(f"{field}: invalid_timestamp") from exc
    if parsed.tzinfo is None:
        raise BackupVerificationError(f"{field}: timezone_required")
    return parsed.astimezone(timezone.utc)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_json_bytes(value: Mapping[str, Any]) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def manifest_digest(manifest: Mapping[str, Any]) -> str:
    return _sha256(canonical_json_bytes(manifest))


def _canonical_path(value: Any) -> str:
    if not isinstance(value, str) or not value or "\\" in value:
        raise BackupVerificationError("source_files.path: noncanonical")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts) or path.as_posix() != value:
        raise BackupVerificationError("source_files.path: escape_or_noncanonical")
    return value


def privacy_findings(text: str) -> list[str]:
    findings = [name for name, pattern in _SECRET_PATTERNS if pattern.search(text)]
    if any(marker in text for marker in _TRANSCRIPT_MARKERS):
        findings.append("private_transcript_marker")
    return sorted(set(findings))


def build_snapshot(*, repository: str, source_sha: str, generated_at: datetime, files: Mapping[str, str]) -> dict[str, Any]:
    if not _HEX40.fullmatch(source_sha):
        raise BackupVerificationError("snapshot: invalid_source_sha")
    if not files or len(files) > MAX_SOURCE_FILES:
        raise BackupVerificationError("snapshot: invalid_file_count")
    canonical_files: dict[str, str] = {}
    for raw_path in sorted(files):
        path = _canonical_path(raw_path)
        content = files[raw_path]
        if not isinstance(content, str):
            raise BackupVerificationError("snapshot: file_content_must_be_text")
        canonical_files[path] = content
    return {
        "schema_version": DOCUMENT_SCHEMA,
        "repository": repository,
        "source_sha": source_sha,
        "generated_at": generated_at.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        "files": canonical_files,
    }


def snapshot_text(snapshot: Mapping[str, Any]) -> str:
    return json.dumps(snapshot, sort_keys=True, indent=2, ensure_ascii=False) + "\n"


def _source_records(files: Mapping[str, str]) -> tuple[list[dict[str, Any]], str, list[str], int]:
    if not files or len(files) > MAX_SOURCE_FILES:
        raise BackupVerificationError("source_files: invalid_count")
    rows: list[dict[str, Any]] = []
    aggregate = hashlib.sha256()
    findings: list[str] = []
    scanned = 0
    for raw_path in sorted(files):
        path = _canonical_path(raw_path)
        content = files[raw_path]
        if not isinstance(content, str):
            raise BackupVerificationError("source_files: non_text_content")
        data = content.encode("utf-8")
        digest = _sha256(data)
        rows.append({"path": path, "size_bytes": len(data), "sha256": digest})
        aggregate.update(f"{path}\0{len(data)}\0{digest}\n".encode("utf-8"))
        findings.extend(privacy_findings(content))
        scanned += len(data)
    return rows, aggregate.hexdigest(), sorted(set(findings)), scanned


def build_manifest(
    *, repository: str, source_sha: str, generated_at: datetime,
    provider_object_id: str, provider_revision_id: str, provider_name: str,
    provider_modified_at: datetime, document_text: str,
) -> dict[str, Any]:
    document_bytes = document_text.encode("utf-8")
    if len(document_bytes) > MAX_DOCUMENT_BYTES:
        raise BackupVerificationError("document: too_large")
    try:
        snapshot = json.loads(document_text)
    except json.JSONDecodeError as exc:
        raise BackupVerificationError("document: invalid_json") from exc
    _validate_snapshot_shape(snapshot, repository, source_sha)
    rows, aggregate, findings, source_scanned = _source_records(snapshot["files"])
    findings = sorted(set(findings + privacy_findings(document_text)))
    return {
        "schema_version": MANIFEST_SCHEMA,
        "repository": repository,
        "source_sha": source_sha,
        "generated_at": generated_at.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        "provider": "google_drive",
        "document": {
            "object_id": provider_object_id,
            "revision_id": provider_revision_id,
            "name": provider_name,
            "modified_at": provider_modified_at.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
            "content_sha256": _sha256(document_bytes),
            "size_bytes": len(document_bytes),
        },
        "source_files": rows,
        "aggregate_source_digest": aggregate,
        "privacy": {
            "policy_version": PRIVACY_POLICY_VERSION,
            "scanned_bytes": len(document_bytes) + source_scanned,
            "forbidden_findings": findings,
        },
    }


def _validate_snapshot_shape(snapshot: Any, repository: str, source_sha: str) -> None:
    if not isinstance(snapshot, Mapping) or set(snapshot) != _SNAPSHOT_KEYS:
        raise BackupVerificationError("document: unknown_or_missing_fields")
    if snapshot.get("schema_version") != DOCUMENT_SCHEMA:
        raise BackupVerificationError("document: unsupported_schema")
    if snapshot.get("repository") != repository:
        raise BackupVerificationError("document: repository_mismatch")
    if snapshot.get("source_sha") != source_sha:
        raise BackupVerificationError("document: source_sha_mismatch")
    _parse_time(str(snapshot.get("generated_at", "")), "document.generated_at")
    files = snapshot.get("files")
    if not isinstance(files, Mapping) or not files or len(files) > MAX_SOURCE_FILES:
        raise BackupVerificationError("document: invalid_files")
    for path, content in files.items():
        _canonical_path(path)
        if not isinstance(content, str):
            raise BackupVerificationError("document: non_text_file")


def validate_manifest(
    manifest: Mapping[str, Any], *, document_text: str,
    expected_repository: str, expected_source_sha: str,
    expected_object_id: str, expected_revision_id: str, expected_document_name: str,
    now: datetime | None = None, max_age: timedelta = DEFAULT_MAX_AGE,
) -> dict[str, Any]:
    if set(manifest) != _MANIFEST_KEYS:
        raise BackupVerificationError("manifest: unknown_or_missing_fields")
    if manifest.get("schema_version") != MANIFEST_SCHEMA:
        raise BackupVerificationError("manifest: unsupported_schema")
    if manifest.get("repository") != expected_repository:
        raise BackupVerificationError("manifest: repository_mismatch")
    source_sha = manifest.get("source_sha")
    if not isinstance(source_sha, str) or not _HEX40.fullmatch(source_sha):
        raise BackupVerificationError("manifest: invalid_source_sha")
    if source_sha != expected_source_sha:
        raise BackupVerificationError("manifest: source_sha_mismatch")
    if manifest.get("provider") != "google_drive":
        raise BackupVerificationError("manifest: provider_mismatch")

    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    generated = _parse_time(str(manifest.get("generated_at", "")), "generated_at")
    if generated > current + DEFAULT_FUTURE_SKEW:
        raise BackupVerificationError("manifest: future_timestamp")
    if current - generated > max_age:
        raise BackupVerificationError("manifest: stale")

    document = manifest.get("document")
    if not isinstance(document, Mapping) or set(document) != _DOCUMENT_META_KEYS:
        raise BackupVerificationError("document: unknown_or_missing_metadata")
    if document.get("object_id") != expected_object_id:
        raise BackupVerificationError("document: object_substitution")
    if document.get("revision_id") != expected_revision_id:
        raise BackupVerificationError("document: revision_substitution")
    if document.get("name") != expected_document_name:
        raise BackupVerificationError("document: name_substitution")
    modified = _parse_time(str(document.get("modified_at", "")), "document.modified_at")
    if modified > current + DEFAULT_FUTURE_SKEW:
        raise BackupVerificationError("document: future_modified_at")
    if modified > generated + DEFAULT_FUTURE_SKEW:
        raise BackupVerificationError("document: generated_before_provider_revision")

    document_bytes = document_text.encode("utf-8")
    if len(document_bytes) > MAX_DOCUMENT_BYTES:
        raise BackupVerificationError("document: too_large")
    if document.get("size_bytes") != len(document_bytes):
        raise BackupVerificationError("document: size_mismatch")
    digest = document.get("content_sha256")
    if not isinstance(digest, str) or not _HEX64.fullmatch(digest) or digest != _sha256(document_bytes):
        raise BackupVerificationError("document: content_hash_mismatch")

    try:
        snapshot = json.loads(document_text)
    except json.JSONDecodeError as exc:
        raise BackupVerificationError("document: invalid_json") from exc
    _validate_snapshot_shape(snapshot, expected_repository, expected_source_sha)
    snapshot_generated = _parse_time(snapshot["generated_at"], "document.generated_at")
    if snapshot_generated > generated + DEFAULT_FUTURE_SKEW:
        raise BackupVerificationError("document: snapshot_newer_than_manifest")

    expected_rows, expected_aggregate, actual_findings, source_scanned = _source_records(snapshot["files"])
    rows = manifest.get("source_files")
    if rows != expected_rows:
        raise BackupVerificationError("source_files: snapshot_binding_mismatch")
    if manifest.get("aggregate_source_digest") != expected_aggregate:
        raise BackupVerificationError("manifest: aggregate_digest_mismatch")

    privacy = manifest.get("privacy")
    if not isinstance(privacy, Mapping) or set(privacy) != _PRIVACY_KEYS:
        raise BackupVerificationError("privacy: unknown_or_missing_fields")
    if privacy.get("policy_version") != PRIVACY_POLICY_VERSION:
        raise BackupVerificationError("privacy: policy_mismatch")
    expected_scanned = len(document_bytes) + source_scanned
    if privacy.get("scanned_bytes") != expected_scanned:
        raise BackupVerificationError("privacy: scan_size_mismatch")
    actual_findings = sorted(set(actual_findings + privacy_findings(document_text)))
    if privacy.get("forbidden_findings") != actual_findings:
        raise BackupVerificationError("privacy: scan_result_mismatch")
    if actual_findings:
        raise BackupVerificationError("privacy: forbidden_content")

    return {
        "status": "VERIFIED",
        "schema_version": MANIFEST_SCHEMA,
        "repository": expected_repository,
        "source_sha": expected_source_sha,
        "provider_object_id": expected_object_id,
        "provider_revision_id": expected_revision_id,
        "document_content_sha256": _sha256(document_bytes),
        "manifest_digest": manifest_digest(manifest),
        "source_file_count": len(expected_rows),
    }


def verify_and_promote_candidate(
    manifest: Mapping[str, Any], *, previous_valid_path: str | os.PathLike[str],
    document_text: str, expected_repository: str, expected_source_sha: str,
    expected_object_id: str, expected_revision_id: str, expected_document_name: str,
    now: datetime | None = None, max_age: timedelta = DEFAULT_MAX_AGE,
) -> dict[str, Any]:
    result = validate_manifest(
        manifest, document_text=document_text, expected_repository=expected_repository,
        expected_source_sha=expected_source_sha, expected_object_id=expected_object_id,
        expected_revision_id=expected_revision_id, expected_document_name=expected_document_name,
        now=now, max_age=max_age,
    )
    destination = Path(previous_valid_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload = canonical_json_bytes(manifest) + b"\n"
    fd, tmp_name = tempfile.mkstemp(prefix=destination.name + ".", suffix=".tmp", dir=str(destination.parent))
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, destination)
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)
    return result


def _cli() -> int:
    parser = argparse.ArgumentParser(description="Fail-closed verifier for NEXUS Project Memory Drive backups")
    parser.add_argument("manifest")
    parser.add_argument("document")
    parser.add_argument("--repository", required=True)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--object-id", required=True)
    parser.add_argument("--revision-id", required=True)
    parser.add_argument("--document-name", required=True)
    parser.add_argument("--max-age-hours", type=float, default=24.0)
    args = parser.parse_args()
    try:
        manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
        document_text = Path(args.document).read_text(encoding="utf-8")
        result = validate_manifest(
            manifest, document_text=document_text, expected_repository=args.repository,
            expected_source_sha=args.source_sha, expected_object_id=args.object_id,
            expected_revision_id=args.revision_id, expected_document_name=args.document_name,
            max_age=timedelta(hours=args.max_age_hours),
        )
    except (OSError, json.JSONDecodeError, BackupVerificationError) as exc:
        print(json.dumps({"status": "QUARANTINED", "reason": str(exc)}, sort_keys=True))
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
