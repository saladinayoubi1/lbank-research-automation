import copy
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from project_memory_backup import (
    BackupVerificationError,
    build_manifest,
    build_snapshot,
    snapshot_text,
    validate_manifest,
    verify_and_promote_candidate,
)


NOW = datetime(2026, 8, 21, 13, 0, tzinfo=timezone.utc)
REPO = "saladinayoubi1/lbank-research-automation"
SHA = "7" * 40
OBJECT = "drive-object-123"
REVISION = "drive-revision-456"
NAME = "NEXUS Project Memory Backup — Durable"
FILES = {
    "docs/project_memory/PROJECT_MEMORY.md": "# NEXUS Project Memory\nResearch / Backtest / Paper only.\n",
    "docs/project_memory/STATE.json": '{"schema_version":3,"data_policy":{"real_trading":false}}\n',
}


def candidate(*, generated_at=NOW):
    snapshot = build_snapshot(
        repository=REPO,
        source_sha=SHA,
        generated_at=NOW - timedelta(minutes=2),
        files=FILES,
    )
    document = snapshot_text(snapshot)
    manifest = build_manifest(
        repository=REPO,
        source_sha=SHA,
        generated_at=generated_at,
        provider_object_id=OBJECT,
        provider_revision_id=REVISION,
        provider_name=NAME,
        provider_modified_at=NOW - timedelta(minutes=1),
        document_text=document,
    )
    return manifest, document


def verify(manifest, document):
    return validate_manifest(
        manifest,
        document_text=document,
        expected_repository=REPO,
        expected_source_sha=SHA,
        expected_object_id=OBJECT,
        expected_revision_id=REVISION,
        expected_document_name=NAME,
        now=NOW,
    )


def test_valid_content_bound_backup_passes():
    manifest, document = candidate()
    result = verify(manifest, document)
    assert result["status"] == "VERIFIED"
    assert result["source_file_count"] == 2
    assert len(result["manifest_digest"]) == 64


@pytest.mark.parametrize(
    ("mutator", "reason"),
    [
        (lambda m: m.update(schema_version="future.schema"), "unsupported_schema"),
        (lambda m: m.update(repository="other/repo"), "repository_mismatch"),
        (lambda m: m.update(source_sha="8" * 40), "source_sha_mismatch"),
        (lambda m: m["document"].update(object_id="substituted"), "object_substitution"),
        (lambda m: m["document"].update(revision_id="replayed"), "revision_substitution"),
        (lambda m: m["document"].update(name="wrong document"), "name_substitution"),
    ],
)
def test_identity_and_schema_substitution_fail_closed(mutator, reason):
    manifest, document = candidate()
    mutated = copy.deepcopy(manifest)
    mutator(mutated)
    with pytest.raises(BackupVerificationError, match=reason):
        verify(mutated, document)


def test_unknown_manifest_field_is_rejected():
    manifest, document = candidate()
    manifest["production_authorized"] = True
    with pytest.raises(BackupVerificationError, match="unknown_or_missing_fields"):
        verify(manifest, document)


def test_stale_and_future_manifest_are_rejected():
    stale, document = candidate(generated_at=NOW - timedelta(hours=25))
    with pytest.raises(BackupVerificationError, match="stale"):
        verify(stale, document)

    future, document = candidate(generated_at=NOW + timedelta(minutes=6))
    with pytest.raises(BackupVerificationError, match="future_timestamp"):
        verify(future, document)


def test_document_content_substitution_is_rejected():
    manifest, document = candidate()
    tampered = document.replace("Paper only", "LIVE ONLY!")
    with pytest.raises(BackupVerificationError, match="content_hash_mismatch"):
        verify(manifest, tampered)


def test_snapshot_file_hash_binding_rejects_poisoned_manifest_rows():
    manifest, document = candidate()
    manifest = copy.deepcopy(manifest)
    manifest["source_files"][0]["sha256"] = "0" * 64
    with pytest.raises(BackupVerificationError, match="snapshot_binding_mismatch"):
        verify(manifest, document)


def test_noncanonical_paths_are_rejected_before_manifest_creation():
    with pytest.raises(BackupVerificationError, match="escape_or_noncanonical"):
        build_snapshot(
            repository=REPO,
            source_sha=SHA,
            generated_at=NOW,
            files={"../private.txt": "nope"},
        )


def test_secret_like_source_content_is_scanned_not_trusted_from_boolean():
    snapshot = build_snapshot(
        repository=REPO,
        source_sha=SHA,
        generated_at=NOW - timedelta(minutes=2),
        files={"docs/project_memory/STATE.json": "api_key=abcdefghijklmno\n"},
    )
    document = snapshot_text(snapshot)
    manifest = build_manifest(
        repository=REPO,
        source_sha=SHA,
        generated_at=NOW,
        provider_object_id=OBJECT,
        provider_revision_id=REVISION,
        provider_name=NAME,
        provider_modified_at=NOW - timedelta(minutes=1),
        document_text=document,
    )
    assert "credential_assignment" in manifest["privacy"]["forbidden_findings"]
    with pytest.raises(BackupVerificationError, match="forbidden_content"):
        verify(manifest, document)


def test_private_transcript_markers_are_rejected():
    snapshot = build_snapshot(
        repository=REPO,
        source_sha=SHA,
        generated_at=NOW - timedelta(minutes=2),
        files={"docs/project_memory/PROJECT_MEMORY.md": "Project Conversation Content\nprivate chat dump\n"},
    )
    document = snapshot_text(snapshot)
    manifest = build_manifest(
        repository=REPO,
        source_sha=SHA,
        generated_at=NOW,
        provider_object_id=OBJECT,
        provider_revision_id=REVISION,
        provider_name=NAME,
        provider_modified_at=NOW - timedelta(minutes=1),
        document_text=document,
    )
    with pytest.raises(BackupVerificationError, match="forbidden_content"):
        verify(manifest, document)


def test_invalid_candidate_does_not_overwrite_previous_valid(tmp_path: Path):
    manifest, document = candidate()
    previous = tmp_path / "previous-valid.json"
    previous.write_text('{"known":"good"}\n', encoding="utf-8")
    before = previous.read_bytes()

    poisoned = copy.deepcopy(manifest)
    poisoned["document"]["revision_id"] = "replayed"
    with pytest.raises(BackupVerificationError):
        verify_and_promote_candidate(
            poisoned,
            previous_valid_path=previous,
            document_text=document,
            expected_repository=REPO,
            expected_source_sha=SHA,
            expected_object_id=OBJECT,
            expected_revision_id=REVISION,
            expected_document_name=NAME,
            now=NOW,
        )
    assert previous.read_bytes() == before


def test_valid_candidate_atomically_promotes_previous_valid(tmp_path: Path):
    manifest, document = candidate()
    previous = tmp_path / "previous-valid.json"
    result = verify_and_promote_candidate(
        manifest,
        previous_valid_path=previous,
        document_text=document,
        expected_repository=REPO,
        expected_source_sha=SHA,
        expected_object_id=OBJECT,
        expected_revision_id=REVISION,
        expected_document_name=NAME,
        now=NOW,
    )
    assert result["status"] == "VERIFIED"
    promoted = json.loads(previous.read_text(encoding="utf-8"))
    assert promoted["source_sha"] == SHA
