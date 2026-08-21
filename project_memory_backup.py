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


SCHEMA_VERSION = "nexus.project-memory-backup-manifest.v1"
PRIVACY_POLICY_VERSION = "nexus.project-memory-backup-privacy.v1"
DEFAULT_MAX_AGE = timedelta(hours=24)
DEFAULT_FUTURE_SKEW = timedelta(minutes=5)
MAX_DOCUMENT_BYTES = 2_000_000
MAX_SOURCE_FILES = 64

_ALLOWED_TOP_LEVEL = {
    "schema_version",
    "repository",
    "source_sha",
    "generated_at",
    "provider",
    "document",
    "source_files",
    "aggregate_source_digest",
    "privacy",
}
_ALLOWED_DOCUMENT = {
    "object_id",
    "revision_id",
    "name",
    "modified_at",
    "content_sha256",
    "size_bytes",
}
_ALLOWED_PRIVACY = {"policy_version", "scanned_bytes", "forbidden_findings"}
_ALLOWED_SOURCE_FILE = {"path", "size_bytes", "sha256"}

_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_SECRET_PATTERNS = (
    ("private_key", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")),
    ("github_token", re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b")),
    ("aws_access_key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("openai_style_key", re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b")),
    (
        "credential_assignment",
        re.compile(
            r"(?i)\b(?:password|passwd|api[_-]?key|access[_-]?token|client[_-]?secret)\s*[:=]\s*[\"']?[^\s\"']{8,}"
        ),
    ),
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
    except Exception as exc:  # pragma: no cover - exact parser error is irrelevant to policy
        raise BackupVerificationError(f"{field}: invalid_timestamp") from exc
    if parsed.tzinfo is None:
        raise BackupVerificationError(f"{field}: timezone_required")
    return parsed.astimezone(timezone.utc)


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_manifest_bytes(manifest: Mapping[str, Any]) -> bytes:
    return json.dumps(manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def manifest_digest(manifest: Mapping[str, Any]) -> str:
    return _sha256_bytes(canonical_manifest_bytes(manifest))


def _canonical_path(value: str) -> str:
    if not isinstance(value, str) or not value or "\\" in value:
        raise BackupVerificationError("source_files.path: noncanonical")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise BackupVerificationError("source_files.path: escape_or_noncanonical")
    normalized = path.as_posix()
    if normalized != value:
        raise BackupVerificationError("source_files.path: noncanonical")
    return normalized


def privacy_findings(text: str) -> list[str]:
    findings: list[str] = []
    for name, pattern in _SECRET_PATTERNS:
        if pattern.search(text):
            findings.append(name)
    for marker in _TRANSCRIPT_MARKERS:
        if marker in text:
            findings.append("private_transcript_marker")
            break
    return sorted(set(findings))


def build_source_records(source_files: Mapping[str, bytes | str]) -> tuple[list[dict[str, Any]], str]:
    if not source_files or len(source_files) > MAX_SOURCE_FILES:
        raise BackupVerificationError("source_files: invalid_count")
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    aggregate = hashlib.sha256()
    for raw_path in sorted(source_files):
        path = _canonical_path(raw_path)
        if path in seen:
            raise BackupVerificationError("source_files: duplicate_path")
        seen.add(path)
        value = source_files[raw_path]
        data = value.encode("utf-8") if isinstance(value, str) else bytes(value)
        digest = _sha256_bytes(data)
        row = {"path": path, "size_bytes": len(data), "sha256": digest}
        rows.append(row)
        aggregate.update(f"{path}\0{len(data)}\0{digest}\n".encode("utf-8"))
    return rows, aggregate.hexdigest()


def build_manifest(
    *,
    repository: str,
    source_sha: str,
    generated_at: datetime,
    provider_object_id: str,
    provider_revision_id: str,
    provider_name: str,
    provider_modified_at: datetime,
    document_text: str,
    source_files: Mapping[str, bytes | str],
) -> dict[str, Any]:
    document_bytes = document_text.encode("utf-8")
    if len(document_bytes) > MAX_DOCUMENT_BYTES:
        raise BackupVerificationError("document: too_large")
    findings = privacy_findings(document_text)
    for value in source_files.values():
        source_text = value if isinstance(value, str) else bytes(value).decode("utf-8", errors="replace")
        findings.extend(privacy_findings(source_text))
    findings = sorted(set(findings))
    rows, aggregate = build_source_records(source_files)
    return {
        "schema_version": SCHEMA_VERSION,
        "repository": repository,
        "source_sha": source_sha,
        "generated_at": generated_at.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        "provider": "google_drive",
        "document": {
            "object_id": provider_object_id,
            "revision_id": provider_revision_id,
            "name": provider_name,
            "modified_at": provider_modified_at.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
            "content_sha256": _sha256_bytes(document_bytes),
            "size_bytes": len(document_bytes),
        },
        "source_files": rows,
        "aggregate_source_digest": aggregate,
        "privacy": {
            "policy_version": PRIVACY_POLICY_VERSION,
            "scanned_bytes": len(document_bytes)
            + sum(len(v.encode("utf-8") if isinstance(v, str) else bytes(v)) for v in source_files.values()),
            "forbidden_findings": findings,
        },
    }


def validate_manifest(
    manifest: Mapping[str, Any],
    *,
    document_text: str,
    expected_repository: str,
    expected_source_sha: str,
    expected_object_id: str,
    expected_revision_id: str,
    expected_document_name: str,
    now: datetime | None = None,
    max_age: timedelta = DEFAULT_MAX_AGE,
) -> dict[str, Any]:
    if set(manifest) != _ALLOWED_TOP_LEVEL:
        raise BackupVerificationError("manifest: unknown_or_missing_fields")
    if manifest.get("schema_version") != SCHEMA_VERSION:
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
    if not isinstance(document, Mapping) or set(document) != _ALLOWED_DOCUMENT:
        raise BackupVerificationError("document: unknown_or_missing_fields")
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
    if not isinstance(digest, str) or not _HEX64.fullmatch(digest):
        raise BackupVerificationError("document: invalid_digest")
    if digest != _sha256_bytes(document_bytes):
        raise BackupVerificationError("document: content_hash_mismatch")

    source_files = manifest.get("source_files")
    if not isinstance(source_files, list) or not source_files or len(source_files) > MAX_SOURCE_FILES:
        raise BackupVerificationError("source_files: invalid_count")
    seen: set[str] = set()
    aggregate = hashlib.sha256()
    for row in source_files:
        if not isinstance(row, Mapping) or set(row) != _ALLOWED_SOURCE_FILE:
            raise BackupVerificationError("source_files: unknown_or_missing_fields")
        path = _canonical_path(row.get("path"))
        if path in seen:
            raise BackupVerificationError("source_files: duplicate_path")
        seen.add(path)
        size = row.get("size_bytes")
        digest = row.get("sha256")
        if not isinstance(size, int) or size < 0:
            raise BackupVerificationError("source_files: invalid_size")
        if not isinstance(digest, str) or not _HEX64.fullmatch(digest):
            raise BackupVerificationError("source_files: invalid_digest")
        aggregate.update(f"{path}\0{size}\0{digest}\n".encode("utf-8"))
    aggregate_value = manifest.get("aggregate_source_digest")
    if not isinstance(aggregate_value, str) or not _HEX64.fullmatch(aggregate_value):
        raise BackupVerificationError("manifest: invalid_aggregate_digest")
    if aggregate.hexdigest() != aggregate_value:
        raise BackupVerificationError("manifest: aggregate_digest_mismatch")

    privacy = manifest.get("privacy")
    if not isinstance(privacy, Mapping) or set(privacy) != _ALLOWED_PRIVACY:
        raise BackupVerificationError("privacy: unknown_or_missing_fields")
    if privacy.get("policy_version") != PRIVACY_POLICY_VERSION:
        raise BackupVerificationError("privacy: policy_mismatch")
    if not isinstance(privacy.get("scanned_bytes"), int) or privacy["scanned_bytes"] < len(document_bytes):
        raise BackupVerificationError("privacy: invalid_scan_size")
    findings = privacy.get("forbidden_findings")
    if findings != []:
        raise BackupVerificationError("privacy: forbidden_content")
    if privacy_findings(document_text):
        raise BackupVerificationError("privacy: document_scan_failed")

    return {
        "status": "VERIFIED",
        "schema_version": SCHEMA_VERSION,
        "repository": expected_repository,
        "source_sha": expected_source_sha,
        "provider_object_id": expected_object_id,
        "provider_revision_id": expected_revision_id,
        "document_content_sha256": _sha256_bytes(document_bytes),
        "manifest_digest": manifest_digest(manifest),
    }


def verify_and_promote_candidate(
    manifest: Mapping[str, Any],
    *,
    previous_valid_path: str | os.PathLike[str],
    document_text: str,
    expected_repository: str,
    expected_source_sha: str,
    expected_object_id: str,
    expected_revision_id: str,
    expected_document_name: str,
    now: datetime | None = None,
    max_age: timedelta = DEFAULT_MAX_AGE,
) -> dict[str, Any]:
    result = validate_manifest(
        manifest,
        document_text=document_text,
        expected_repository=expected_repository,
        expected_source_sha=expected_source_sha,
        expected_object_id=expected_object_id,
        expected_revision_id=expected_revision_id,
        expected_document_name=expected_document_name,
        now=now,
        max_age=max_age,
    )
    destination = Path(previous_valid_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload = canonical_manifest_bytes(manifest) + b"\n"
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
            manifest,
            document_text=document_text,
            expected_repository=args.repository,
            expected_source_sha=args.source_sha,
            expected_object_id=args.object_id,
            expected_revision_id=args.revision_id,
            expected_document_name=args.document_name,
            max_age=timedelta(hours=args.max_age_hours),
        )
    except (OSError, json.JSONDecodeError, BackupVerificationError) as exc:
        print(json.dumps({"status": "QUARANTINED", "reason": str(exc)}, sort_keys=True))
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
