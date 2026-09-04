from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from scripts import nexus_snapshot_artifact as artifact


SOURCE_SHA = "a" * 40
SNAPSHOT_DIGEST = "b" * 64


def _manifest() -> dict:
    return {
        "schema_version": artifact.SCHEMA,
        "source_sha": SOURCE_SHA,
        "snapshot_digest": SNAPSHOT_DIGEST,
        "symbols": list(artifact.SYMBOLS),
        "timeframes": list(artifact.TIMEFRAMES),
        "archive_source_count": 12,
        "cell_count": 12,
        "history_limit": 500,
        "data_origin": "official_public_bybit_spot_trade_archive_aggregated",
        "runtime_freshness_claimed": False,
        "research_only": True,
        "paper_execution_started": False,
        "live_trading_authority": False,
        "private_credentials_used": False,
        "real_exchange_orders": False,
        "automatic_strategy_promotion": False,
        "silent_exchange_substitution": False,
        "third_party_proxy_used": False,
        "issue_984_state_touched": False,
        "persistent_runtime_database_on_github": False,
    }


def _write(archive: zipfile.ZipFile, name: str, data: str | bytes) -> None:
    info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_STORED
    info.create_system = 3
    info.external_attr = 0o100644 << 16
    archive.writestr(info, data)


def _inner(path: Path, *, extra: str | None = None, traversal: bool = False) -> Path:
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_STORED) as archive:
        _write(archive, artifact.MANIFEST_NAME, json.dumps(_manifest()))
        for name in sorted(artifact._expected_members() - {artifact.MANIFEST_NAME}):
            _write(archive, name, b"parquet-placeholder")
        if extra is not None:
            _write(archive, extra, b"unexpected")
        if traversal:
            _write(archive, "../escape", b"bad")
    return path


def test_exact_snapshot_inner_surface_extracts_and_manifest_boundary_passes(tmp_path: Path) -> None:
    inner = _inner(tmp_path / artifact.INNER_ARCHIVE_NAME)
    destination = tmp_path / "snapshot"
    artifact._extract_inner(inner, destination)
    value = artifact._validate_manifest(destination, source_sha=SOURCE_SHA, snapshot_digest=SNAPSHOT_DIGEST)
    assert value["cell_count"] == 12
    assert set(path.relative_to(destination).as_posix() for path in destination.rglob("*") if path.is_file()) == artifact._expected_members()


def test_inner_archive_rejects_extra_or_traversal_members(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="exact 12-cell contract"):
        artifact._extract_inner(_inner(tmp_path / "extra.zip", extra="unexpected.txt"), tmp_path / "extra-out")
    with pytest.raises(RuntimeError, match="exact 12-cell contract"):
        artifact._extract_inner(_inner(tmp_path / "traversal.zip", traversal=True), tmp_path / "traversal-out")


def test_manifest_rejects_freshness_or_authority_escalation(tmp_path: Path) -> None:
    destination = tmp_path / "snapshot"
    destination.mkdir()
    value = _manifest()
    value["runtime_freshness_claimed"] = True
    (destination / artifact.MANIFEST_NAME).write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(RuntimeError, match="boundary contract mismatch"):
        artifact._validate_manifest(destination, source_sha=SOURCE_SHA, snapshot_digest=SNAPSHOT_DIGEST)

    value = _manifest()
    value["live_trading_authority"] = True
    (destination / artifact.MANIFEST_NAME).write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(RuntimeError, match="boundary contract mismatch"):
        artifact._validate_manifest(destination, source_sha=SOURCE_SHA, snapshot_digest=SNAPSHOT_DIGEST)


def test_outer_artifact_requires_one_exact_inner_zip(tmp_path: Path) -> None:
    outer = tmp_path / "outer.zip"
    with zipfile.ZipFile(outer, "w") as archive:
        archive.writestr("wrong.zip", b"x")
    with pytest.raises(RuntimeError, match="exactly one deterministic inner archive"):
        artifact._extract_outer(outer, tmp_path / "work")
