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
LIFECYCLE_WORKFLOW = (
    ROOT / ".github" / "workflows" / "nexus_demo_regime_lifecycle_bridge.yml"
)
STRATEGY_FACTORY_REPLAY_WORKFLOWS = tuple(
    ROOT / ".github" / "workflows" / name
    for name in (
        "bybit_strategy_search_v2.yml",
        "bybit_portfolio_search_v3.yml",
        "bybit_long_short_search_v4.yml",
        "bybit_consensus_search_v5.yml",
        "bybit_regime_search_v6.yml",
        "bybit_neighborhood_validation_v7.yml",
        "nexus_multitimeframe_strategy_discovery.yml",
    )
)


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def frozen_bulk_dataset(tmp_path, monkeypatch):
    from scripts import build_nexus_bybit_replay_package as builder
    from scripts import rehydrate_nexus_bybit_chunk as rehydrator
    import nexus_demo_archive_contract as contract

    # A compact grid has candles before, inside, and after the permitted months.
    grid = pd.DatetimeIndex(["2024-03-31", "2024-04-01", "2024-06-01"], tz="UTC").as_unit("ns")
    monkeypatch.setattr(builder, "expected_index", lambda step: grid)
    for timeframe, (step, _) in list(builder.TIMEFRAMES.items()):
        monkeypatch.setitem(builder.TIMEFRAMES, timeframe, (step, len(grid)))
    reference, output = tmp_path / "reference", tmp_path / "output"
    for symbol in builder.SYMBOLS:
        for timeframe in builder.TIMEFRAMES:
            relative = Path("bybit_market") / symbol / f"{timeframe}.parquet"
            frame = pd.DataFrame({
                "timestamp": grid, "open": 100.0, "high": 120.0, "low": 90.0,
                "close": 105.0, "volume": 10.0, "symbol": symbol, "timeframe": timeframe,
            })
            for root in (reference, output):
                (root / relative).parent.mkdir(parents=True, exist_ok=True)
            frame.to_parquet(reference / relative, index=False)
            frame.loc[1, "open"] = 110.0
            frame.to_parquet(output / relative, index=False)
    canonical = builder.build_manifest(reference)["semantic_dataset_sha256"]
    monkeypatch.setattr(contract, "ARCHIVE_SHA256", canonical)
    sources = []
    for filename, sha in rehydrator.FROZEN_BULK_SOURCE_SHA256.items():
        symbol, year, month_file = filename.split("-")
        period = pd.Period(f"{year}-{month_file[:2]}", freq="M")
        sources.append({
            "filename": filename, "symbol": symbol, "sha256": sha,
            "start_date": period.start_time.strftime("%Y-%m-%d"),
            "end_date": period.end_time.strftime("%Y-%m-%d"),
            "url": f"https://public.bybit.com/spot/{symbol}/{filename}",
            "parser_engine": "c-chunked",
        })
    (output / "_source_manifest.json").write_text(json.dumps(sources))
    return builder, rehydrator, reference, output, sources, canonical


def test_frozen_restoration_preserves_exact_reference_and_only_permitted_months(frozen_bulk_dataset):
    builder, rehydrator, reference, output, _, canonical = frozen_bulk_dataset
    receipt = rehydrator.restore_frozen_bulk_semantics(output, reference)
    assert receipt["restored_chunk_ids"] == ["41", "42"]
    assert receipt["outside_month_candles_unchanged"] is True
    assert len(receipt["unchanged_official_raw_archives"]) == 4
    assert receipt["live_trading_authority"] is False
    assert builder.build_manifest(output)["semantic_dataset_sha256"] == canonical
    for path in reference.rglob("*.parquet"):
        pd.testing.assert_frame_equal(pd.read_parquet(path), pd.read_parquet(output / path.relative_to(reference)))


@pytest.mark.parametrize("mutation", ["digest", "missing", "duplicate", "venue"])
def test_frozen_restoration_rejects_changed_or_ambiguous_raw_sources(frozen_bulk_dataset, mutation):
    _, rehydrator, reference, output, sources, _ = frozen_bulk_dataset
    if mutation == "digest":
        sources[0]["sha256"] = "0" * 64
    elif mutation == "missing":
        sources.pop()
    elif mutation == "duplicate":
        sources.append(dict(sources[0]))
    else:
        sources[0]["url"] = "https://example.test/substitute.csv.gz"
    (output / "_source_manifest.json").write_text(json.dumps(sources))
    before = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in output.rglob("*.parquet")}
    with pytest.raises(rehydrator.FrozenReplaySemanticsError):
        rehydrator.restore_frozen_bulk_semantics(output, reference)
    assert before == {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in before}


def test_frozen_restoration_rejects_drift_outside_allowed_months_without_writes(frozen_bulk_dataset):
    _, rehydrator, reference, output, _, _ = frozen_bulk_dataset
    path = next(output.rglob("*.parquet"))
    frame = pd.read_parquet(path)
    frame.loc[2, "close"] += 1
    frame.to_parquet(path, index=False)
    before = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in output.rglob("*.parquet")}
    with pytest.raises(rehydrator.FrozenReplaySemanticsError, match="outside frozen bulk months"):
        rehydrator.restore_frozen_bulk_semantics(output, reference)
    assert before == {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in before}


def test_frozen_restoration_rejects_reference_that_is_not_the_frozen_content(frozen_bulk_dataset):
    _, rehydrator, reference, output, _, _ = frozen_bulk_dataset
    path = next(reference.rglob("*.parquet"))
    frame = pd.read_parquet(path)
    frame.loc[1, "open"] += 1
    frame.to_parquet(path, index=False)
    with pytest.raises(rehydrator.FrozenReplaySemanticsError, match="not the frozen canonical"):
        rehydrator.restore_frozen_bulk_semantics(output, reference)


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


def test_selector_cross_host_redirect_strips_github_authorization() -> None:
    selector = _load(SELECTOR_PATH, "nexus_replay_selector_redirect_test")
    handler = selector._CrossHostAuthStrippingRedirectHandler()
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


def test_selector_accepts_v2_semantic_identity_without_pinning_container_bytes(tmp_path: Path) -> None:
    selector = _load(SELECTOR_PATH, "nexus_replay_selector_semantic_test")
    root = tmp_path / "candidate-v2"
    root.mkdir()
    replay = root / "NEXUS_BYBIT_replay_v2_2022-12-01_to_2026-07-31.zip"
    semantic = "2" * 64
    manifest_core = {
        "schema_version": 2,
        "semantic_dataset_sha256": semantic,
        "series_count": 1,
        "files": [],
    }
    manifest_sha = hashlib.sha256(selector._canonical_json_bytes(manifest_core)).hexdigest()
    manifest = {**manifest_core, "manifest_sha256": manifest_sha}
    with zipfile.ZipFile(replay, "w") as handle:
        handle.writestr(selector.REPLAY_V2_MANIFEST, json.dumps(manifest))
    replay_sha = hashlib.sha256(replay.read_bytes()).hexdigest()
    delivery_name = "NEXUS_BYBIT_replay_v2_delivery.json"
    (root / delivery_name).write_text(
        json.dumps({
            "schema_version": 2,
            "file_name": replay.name,
            "sha256": replay_sha,
            "semantic_dataset_sha256": semantic,
            "dataset_manifest_sha256": manifest_sha,
            "series_count": 1,
            "paper_replay_only": True,
            "live_trading_authority": False,
            "private_credentials_used": False,
        }),
        encoding="utf-8",
    )
    selected, delivery = selector.validate_candidate(
        root,
        replay.name,
        expected_semantic_sha256=semantic,
        delivery_name=delivery_name,
    )
    assert selected == replay
    assert delivery.name == delivery_name
    with pytest.raises(selector.ReplayArtifactError, match="semantic replay SHA mismatch"):
        selector.validate_candidate(
            root,
            replay.name,
            expected_semantic_sha256="3" * 64,
            delivery_name=delivery_name,
        )


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


def test_chunk_artifact_listing_is_bounded_and_stops_when_all_chunks_are_found(monkeypatch) -> None:
    chunks = _load(CHUNK_MAP_PATH, "nexus_replay_chunks_listing_test")
    calls = []

    def fake_request(url, token):
        calls.append((url, token))
        return {
            "artifacts": [
                {
                    "id": 1000 + index,
                    "name": f"bybit-rehydrated-chunk-{chunk.id}-99999",
                    "expired": False,
                    "created_at": "2026-10-07T00:00:00Z",
                }
                for index, chunk in enumerate(chunks.CANONICAL_CHUNKS)
            ]
        }

    monkeypatch.setattr(chunks, "_request_json", fake_request)
    payload = chunks.fetch_artifact_pages("example/repo", "token", max_pages=20)
    plan = chunks.build_plan(payload)

    assert len(calls) == 1
    assert "per_page=100" in calls[0][0]
    assert "page=1" in calls[0][0]
    assert plan["reusable_chunk_count"] == 42
    assert plan["missing_chunk_count"] == 0


def test_bounded_chunk_listing_treats_unseen_chunks_as_rebuild_required(monkeypatch) -> None:
    chunks = _load(CHUNK_MAP_PATH, "nexus_replay_chunks_bounded_listing_test")

    def fake_request(_url, _token):
        return {
            "artifacts": [
                {
                    "id": index + 1,
                    "name": f"unrelated-artifact-{index}",
                    "expired": False,
                    "created_at": "2026-10-07T00:00:00Z",
                }
                for index in range(100)
            ]
        }

    monkeypatch.setattr(chunks, "_request_json", fake_request)
    payload = chunks.fetch_artifact_pages("example/repo", "token", max_pages=1)
    plan = chunks.build_plan(payload)

    assert plan["reusable_chunk_count"] == 0
    assert plan["missing_chunk_count"] == 42


def test_rehydrate_workflow_rebuilds_missing_chunks_fail_closed_and_paper_only() -> None:
    text = REHYDRATE_WORKFLOW.read_text(encoding="utf-8")
    assert "workflow_dispatch:" in text
    assert "cancel-in-progress: false" in text
    assert "scripts/nexus_bybit_replay_chunks.py" in text
    assert "gh api --paginate --slurp" not in text
    assert '--max-pages 20' in text
    assert '--token-env GH_TOKEN' in text
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


def test_matrix_restores_replay_v2_by_semantic_content_not_fixed_artifact_id() -> None:
    text = MATRIX_WORKFLOW.read_text(encoding="utf-8")
    assert "DATASET_ARTIFACT_ID" not in text
    assert "DATASET_ARTIFACT_PREFIX: bybit-full-history-final-" in text
    assert "DATASET_FILE: NEXUS_BYBIT_replay_v2_2022-12-01_to_2026-07-31.zip" in text
    assert "DATASET_DELIVERY: NEXUS_BYBIT_replay_v2_delivery.json" in text
    assert "select_nexus_bybit_replay_artifact.py" in text
    assert "--expected-semantic-sha256 \"$DATASET_SHA256\"" in text
    assert "--delivery-name \"$DATASET_DELIVERY\"" in text
    assert "2455a725886d81adaec9d3478e8f3b2daaba6c0c9645a691e71737eb64f67422" in text
    assert "5f1173467c2296201940c3b7786b7cc3e5442244e07289769ab4867ace41d668" not in text


def test_lifecycle_bridge_restores_replay_v2_by_semantic_content_not_fixed_artifact_id() -> None:
    text = LIFECYCLE_WORKFLOW.read_text(encoding="utf-8")
    assert "DATASET_ARTIFACT_ID" not in text
    assert "DATASET_ARTIFACT_PREFIX: bybit-full-history-final-" in text
    assert "DATASET_FILE: NEXUS_BYBIT_replay_v2_2022-12-01_to_2026-07-31.zip" in text
    assert "DATASET_DELIVERY: NEXUS_BYBIT_replay_v2_delivery.json" in text
    assert "select_nexus_bybit_replay_artifact.py" in text
    assert '--expected-semantic-sha256 "$DATASET_SHA256"' in text
    assert '--delivery-name "$DATASET_DELIVERY"' in text
    assert "2455a725886d81adaec9d3478e8f3b2daaba6c0c9645a691e71737eb64f67422" in text
    assert "8867026863" not in text
    assert "5f1173467c2296201940c3b7786b7cc3e5442244e07289769ab4867ace41d668" not in text


def test_selector_filters_optional_exact_artifact_id_without_weakening_identity(
    monkeypatch,
) -> None:
    selector = _load(SELECTOR_PATH, "nexus_replay_optional_artifact_filter_test")
    payload = {
        "artifacts": [
            {
                "id": 11,
                "name": "bybit-full-history-final-older",
                "expired": False,
                "created_at": "2026-09-01T00:00:00Z",
            },
            {
                "id": 12,
                "name": "bybit-full-history-final-newer",
                "expired": False,
                "created_at": "2026-09-02T00:00:00Z",
            },
            {
                "id": 13,
                "name": "bybit-full-history-final-expired",
                "expired": True,
                "created_at": "2026-09-03T00:00:00Z",
            },
        ]
    }
    monkeypatch.setattr(selector, "_request_json", lambda *_args, **_kwargs: payload)

    selected = selector.list_candidate_artifacts(
        "example/repo", "token", artifact_id=12
    )
    assert [item["id"] for item in selected] == [12]
    assert selector.list_candidate_artifacts(
        "example/repo", "token", artifact_id=13
    ) == []


def test_selector_discovers_replay_from_source_workflow_before_repo_scan(monkeypatch) -> None:
    selector = _load(SELECTOR_PATH, "nexus_replay_source_workflow_test")
    calls: list[str] = []

    def fake_request(url: str, _token: str):
        calls.append(url)
        if "/actions/workflows/" in url:
            return {"workflow_runs": [{"id": 101, "conclusion": "success"}, {"id": 100, "conclusion": "failure"}]}
        if "/actions/runs/101/artifacts" in url:
            return {"artifacts": [{"id": 1001, "name": "bybit-full-history-final-rehydrated-101", "expired": False, "created_at": "2026-09-09T00:00:00Z"}]}
        raise AssertionError(url)

    monkeypatch.setattr(selector, "_request_json", fake_request)
    selected = selector.list_source_workflow_candidate_artifacts("example/repo", "token")
    assert [item["id"] for item in selected] == [1001]
    assert not any("/actions/artifacts?" in url for url in calls)


def test_selector_repo_fallback_scans_beyond_legacy_ten_page_cap(monkeypatch) -> None:
    selector = _load(SELECTOR_PATH, "nexus_replay_deep_pagination_test")
    pages: list[int] = []

    def fake_request(url: str, _token: str):
        page = int(url.rsplit("page=", 1)[1])
        pages.append(page)
        if page < 14:
            return {"artifacts": [{"id": page * 100 + i, "name": f"other-{page}-{i}", "expired": False} for i in range(100)]}
        return {"artifacts": [{"id": 1401, "name": "bybit-full-history-final-rehydrated-archive", "expired": False, "created_at": "2026-09-09T00:00:00Z"}]}

    monkeypatch.setattr(selector, "_request_json", fake_request)
    selected = selector.list_candidate_artifacts("example/repo", "token", max_pages=20)
    assert [item["id"] for item in selected] == [1401]
    assert pages == list(range(1, 15))


def test_strategy_factory_workflows_rotate_replay_v2_without_fixed_artifact_ids() -> None:
    for workflow in STRATEGY_FACTORY_REPLAY_WORKFLOWS:
        text = workflow.read_text(encoding="utf-8")
        assert 'default: ""' in text
        assert "DATASET_ARTIFACT_ID" not in text
        assert "DEFAULT_ARTIFACT_ID" not in text
        assert "DATASET_ARTIFACT_PREFIX: bybit-full-history-final-" in text
        assert (
            "DATASET_FILE: NEXUS_BYBIT_replay_v2_2022-12-01_to_2026-07-31.zip"
            in text
        )
        assert "DATASET_DELIVERY: NEXUS_BYBIT_replay_v2_delivery.json" in text
        assert "select_nexus_bybit_replay_artifact.py" in text
        assert '--expected-semantic-sha256 "$DATASET_SHA256"' in text
        assert '--artifact-id "$DISPATCH_ARTIFACT_ID"' in text
        assert (
            "2455a725886d81adaec9d3478e8f3b2daaba6c0c9645a691e71737eb64f67422"
            in text
        )
        assert "8867026863" not in text
        assert (
            "5f1173467c2296201940c3b7786b7cc3e5442244e07289769ab4867ace41d668"
            not in text
        )

