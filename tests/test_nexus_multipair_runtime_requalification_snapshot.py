from __future__ import annotations

import json
import math
from pathlib import Path

import pandas as pd

from phase6_research_pipeline import bind_bybit_closed_dataset
import nexus_multipair_discovery_snapshot as discovery_snapshot
import nexus_multipair_runtime_requalification_snapshot as runtime_snapshot
import nexus_multipair_strategy_discovery as discovery


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "experiments" / "nexus_multipair_strategy_discovery_v2.json"
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
        close = base * (1.0 + 0.0008 * index + 0.01 * math.sin(index / 7.0))
        open_price = close * (1.0 + 0.001 * math.sin(index / 5.0))
        candles.append({
            "source": "Bybit",
            "market_type": "spot",
            "symbol": source_symbol,
            "interval": interval,
            "open_time_ms": open_ms,
            "open": str(open_price),
            "high": str(max(open_price, close) * 1.003),
            "low": str(min(open_price, close) * 0.997),
            "close": str(close),
            "volume": str(1000.0 + index),
            "closed": True,
        })
    return bind_bybit_closed_dataset(
        candles,
        canonical_symbol=canonical_symbol,
        source_symbol=source_symbol,
        interval=interval,
    )


def _fresh_snapshot(tmp_path: Path, *, now_ms: int = NOW_MS) -> Path:
    root = tmp_path / f"runtime-{now_ms}"
    value = runtime_snapshot.collect_fresh_runtime_snapshot(
        output_root=root,
        source_sha=SOURCE_SHA,
        now_ms=now_ms,
        fetcher=_fake_fetcher,
    )
    assert value["history_limit"] == 240
    assert runtime_snapshot.verify_fresh_runtime_snapshot(
        root, value, source_sha=SOURCE_SHA, now_ms=now_ms
    )["decision"] == "pass"
    return root


def test_collects_exact_fresh_12_cell_240_row_runtime_snapshot(tmp_path: Path) -> None:
    root = _fresh_snapshot(tmp_path)
    value = json.loads((root / "snapshot-manifest.json").read_text())
    assert value["schema_version"] == discovery_snapshot.SCHEMA
    assert value["symbols"] == ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT"]
    assert value["timeframes"] == ["minute15", "hour1", "hour4"]
    assert value["cell_count"] == 12
    assert value["history_limit"] == 240
    assert value["data_origin"] == "canonical_public_bybit_closed_candles"
    assert value["research_only"] is True
    assert value["paper_execution_started"] is False
    assert value["live_trading_authority"] is False
    assert value["private_credentials_used"] is False
    assert value["automatic_strategy_promotion"] is False


def test_runtime_snapshot_fails_closed_after_transport_freshness_budget(tmp_path: Path) -> None:
    root = _fresh_snapshot(tmp_path)
    value = json.loads((root / "snapshot-manifest.json").read_text())
    too_late = NOW_MS + runtime_snapshot.MAX_SNAPSHOT_TRANSPORT_AGE_MS + 1
    verification = runtime_snapshot.verify_fresh_runtime_snapshot(
        root,
        value,
        source_sha=SOURCE_SHA,
        now_ms=too_late,
    )
    assert verification["decision"] == "reject"
    assert verification["checks"]["transport_age"] is False


def test_runtime_snapshot_pack_is_deterministic(tmp_path: Path) -> None:
    root = _fresh_snapshot(tmp_path)
    first = tmp_path / "one.zip"
    second = tmp_path / "two.zip"
    first_sha = runtime_snapshot.deterministic_pack(root, first)
    second_sha = runtime_snapshot.deterministic_pack(root, second)
    assert first_sha == second_sha
    assert first.read_bytes() == second.read_bytes()


def test_transport_rebinds_verified_frame_to_canonical_bybit_dataset(tmp_path: Path) -> None:
    root = _fresh_snapshot(tmp_path)
    value = json.loads((root / "snapshot-manifest.json").read_text())
    dataset = runtime_snapshot.bind_transported_runtime_dataset(
        root,
        value,
        symbol="SOLUSDT",
        timeframe="hour4",
    )
    assert dataset["source"] == "Bybit"
    assert dataset["source_role"] == "primary"
    assert dataset["source_symbol"] == "SOLUSDT"
    assert dataset["manifest_timeframe"] == "4h"
    assert dataset["interval"] == "240"
    assert dataset["row_count"] == 240
    assert dataset["paper_only"] is True
    assert len(dataset["binding_sha256"]) == 64


def test_runtime_snapshot_evaluator_binds_transport_and_replays_deterministically(tmp_path: Path) -> None:
    root = _fresh_snapshot(tmp_path)
    value = json.loads((root / "snapshot-manifest.json").read_text())
    evaluator = runtime_snapshot.RuntimeSnapshotEvaluator(
        root,
        value,
        source_sha=SOURCE_SHA,
        now_ms=NOW_MS,
    )
    proposal = {
        "proposal_digest": "1" * 64,
        "family": "momentum",
        "timeframe": "minute15",
        "variant_id": "unit-runtime-variant",
        "strategy_config": {"lookback": 12, "entry_threshold": 0.002},
    }
    result = evaluator(proposal, "BTCUSDT", SOURCE_SHA, NOW_MS, tmp_path / "state")
    assert result["symbol"] == "BTCUSDT"
    assert result["qualification_status"] in {"paper_candidate", "killed"}
    assert result["deterministic_replay_verified"] is True
    assert result["data_origin"] == "canonical_public_bybit_runtime"
    assert result["runtime_data_transport"] == runtime_snapshot.TRANSPORT_ORIGIN
    assert result["runtime_snapshot_digest"] == value["snapshot_digest"]
    assert result["runtime_snapshot_as_of_ms"] == NOW_MS
    assert result["paper_execution_started"] is False
    assert result["automatic_strategy_promotion"] is False
    assert result["live_trading_authority"] is False
    assert result["deterministic_risk_final_authority"] is True


def test_snapshot_backed_requalification_is_distinct_from_discovery_even_with_zero_proposals(tmp_path: Path) -> None:
    discovery_root = tmp_path / "discovery-snapshot"
    discovery_value = discovery_snapshot.collect_snapshot(
        output_root=discovery_root,
        source_sha=SOURCE_SHA,
        now_ms=NOW_MS - 2 * 86_400_000,
        limit=500,
        fetcher=_fake_fetcher,
    )
    assert discovery_snapshot.verify_snapshot(discovery_root, discovery_value)["decision"] == "pass"

    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    manifest["dataset"]["dataset_root"] = str(discovery_root)
    for name in ("training", "locked"):
        manifest["gates"][name]["minimum_positive_ratio"] = 1.0
        manifest["gates"][name]["minimum_median_return"] = 10.0
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    discovery_output = tmp_path / "discovery-output"
    discovery_result = discovery.run(manifest_path, discovery_output, source_sha=SOURCE_SHA)
    assert discovery_result["research_proposal_count"] == 0

    runtime_root = _fresh_snapshot(tmp_path)
    result = runtime_snapshot.run_requalification_from_snapshot(
        discovery_output / "multipair_strategy_discovery.json",
        discovery_output / "research_proposals.json",
        snapshot_root=runtime_root,
        source_sha=SOURCE_SHA,
        state_root=tmp_path / "requalification-state",
        output=tmp_path / "runtime-requalification.json",
        now_ms=NOW_MS,
    )
    runtime_value = json.loads((runtime_root / "snapshot-manifest.json").read_text())
    assert result["status"] == "NO_WORK"
    assert result["proposal_count"] == 0
    assert result["runtime_data_is_fresh_not_snapshot_reuse"] is True
    assert result["runtime_data_transport"] == runtime_snapshot.TRANSPORT_ORIGIN
    assert result["runtime_snapshot_digest"] == runtime_value["snapshot_digest"]
    assert result["runtime_snapshot_distinct_from_discovery"] is True
    assert result["historical_discovery_snapshot_reused"] is False
    assert result["paper_execution_started"] is False
    assert result["automatic_strategy_promotion"] is False
    assert result["live_trading_authority"] is False
