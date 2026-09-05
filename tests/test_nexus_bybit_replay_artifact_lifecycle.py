from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import zipfile

import pandas as pd
import pytest


ROOT = Path(__file__).resolve().parents[1]
SELECTOR_PATH = ROOT / "scripts" / "select_nexus_bybit_replay_artifact.py"
BUILDER_PATH = ROOT / "scripts" / "build_nexus_bybit_replay_package.py"
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


def test_rehydrate_workflow_is_manual_fail_closed_and_paper_only() -> None:
    text = REHYDRATE_WORKFLOW.read_text(encoding="utf-8")
    assert "workflow_dispatch:" in text
    assert "cancel-in-progress: false" in text
    assert "--start-date 2022-12-01" in text
    assert "--end-date 2023-01-31" in text
    assert "--max-archives-per-run 4" in text
    assert 'range(1, 43)' in text
    assert 'artifact.get("expired")' in text
    assert "Missing unexpired monthly chunk artifacts" in text
    assert 'report["summary"]["completed_units"] == 44' in text
    assert 'report["summary"]["source_archives"] == 88' in text
    assert "rehydrated_full_history_integrity=PASS" in text
    assert "HISTORICAL_LEGACY_SHA256" in text
    assert "historical_digest_match" in text
    assert "build_nexus_bybit_replay_package.py" in text
    assert "semantic_dataset_sha256=" in text
    assert "retention-days: 90" in text
    assert '"paper_replay_only": True' in text
    assert '"live_trading_authority": False' in text
    assert '"private_credentials_used": False' in text
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
