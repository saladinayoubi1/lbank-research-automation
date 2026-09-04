from __future__ import annotations

import math
import shutil
import zipfile
from pathlib import Path

import pytest

from phase6_research_pipeline import bind_bybit_closed_dataset
import nexus_multipair_runtime_requalification_snapshot as runtime
from scripts import nexus_runtime_snapshot_artifact as artifact


SOURCE_SHA = "a" * 40
NOW_MS = 1_800_000_000_000
STEP = {"15": 900_000, "60": 3_600_000, "240": 14_400_000}


def _fake_fetcher(**kwargs):
    interval = str(kwargs["interval"])
    source_symbol = str(kwargs["source_symbol"])
    canonical_symbol = str(kwargs["canonical_symbol"])
    start = int(kwargs["start_time_ms"])
    end = int(kwargs["end_time_ms"])
    limit = int(kwargs["limit"])
    step = STEP[interval]
    opens = list(range(start, end + 1, step))
    assert len(opens) == limit
    base = {"BTCUSDT": 40_000.0, "ETHUSDT": 2_000.0, "SOLUSDT": 100.0, "XRPUSDT": 0.5}[source_symbol]
    candles = []
    for index, open_ms in enumerate(opens):
        close = base * (1.0 + 0.0005 * index + 0.005 * math.sin(index / 9.0))
        candles.append({
            "source": "Bybit",
            "market_type": "spot",
            "symbol": source_symbol,
            "interval": interval,
            "open_time_ms": open_ms,
            "open": str(close * 0.999),
            "high": str(close * 1.002),
            "low": str(close * 0.998),
            "close": str(close),
            "volume": str(1000 + index),
            "closed": True,
        })
    return bind_bybit_closed_dataset(
        candles,
        canonical_symbol=canonical_symbol,
        source_symbol=source_symbol,
        interval=interval,
    )


def _snapshot(tmp_path: Path):
    root = tmp_path / "snapshot"
    value = runtime.collect_fresh_runtime_snapshot(
        output_root=root,
        source_sha=SOURCE_SHA,
        now_ms=NOW_MS,
        fetcher=_fake_fetcher,
    )
    inner = tmp_path / artifact.INNER_ARCHIVE_NAME
    inner_sha = runtime.deterministic_pack(root, inner)
    return root, value, inner, inner_sha


def _outer(path: Path, inner: Path, *, name: str | None = None) -> Path:
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_STORED) as archive:
        info = zipfile.ZipInfo(name or artifact.INNER_ARCHIVE_NAME, date_time=(1980, 1, 1, 0, 0, 0))
        info.compress_type = zipfile.ZIP_STORED
        info.create_system = 3
        info.external_attr = 0o100644 << 16
        archive.writestr(info, inner.read_bytes())
    return path


def test_runtime_snapshot_outer_extracts_and_fresh_manifest_passes(tmp_path: Path) -> None:
    _root, value, inner, _sha = _snapshot(tmp_path)
    outer = _outer(tmp_path / "outer.zip", inner)
    work = tmp_path / "work"
    work.mkdir()
    extracted_inner = artifact._extract_outer(outer, work)
    destination = tmp_path / "restored"
    artifact.base._extract_inner(extracted_inner, destination)
    restored = artifact._validate_manifest(
        destination,
        source_sha=SOURCE_SHA,
        snapshot_digest=value["snapshot_digest"],
        expected_as_of_ms=NOW_MS,
        now_ms=NOW_MS,
    )
    assert restored["cell_count"] == 12
    assert restored["history_limit"] == 240


def test_runtime_snapshot_transport_rejects_stale_consumption(tmp_path: Path) -> None:
    root, value, _inner_path, _sha = _snapshot(tmp_path)
    with pytest.raises(RuntimeError, match="freshness or authority"):
        artifact._validate_manifest(
            root,
            source_sha=SOURCE_SHA,
            snapshot_digest=value["snapshot_digest"],
            expected_as_of_ms=NOW_MS,
            now_ms=NOW_MS + runtime.MAX_SNAPSHOT_TRANSPORT_AGE_MS + 1,
        )


def test_runtime_snapshot_outer_requires_exact_inner_name(tmp_path: Path) -> None:
    _root, _value, inner, _sha = _snapshot(tmp_path)
    outer = _outer(tmp_path / "wrong-outer.zip", inner, name="wrong.zip")
    work = tmp_path / "work"
    work.mkdir()
    with pytest.raises(RuntimeError, match="exactly one deterministic inner archive"):
        artifact._extract_outer(outer, work)


def test_current_run_restore_checks_identity_digest_and_freshness(tmp_path: Path, monkeypatch) -> None:
    _root, value, inner, inner_sha = _snapshot(tmp_path)
    outer = _outer(tmp_path / "outer.zip", inner)
    artifact_name = f"runtime-snapshot-{SOURCE_SHA}"

    def fake_json_get(url, headers):
        del headers
        if "/actions/runs/123/artifacts?" in url:
            return {
                "artifacts": [{
                    "id": 77,
                    "name": artifact_name,
                    "expired": False,
                    "size_in_bytes": outer.stat().st_size,
                }]
            }
        if url.endswith("/actions/runs/123"):
            return {
                "id": 123,
                "head_sha": SOURCE_SHA,
                "head_branch": "main",
                "event": "push",
            }
        raise AssertionError(url)

    def fake_download(url, headers, output, *, expected_size):
        del url, headers
        assert expected_size == outer.stat().st_size
        shutil.copyfile(outer, output)

    monkeypatch.setattr(artifact.base, "_json_get", fake_json_get)
    monkeypatch.setattr(artifact.base, "_download", fake_download)
    result = artifact.restore_current_run_runtime_snapshot(
        repository="owner/repo",
        run_id="123",
        token="token",
        artifact_name=artifact_name,
        expected_sha256=inner_sha,
        expected_source_sha=SOURCE_SHA,
        expected_snapshot_digest=value["snapshot_digest"],
        expected_as_of_ms=NOW_MS,
        now_ms=NOW_MS,
        destination=tmp_path / "destination",
        work_root=tmp_path / "restore-work",
    )
    assert result["artifact_id"] == 77
    assert result["archive_sha256"] == inner_sha
    assert result["snapshot_digest"] == value["snapshot_digest"]
    assert result["snapshot_as_of_ms"] == NOW_MS
    assert result["cell_count"] == 12
    assert result["history_limit"] == 240
