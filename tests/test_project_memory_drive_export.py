from __future__ import annotations

import copy
from datetime import datetime, timedelta, timezone

import pytest

from project_memory_backup import build_snapshot, snapshot_text
from project_memory_drive_export import (
    DriveExportVerificationError,
    build_drive_export_manifest,
    normalize_google_docs_text_export,
    validate_drive_export_manifest,
)


NOW = datetime(2026, 8, 21, 13, 35, tzinfo=timezone.utc)
REPO = "saladinayoubi1/lbank-research-automation"
SHA = "b" * 40
OBJECT_ID = "drive-object"
REVISION_ID = "1"
NAME = "NEXUS Project Memory Backup — Durable"


def raw_export() -> str:
    snapshot = build_snapshot(
        repository=REPO,
        source_sha=SHA,
        generated_at=NOW - timedelta(minutes=3),
        files={
            "docs/project_memory/PROJECT_MEMORY.md": "# Memory\nPaper only.\n",
            "docs/project_memory/STATE.json": '{"real_trading":false}\n',
        },
    )
    canonical = snapshot_text(snapshot)
    return "\ufeff" + canonical.replace("\n", "\r\n")


def manifest_for(raw: str):
    return build_drive_export_manifest(
        repository=REPO,
        source_sha=SHA,
        generated_at=NOW,
        provider_object_id=OBJECT_ID,
        provider_revision_id=REVISION_ID,
        provider_name=NAME,
        provider_modified_at=NOW - timedelta(minutes=1),
        raw_export_text=raw,
    )


def verify(manifest, raw):
    return validate_drive_export_manifest(
        manifest,
        raw_export_text=raw,
        expected_repository=REPO,
        expected_source_sha=SHA,
        expected_object_id=OBJECT_ID,
        expected_revision_id=REVISION_ID,
        expected_document_name=NAME,
        now=NOW,
    )


def test_google_docs_bom_crlf_export_is_content_bound_and_verified():
    raw = raw_export()
    result = verify(manifest_for(raw), raw)
    assert result["status"] == "VERIFIED"
    assert result["provider_export_bom"] is True
    assert result["document_size_bytes"] == len(raw.encode("utf-8"))
    assert normalize_google_docs_text_export(raw).startswith("{")


def test_raw_provider_hash_is_not_normalized_away():
    raw = raw_export()
    manifest = manifest_for(raw)
    substituted = raw.replace("Paper only.", "Paper ONLY!")
    with pytest.raises(DriveExportVerificationError, match="content_hash_mismatch"):
        verify(manifest, substituted)


def test_provider_revision_substitution_still_fails_closed():
    raw = raw_export()
    manifest = manifest_for(raw)
    poisoned = copy.deepcopy(manifest)
    poisoned["document"]["revision_id"] = "2"
    with pytest.raises(Exception, match="revision_substitution"):
        verify(poisoned, raw)


def test_canonical_export_without_bom_remains_supported():
    raw = normalize_google_docs_text_export(raw_export())
    result = verify(manifest_for(raw), raw)
    assert result["status"] == "VERIFIED"
    assert result["provider_export_bom"] is False
