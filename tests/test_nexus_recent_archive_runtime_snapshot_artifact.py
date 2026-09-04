from __future__ import annotations

import hashlib
import json
import shutil
import zipfile
from pathlib import Path

import pytest

import nexus_multipair_recent_archive_runtime_snapshot as recent
from nexus_multipair_trusted_surface import SYMBOLS, TIMEFRAMES
from scripts import nexus_recent_archive_runtime_snapshot_artifact as artifact


SOURCE_SHA = "9" * 40
ACQUIRED_MS = 1_788_432_000_000
DATA_AS_OF_MS = ACQUIRED_MS - 12 * 60 * 60 * 1000
SNAPSHOT_DIGEST = "a" * 64


def _manifest() -> dict:
    return {
        "schema_version": recent.SCHEMA,
        "source_sha": SOURCE_SHA,
        "snapshot_digest": SNAPSHOT_DIGEST,
        "as_of_ms": ACQUIRED_MS,
        "acquired_at_ms": ACQUIRED_MS,
        "data_as_of_ms": DATA_AS_OF_MS,
        "latest_common_complete_date": "2026-09-02",
        "history_limit": recent.HISTORY_LIMIT,
        "cell_count": 12,
        "symbols": list(SYMBOLS),
        "timeframes": list(TIMEFRAMES),
        "data_origin": recent.DATA_ORIGIN,
        "runtime_requalification_recency_verified": True,
        "live_freshness_claimed": False,
    }


def _regular_member(name: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_STORED
    info.create_system = 3
    info.external_attr = 0o100644 << 16
    return info


def _inner(tmp_path: Path) -> tuple[Path, str]:
    path = tmp_path / artifact.INNER_ARCHIVE_NAME
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_STORED) as archive:
        archive.writestr(_regular_member("snapshot-manifest.json"), json.dumps(_manifest()))
        for symbol in SYMBOLS:
            for timeframe in TIMEFRAMES:
                archive.writestr(_regular_member(f"bybit_market/{symbol}/{timeframe}.parquet"), b"x")
    return path, hashlib.sha256(path.read_bytes()).hexdigest()


def _outer(path: Path, inner: Path, *, name: str | None = None) -> Path:
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_STORED) as archive:
        archive.writestr(_regular_member(name or artifact.INNER_ARCHIVE_NAME), inner.read_bytes())
    return path


def test_recent_archive_manifest_uses_bounded_recency_not_live_freshness(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "snapshot"
    root.mkdir()
    (root / "snapshot-manifest.json").write_text(json.dumps(_manifest()), encoding="utf-8")
    monkeypatch.setattr(
        artifact.recent,
        "verify_recent_archive_runtime_snapshot",
        lambda *args, **kwargs: {"decision": "pass"},
    )
    value = artifact._validate_manifest(
        root,
        source_sha=SOURCE_SHA,
        snapshot_digest=SNAPSHOT_DIGEST,
        expected_acquired_at_ms=ACQUIRED_MS,
        expected_data_as_of_ms=DATA_AS_OF_MS,
        now_ms=ACQUIRED_MS + 5 * 60 * 1000,
    )
    assert value["runtime_requalification_recency_verified"] is True
    assert value["live_freshness_claimed"] is False
    assert value["data_origin"] == recent.DATA_ORIGIN


def test_recent_archive_manifest_rejects_live_freshness_claim(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "snapshot"
    root.mkdir()
    value = _manifest()
    value["live_freshness_claimed"] = True
    (root / "snapshot-manifest.json").write_text(json.dumps(value), encoding="utf-8")
    monkeypatch.setattr(
        artifact.recent,
        "verify_recent_archive_runtime_snapshot",
        lambda *args, **kwargs: {"decision": "pass"},
    )
    with pytest.raises(RuntimeError, match="identity contract"):
        artifact._validate_manifest(
            root,
            source_sha=SOURCE_SHA,
            snapshot_digest=SNAPSHOT_DIGEST,
            expected_acquired_at_ms=ACQUIRED_MS,
            expected_data_as_of_ms=DATA_AS_OF_MS,
            now_ms=ACQUIRED_MS,
        )


def test_recent_archive_outer_requires_exact_inner_name(tmp_path: Path) -> None:
    inner, _sha = _inner(tmp_path)
    outer = _outer(tmp_path / "outer.zip", inner, name="wrong.zip")
    work = tmp_path / "work"
    work.mkdir()
    with pytest.raises(RuntimeError, match="exactly one deterministic inner archive"):
        artifact._extract_outer(outer, work)


def test_current_run_restore_checks_identity_digest_and_recent_archive_contract(tmp_path: Path, monkeypatch) -> None:
    inner, inner_sha = _inner(tmp_path)
    outer = _outer(tmp_path / "outer.zip", inner)
    artifact_name = f"recent-runtime-{SOURCE_SHA}"

    def fake_json_get(url, headers):
        del headers
        if "/actions/runs/123/artifacts?" in url:
            return {
                "artifacts": [{
                    "id": 88,
                    "name": artifact_name,
                    "expired": False,
                    "size_in_bytes": outer.stat().st_size,
                }]
            }
        if url.endswith("/actions/runs/123"):
            return {"id": 123, "head_sha": SOURCE_SHA, "head_branch": "main", "event": "push"}
        raise AssertionError(url)

    def fake_download(url, headers, output, *, expected_size):
        del url, headers
        assert expected_size == outer.stat().st_size
        shutil.copyfile(outer, output)

    monkeypatch.setattr(artifact.base, "_json_get", fake_json_get)
    monkeypatch.setattr(artifact.base, "_download", fake_download)
    monkeypatch.setattr(
        artifact.recent,
        "verify_recent_archive_runtime_snapshot",
        lambda *args, **kwargs: {"decision": "pass"},
    )
    result = artifact.restore_current_run_recent_archive_runtime_snapshot(
        repository="owner/repo",
        run_id="123",
        token="token",
        artifact_name=artifact_name,
        expected_sha256=inner_sha,
        expected_source_sha=SOURCE_SHA,
        expected_snapshot_digest=SNAPSHOT_DIGEST,
        expected_acquired_at_ms=ACQUIRED_MS,
        expected_data_as_of_ms=DATA_AS_OF_MS,
        now_ms=ACQUIRED_MS + 5 * 60 * 1000,
        destination=tmp_path / "destination",
        work_root=tmp_path / "restore-work",
    )
    assert result["artifact_id"] == 88
    assert result["archive_sha256"] == inner_sha
    assert result["snapshot_digest"] == SNAPSHOT_DIGEST
    assert result["snapshot_data_as_of_ms"] == DATA_AS_OF_MS
    assert result["live_freshness_claimed"] is False
