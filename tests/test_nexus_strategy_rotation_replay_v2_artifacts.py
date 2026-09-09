from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

WORKFLOWS = {
    "v2": (
        ROOT / ".github/workflows/bybit_strategy_search_v2.yml",
        "bybit_strategy_search_v2.py",
    ),
    "v3": (
        ROOT / ".github/workflows/bybit_portfolio_search_v3.yml",
        "bybit_portfolio_search_v3_scheduled.py",
    ),
    "v4": (
        ROOT / ".github/workflows/bybit_long_short_search_v4.yml",
        "bybit_long_short_search_v4.py",
    ),
    "v5": (
        ROOT / ".github/workflows/bybit_consensus_search_v5.yml",
        "bybit_consensus_search_v5.py",
    ),
    "v6": (
        ROOT / ".github/workflows/bybit_regime_search_v6.yml",
        "bybit_regime_search_v6.py",
    ),
    "v7": (
        ROOT / ".github/workflows/bybit_neighborhood_validation_v7.yml",
        "bybit_neighborhood_validation_v7.py",
    ),
}

LEGACY_ARTIFACT_ID = "8867026863"
LEGACY_ZIP_SHA256 = "5f1173467c2296201940c3b7786b7cc3e5442244e07289769ab4867ace41d668"
SEMANTIC_REPLAY_SHA256 = "2455a725886d81adaec9d3478e8f3b2daaba6c0c9645a691e71737eb64f67422"
REPLAY_FILE = "NEXUS_BYBIT_replay_v2_2022-12-01_to_2026-07-31.zip"
DELIVERY_FILE = "NEXUS_BYBIT_replay_v2_delivery.json"
ARTIFACT_PREFIX = "bybit-full-history-final-"


def test_strategy_rotation_stages_restore_by_semantic_replay_identity() -> None:
    for stage, (workflow, strategy_script) in WORKFLOWS.items():
        text = workflow.read_text(encoding="utf-8")

        assert LEGACY_ARTIFACT_ID not in text, stage
        assert LEGACY_ZIP_SHA256 not in text, stage
        assert "DEFAULT_ARTIFACT_ID" not in text, stage
        assert "artifact_id:" not in text, stage

        assert "scripts/select_nexus_bybit_replay_artifact.py" in text, stage
        assert REPLAY_FILE in text, stage
        assert DELIVERY_FILE in text, stage
        assert ARTIFACT_PREFIX in text, stage
        assert SEMANTIC_REPLAY_SHA256 in text, stage
        assert '--expected-semantic-sha256 "$DATASET_SHA256"' in text, stage
        assert '--delivery-name "$DATASET_DELIVERY"' in text, stage
        assert '--artifact-prefix "$DATASET_ARTIFACT_PREFIX"' in text, stage
        assert strategy_script in text, stage

        assert "contents: read" in text, stage
        assert "actions: read" in text, stage
        assert "contents: write" not in text, stage
        assert "actions: write" not in text, stage
