from __future__ import annotations

import copy
import hashlib
import json
from datetime import datetime, timedelta
from typing import Any, Mapping

import project_memory_backup as core


GOOGLE_DOCS_EXPORT_ADAPTER_VERSION = "nexus.project-memory-google-docs-export.v1"


class DriveExportVerificationError(core.BackupVerificationError):
    pass


def normalize_google_docs_text_export(raw_export_text: str) -> str:
    """Return the JSON text represented by a Google Docs text/plain export.

    Google Docs may prefix text/plain exports with a single UTF-8 BOM. The raw
    provider bytes remain authoritative for digest/size binding; this helper is
    used only for JSON interpretation. CRLF is intentionally preserved because
    it is valid JSON whitespace and is part of the raw content digest.
    """
    if not isinstance(raw_export_text, str):
        raise DriveExportVerificationError("drive_export: text_required")
    if raw_export_text.startswith("\ufeff"):
        return raw_export_text[1:]
    return raw_export_text


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _snapshot_source_bytes(normalized_text: str) -> int:
    try:
        snapshot = json.loads(normalized_text)
    except json.JSONDecodeError as exc:
        raise DriveExportVerificationError("document: invalid_json") from exc
    files = snapshot.get("files") if isinstance(snapshot, Mapping) else None
    if not isinstance(files, Mapping):
        raise DriveExportVerificationError("document: invalid_files")
    total = 0
    for value in files.values():
        if not isinstance(value, str):
            raise DriveExportVerificationError("document: non_text_file")
        total += len(value.encode("utf-8"))
    return total


def build_drive_export_manifest(
    *,
    repository: str,
    source_sha: str,
    generated_at: datetime,
    provider_object_id: str,
    provider_revision_id: str,
    provider_name: str,
    provider_modified_at: datetime,
    raw_export_text: str,
) -> dict[str, Any]:
    normalized = normalize_google_docs_text_export(raw_export_text)
    manifest = core.build_manifest(
        repository=repository,
        source_sha=source_sha,
        generated_at=generated_at,
        provider_object_id=provider_object_id,
        provider_revision_id=provider_revision_id,
        provider_name=provider_name,
        provider_modified_at=provider_modified_at,
        document_text=normalized,
    )
    raw_bytes = raw_export_text.encode("utf-8")
    source_bytes = _snapshot_source_bytes(normalized)
    findings = sorted(set(manifest["privacy"]["forbidden_findings"] + core.privacy_findings(raw_export_text)))
    manifest["document"]["content_sha256"] = hashlib.sha256(raw_bytes).hexdigest()
    manifest["document"]["size_bytes"] = len(raw_bytes)
    manifest["privacy"]["scanned_bytes"] = len(raw_bytes) + source_bytes
    manifest["privacy"]["forbidden_findings"] = findings
    return manifest


def validate_drive_export_manifest(
    manifest: Mapping[str, Any],
    *,
    raw_export_text: str,
    expected_repository: str,
    expected_source_sha: str,
    expected_object_id: str,
    expected_revision_id: str,
    expected_document_name: str,
    now: datetime | None = None,
    max_age: timedelta = core.DEFAULT_MAX_AGE,
) -> dict[str, Any]:
    normalized = normalize_google_docs_text_export(raw_export_text)
    document = manifest.get("document") if isinstance(manifest, Mapping) else None
    if not isinstance(document, Mapping):
        raise DriveExportVerificationError("document: unknown_or_missing_metadata")
    raw_bytes = raw_export_text.encode("utf-8")
    raw_digest = hashlib.sha256(raw_bytes).hexdigest()
    if document.get("size_bytes") != len(raw_bytes):
        raise DriveExportVerificationError("document: size_mismatch")
    if document.get("content_sha256") != raw_digest:
        raise DriveExportVerificationError("document: content_hash_mismatch")

    source_bytes = _snapshot_source_bytes(normalized)
    privacy = manifest.get("privacy")
    if not isinstance(privacy, Mapping):
        raise DriveExportVerificationError("privacy: unknown_or_missing_fields")
    if privacy.get("scanned_bytes") != len(raw_bytes) + source_bytes:
        raise DriveExportVerificationError("privacy: scan_size_mismatch")
    raw_findings = core.privacy_findings(raw_export_text)
    if raw_findings:
        raise DriveExportVerificationError("privacy: forbidden_content")

    normalized_manifest = copy.deepcopy(dict(manifest))
    normalized_bytes = normalized.encode("utf-8")
    normalized_manifest["document"]["content_sha256"] = hashlib.sha256(normalized_bytes).hexdigest()
    normalized_manifest["document"]["size_bytes"] = len(normalized_bytes)
    normalized_manifest["privacy"]["scanned_bytes"] = len(normalized_bytes) + source_bytes

    result = core.validate_manifest(
        normalized_manifest,
        document_text=normalized,
        expected_repository=expected_repository,
        expected_source_sha=expected_source_sha,
        expected_object_id=expected_object_id,
        expected_revision_id=expected_revision_id,
        expected_document_name=expected_document_name,
        now=now,
        max_age=max_age,
    )
    result["adapter_version"] = GOOGLE_DOCS_EXPORT_ADAPTER_VERSION
    result["document_content_sha256"] = raw_digest
    result["document_size_bytes"] = len(raw_bytes)
    result["manifest_digest"] = core.manifest_digest(manifest)
    result["provider_export_bom"] = raw_export_text.startswith("\ufeff")
    return result
