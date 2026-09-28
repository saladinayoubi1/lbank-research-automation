from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

import pytest

from phase5_data_binding import validate_canonical_dataset
from scripts.nexus_recent_archive_offline_export import export_historical
from test_nexus_multipair_recent_archive_runtime_snapshot import (
    _seed, SOURCE_SHA, ACQUIRED_MS, LATEST,
)
import nexus_multipair_recent_archive_runtime_snapshot as recent

EXPORT_SHA = "a" * 40


def _source(tmp_path: Path) -> tuple[Path, dict]:
    state, report = _seed(tmp_path)
    snapshot_root = tmp_path / "snapshot"
    manifest = recent.build_snapshot_from_backfill(
        state_root=state,
        output_root=snapshot_root,
        report=report,
        source_sha=SOURCE_SHA,
        acquired_at_ms=ACQUIRED_MS,
        latest_common_complete_date=LATEST,
    )
    archive = tmp_path / "verified.zip"
    recent.deterministic_pack(snapshot_root, archive)
    return archive, manifest


def _export(tmp_path: Path, archive: Path, manifest: dict, **kwargs) -> dict:
    params = {
        "archive": archive,
        "expected_archive_sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
        "expected_snapshot_digest": manifest["snapshot_digest"],
        "source_sha": SOURCE_SHA,
        "exporter_sha": EXPORT_SHA,
        "artifact_run_id": 36358344933,
        "artifact_id": 10945685213,
        "now_ms": ACQUIRED_MS + 24 * 60 * 60 * 1000,
        "output_root": tmp_path / "result",
    }
    params.update(kwargs)
    return export_historical(**params)


def test_12_canonical_verified_archive_datasets_are_explicit_historical(tmp_path: Path) -> None:
    archive, manifest = _source(tmp_path)
    result = _export(tmp_path, archive, manifest)
    assert result["decision"] == "historical_only_verified"
    assert result["count"] == 12
    assert result["live_freshness_claimed"] is False
    assert result["paper_execution_started"] is False
    exported = tmp_path / "result" / "offline-import.zip"
    assert exported.is_file()
    assert result["offline_archive_sha256"] == hashlib.sha256(exported.read_bytes()).hexdigest()
    with zipfile.ZipFile(exported) as package:
        assert len(package.namelist()) == 13
        receipt = json.loads(package.read("historical-receipt.json"))
        claimed = receipt.pop("receipt_sha256")
        from scripts.nexus_recent_archive_offline_export import _canonical
        assert hashlib.sha256(_canonical(receipt)).hexdigest() == claimed
        assert receipt["original_data_origin"] == recent.DATA_ORIGIN
        assert receipt["source_sha"] == SOURCE_SHA
        assert receipt["snapshot_digest"] == manifest["snapshot_digest"]
        assert receipt["data_as_of_ms"] == manifest["data_as_of_ms"]
        assert receipt["historical_only"] is True
        assert receipt["live_freshness_claimed"] is False
        assert receipt["automatic_paper_eligible"] is False
        assert receipt["paper_execution_started"] is False
        assert len({d["binding_sha256"] for d in receipt["datasets"]}) == 12
        for item in receipt["datasets"]:
            blob = package.read(item["filename"])
            assert hashlib.sha256(blob).hexdigest() == item["sha256"]
            dataset = validate_canonical_dataset(json.loads(blob))
            assert dataset["source"] == "Bybit"
            assert dataset["row_count"] == 240
            assert dataset["binding_sha256"] == item["binding_sha256"]


@pytest.mark.parametrize("field,bad", [
    ("expected_archive_sha256", "0" * 64),
    ("expected_snapshot_digest", "0" * 64),
    ("source_sha", "1" * 40),
    ("exporter_sha", "not_a_commit"),
    ("artifact_id", 0),
    ("now_ms", ACQUIRED_MS - 1),
])
def test_fails_closed_on_invalid_identity_and_clock(tmp_path: Path, field, bad) -> None:
    archive, manifest = _source(tmp_path)
    with pytest.raises(ValueError):
        _export(tmp_path, archive, manifest, **{field: bad})
    assert not (tmp_path / "result").exists()


def test_archive_with_extra_traversal_member_is_rejected_before_extraction(tmp_path: Path) -> None:
    archive, manifest = _source(tmp_path)
    with zipfile.ZipFile(archive, "a") as bad:
        bad.writestr("../unexpected-user-data.json", '{"forged":true}')
    with pytest.raises(ValueError, match="members"):
        _export(tmp_path, archive, manifest)
    assert not (tmp_path / "unexpected-user-data.json").exists()
    assert not (tmp_path / "result").exists()


def test_embedded_historical_authority_tamper_cannot_be_accepted(tmp_path: Path) -> None:
    archive, manifest = _source(tmp_path)
    tampered = tmp_path / "tampered.zip"
    with zipfile.ZipFile(archive) as input_zip, zipfile.ZipFile(tampered, "w") as output_zip:
        for item in input_zip.infolist():
            data = input_zip.read(item.filename)
            if item.filename == "snapshot-manifest.json":
                payload = json.loads(data)
                payload["live_freshness_claimed"] = True
                data = json.dumps(payload).encode()
            output_zip.writestr(item, data)
    with pytest.raises(ValueError, match="historical identity"):
        _export(
            tmp_path, tampered, manifest,
            expected_archive_sha256=hashlib.sha256(tampered.read_bytes()).hexdigest(),
        )
    assert not (tmp_path / "result").exists()


def test_original_archive_integrity_is_not_false_current_recency(tmp_path: Path) -> None:
    archive, manifest = _source(tmp_path)
    result = _export(
        tmp_path, archive, manifest,
        now_ms=ACQUIRED_MS + 40 * 24 * 60 * 60 * 1000,
    )
    assert result["decision"] == "historical_only_verified"
    with zipfile.ZipFile(tmp_path / "result" / "offline-import.zip") as package:
        receipt = json.loads(package.read("historical-receipt.json"))
    assert receipt["transport_age_ms"] == 40 * 24 * 60 * 60 * 1000
    assert receipt["historical_only"] is True
    assert receipt["live_freshness_claimed"] is False
    assert receipt["automatic_paper_eligible"] is False


def test_workflow_runs_exporter_as_repository_module() -> None:
    workflow = Path(".github/workflows/nexus_historical_offline_export.yml").read_text(encoding="utf-8")
    assert "python -m scripts.nexus_recent_archive_offline_export \\" in workflow
    assert "python scripts/nexus_recent_archive_offline_export.py \\" not in workflow
