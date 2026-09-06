from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import urllib.request
import zipfile

import pandas as pd
import pytest


ROOT = Path(__file__).resolve().parents[1]
SELECTOR_PATH = ROOT / "scripts" / "select_nexus_bybit_replay_artifact.py"
BUILDER_PATH = ROOT / "scripts" / "build_nexus_bybit_replay_package.py"
CHUNK_MAP_PATH = ROOT / "scripts" / "nexus_bybit_replay_chunks.py"
CHUNK_REHYDRATOR_PATH = ROOT / "scripts" / "rehydrate_nexus_bybit_chunk.py"
REHYDRATE_WORKFLOW = ROOT / ".github" / "workflows" / "bybit_full_history_backfill.yml"
MATRIX_WORKFLOW = ROOT / ".github" / "workflows" / "nexus_demo_strategy_matrix.yml"


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_selector_requires_manifest_and_exact_immutable_zip_digest(tmp_path: Path) -> None:
    selector = _load(SELECTOR_PATH, "nexus_replay_selector_test")
    root = tmp_path / "candidate"
    root.mkdir()
    replay = root / "BYBIT_full_history_2022-12-01_to_2026-07-31.zip"
    replay.write_bytes(b"immutable-replay-bytes")
    digest = hashlib.sha256(replay.read_bytes()).hexdigest()
    (root / selector.DELIVERY_NAME).write_text(
        json.dumps({"file_name": replay.name, "sha256": digest}), encoding="utf-8"
    )

    selected, delivery = selector.validate_candidate(root, replay.name, digest)
    assert selected == replay
    assert delivery.name == selector.DELIVERY_NAME

    with pytest.raises(selector.ReplayArtifactError, match="delivery manifest replay SHA mismatch"):
        selector.validate_candidate(root, replay.name, "0" * 64)


def test_selector_safe_extract_rejects_path_traversal(tmp_path: Path) -> None:
    selector = _load(SELECTOR_PATH, "nexus_replay_selector_zip_test")
    archive = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(archive, "w") as handle:
        handle.writestr("../escape.txt", "forbidden")
    with pytest.raises(selector.ReplayArtifactError, match="unsafe artifact member"):
        selector.safe_extract(archive, tmp_path / "out")


def test_semantic_digest_is_data_stable_and_changes_with_market_values() -> None:
    builder = _load(BUILDER_PATH, "nexus_replay_builder_digest_test")
    frame = pd.DataFrame(
        [
            {
                "timestamp": pd.Timestamp("2026-01-01T00:00:00Z"),
                "open": 1.0,
                "high": 2.0,
                "low": 0.5,
                "close": 1.5,
                "volume": 10.0,
                "symbol": "btc_usdt",
                "timeframe": "hour1",
            },
            {
                "timestamp": pd.Timestamp("2026-01-01T01:00:00Z"),
                "open": 1.5,
                "high": 2.5,
                "low": 1.0,
                "close": 2.0,
                "volume": 11.0,
                "symbol": "btc_usdt",
                "timeframe": "hour1",
            },
        ]
    )
    first = builder.semantic_series_digest(frame)
    assert first == builder.semantic_series_digest(frame.copy())
    changed = frame.copy()
    changed.loc[1, "close"] = 2.0001
    assert builder.semantic_series_digest(changed) != first


def test_replay_timestamp_grid_normalizes_equivalent_storage_units() -> None:
    builder = _load(BUILDER_PATH, "nexus_replay_builder_timestamp_unit_test")
    expected = pd.date_range("2026-01-01", periods=8, freq="15min", tz="UTC").as_unit("ns")
    parquet_style = expected.as_unit("us")
    assert expected.difference(parquet_style).empty
    assert parquet_style.difference(expected).empty
    assert not parquet_style.equals(expected)
    assert builder.canonical_timestamp_index(parquet_style).equals(expected)


def test_validate_series_accepts_microsecond_parquet_timestamps(tmp_path: Path) -> None:
    builder = _load(BUILDER_PATH, "nexus_replay_builder_validate_timestamp_unit_test")
    builder.START_DATE = "2026-01-01"
    builder.END_DATE = "2026-01-01"
    builder.TIMEFRAMES = {"minute15": (pd.Timedelta(minutes=15), 96)}
    timestamps = pd.date_range(
        "2026-01-01T00:00:00Z", periods=96, freq="15min"
    ).as_unit("us")
    frame = pd.DataFrame(
        {
            "timestamp": timestamps,
            "open": 100.0,
            "high": 101.0,
            "low": 99.0,
            "close": 100.5,
            "volume": 1.0,
            "symbol": "btc_usdt",
            "timeframe": "minute15",
        }
    )
    path = tmp_path / "minute15.parquet"
    frame.to_parquet(path, index=False)
    result = builder.validate_series(path, "btc_usdt", "minute15")
    assert result["rows"] == 96
    assert result["first_timestamp"] == "2026-01-01T00:00:00+00:00"
    assert result["last_timestamp"] == "2026-01-01T23:45:00+00:00"


def test_deterministic_zip_is_byte_identical_for_same_inputs(tmp_path: Path) -> None:
    builder = _load(BUILDER_PATH, "nexus_replay_builder_zip_test")
    root = tmp_path / "root"
    (root / "bybit_market" / "btc_usdt").mkdir(parents=True)
    payload = root / "bybit_market" / "btc_usdt" / "hour1.parquet"
    payload.write_bytes(b"same-content")
    manifest = {
        "schema_version": 2,
        "files": [{"path": "bybit_market/btc_usdt/hour1.parquet"}],
    }
    first = tmp_path / "first.zip"
    second = tmp_path / "second.zip"
    first_sha = builder.write_deterministic_zip(root, first, manifest)
    second_sha = builder.write_deterministic_zip(root, second, manifest)
    assert first_sha == second_sha
    assert first.read_bytes() == second.read_bytes()


def test_canonical_replay_chunk_map_is_complete_contiguous_and_matches_anchors() -> None:
    chunks = _load(CHUNK_MAP_PATH, "nexus_replay_chunks_contract_test")
    values = chunks.CANONICAL_CHUNKS
    assert len(values) == 42
    assert len({item.id for item in values}) == 42

    expected = {
        "27": ("2023-02-01", "2023-02-28"),
        "42": ("2024-05-01", "2024-05-31"),
        "01": ("2024-06-01", "2024-06-30"),
        "02": ("2024-07-01", "2024-07-31"),
        "03": ("2024-08-01", "2024-08-31"),
        "05": ("2024-10-01", "2024-10-31"),
        "18": ("2025-11-01", "2025-11-30"),
        "21": ("2026-02-01", "2026-02-28"),
        "22": ("2026-03-01", "2026-03-31"),
        "26": ("2026-07-01", "2026-07-31"),
    }
    for chunk_id, (start, end) in expected.items():
        item = chunks.CANONICAL_CHUNK_MAP[chunk_id]
        assert (item.start, item.end) == (start, end)

    for previous, current in zip(values, values[1:]):
        assert pd.Timestamp(previous.end) + pd.Timedelta(days=1) == pd.Timestamp(current.start)


def test_rehydrate_plan_reuses_latest_unexpired_and_rebuilds_missing() -> None:
    chunks = _load(CHUNK_MAP_PATH, "nexus_replay_chunks_plan_test")
    payload = [
        {
            "artifacts": [
                {
                    "id": 10,
                    "name": "bybit-chunk-01-attempt-1",
                    "expired": False,
                    "created_at": "2026-09-01T00:00:00Z",
                },
                {
                    "id": 11,
                    "name": "bybit-chunk-01-attempt-2",
                    "expired": False,
                    "created_at": "2026-09-02T00:00:00Z",
                },
                {
                    "id": 14,
                    "name": "bybit-rehydrated-chunk-01-34062636033",
                    "expired": False,
                    "created_at": "2026-09-05T00:00:00Z",
                },
                {
                    "id": 12,
                    "name": "bybit-chunk-02-attempt-1",
                    "expired": True,
                    "created_at": "2026-09-03T00:00:00Z",
                },
                {
                    "id": 13,
                    "name": "not-a-replay-artifact",
                    "expired": False,
                    "created_at": "2026-09-04T00:00:00Z",
                },
            ]
        }
    ]
    plan = chunks.build_plan(payload)
    assert plan["required_chunk_count"] == 42
    assert plan["reusable_chunk_count"] == 1
    assert plan["reusable_artifacts"]["01"]["artifact_id"] == 14
    assert plan["reusable_artifacts"]["01"]["name"] == "bybit-chunk-01-attempt-rehydrated"
    assert plan["reusable_artifacts"]["01"]["source_name"] == "bybit-rehydrated-chunk-01-34062636033"
    assert plan["missing_chunk_count"] == 41
    assert "02" in plan["missing_ids"]
    entry = next(item for item in plan["missing_matrix"]["include"] if item["id"] == "02")
    assert entry == {"id": "02", "start": "2024-07-01", "end": "2024-07-31"}


def test_cross_host_redirect_strips_github_authorization() -> None:
    chunks = _load(CHUNK_MAP_PATH, "nexus_replay_redirect_contract_test")
    handler = chunks._CrossHostAuthStrippingRedirectHandler()
    request = urllib.request.Request(
        "https://api.github.com/repos/example/repo/actions/artifacts/1/zip",
        headers={"Authorization": "Bearer test-token"},
    )
    redirected = handler.redirect_request(
        request,
        None,
        302,
        "Found",
        {},
        "https://productionresultssa8.blob.core.windows.net/actions-results/file.zip?sig=signed",
    )
    assert redirected is not None
    assert redirected.get_header("Authorization") is None

    same_origin = handler.redirect_request(
        request,
        None,
        302,
        "Found",
        {},
        "https://api.github.com/repos/example/repo/actions/artifacts/1/redirected",
    )
    assert same_origin is not None
    assert same_origin.get_header("Authorization") == "Bearer test-token"


def test_chunk_rehydrator_rejects_noncanonical_dates_before_network_access() -> None:
    rehydrator = _load(CHUNK_REHYDRATOR_PATH, "nexus_replay_chunk_rehydrator_contract_test")
    rehydrator._validate_chunk_request("01", "2024-06-01", "2024-06-30")
    with pytest.raises(SystemExit, match="date mismatch"):
        rehydrator._validate_chunk_request("01", "2024-06-02", "2024-06-30")
    with pytest.raises(SystemExit, match="Unknown replay chunk id"):
        rehydrator._validate_chunk_request("99", "2024-06-01", "2024-06-30")


def test_rehydrate_workflow_rebuilds_missing_chunks_fail_closed_and_paper_only() -> None:
    text = REHYDRATE_WORKFLOW.read_text(encoding="utf-8")
    assert "workflow_dispatch:" in text
    assert "cancel-in-progress: false" in text
    assert "scripts/nexus_bybit_replay_chunks.py" in text
    assert "scripts/rehydrate_nexus_bybit_chunk.py" in text
    assert "missing_matrix" in text
    assert "reusable_artifacts" in text
    assert "max-parallel: 6" in text
    assert "bybit-rehydrated-chunk-" in text
    assert "canonical_monthly_chunk_coverage=PASS" in text
    assert "validated_monthly_chunk_count=" in text
    assert "--start-date 2022-12-01" in text
    assert "--end-date 2023-01-31" in text
    assert "--max-archives-per-run 4" in text
    assert 'report["summary"]["completed_units"] == 44' in text
    assert 'report["summary"]["source_archives"] == 88' in text
    assert "rehydrated_full_history_integrity=PASS" in text
    assert "HISTORICAL_LEGACY_SHA256" in text
    assert "historical_digest_match" in text
    assert "build_nexus_bybit_replay_package.py" in text
    assert "semantic_dataset_sha256=" in text
    assert "retention-days: 7" in text
    assert "retention-days: 90" in text
    assert '"paper_replay_only": True' in text
    assert '"live_trading_authority": False' in text
    assert '"private_credentials_used": False' in text
    assert "BASE_ARTIFACT_ID" not in text
    assert "Missing unexpired monthly chunk artifacts" not in text
    for forbidden in (
        "api_key",
        "api_secret",
        "place_order",
        "create_order",
        "live_trading_authority: true",
    ):
        assert forbidden not in text.lower()


def test_matrix_restores_by_content_not_fixed_artifact_id() -> None:
    text = MATRIX_WORKFLOW.read_text(encoding="utf-8")
    assert "DATASET_ARTIFACT_ID" not in text
    assert "DATASET_ARTIFACT_PREFIX: bybit-full-history-final-" in text
    assert "select_nexus_bybit_replay_artifact.py" in text
    assert "--expected-sha256 \"$DATASET_SHA256\"" in text
    assert "5f1173467c2296201940c3b7786b7cc3e5442244e07289769ab4867ace41d668" in text
