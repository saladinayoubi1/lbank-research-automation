from __future__ import annotations

import json
import math
from copy import deepcopy
from pathlib import Path

import pandas as pd

from phase6_research_pipeline import bind_bybit_closed_dataset
import nexus_multipair_discovery_snapshot as snapshot
import nexus_multipair_strategy_discovery as discovery
import nexus_multipair_strategy_proposal_requalification as requal


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


def _snapshot(tmp_path: Path) -> Path:
    root = tmp_path / "snapshot"
    value = snapshot.collect_snapshot(
        output_root=root,
        source_sha=SOURCE_SHA,
        now_ms=NOW_MS,
        fetcher=_fake_fetcher,
    )
    assert value["cell_count"] == 12
    assert snapshot.verify_snapshot(root, value)["decision"] == "pass"
    return root


def _manifest(tmp_path: Path, snapshot_root: Path, *, permissive: bool = False) -> Path:
    value = json.loads(MANIFEST.read_text(encoding="utf-8"))
    value["dataset"]["dataset_root"] = str(snapshot_root)
    if permissive:
        for name in ("training", "locked"):
            value["gates"][name] = {
                "minimum_positive_ratio": 0.0,
                "minimum_median_return": -1.0,
                "minimum_worst_return": -1.0,
                "maximum_drawdown": 1.0,
                "minimum_median_sharpe": -100.0,
                "minimum_sharpe": -100.0,
                "minimum_fill_count": 0,
            }
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def test_repository_manifest_is_four_symbol_research_only() -> None:
    value = discovery.load_manifest(MANIFEST)
    assert value["symbols"] == ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT"]
    assert value["timeframes"] == ["minute15", "hour1", "hour4"]
    assert value["families"] == ["momentum", "trend_breakout", "mean_reversion"]
    assert value["authority"] == {
        "research_only": True,
        "paper_only": True,
        "live_trading_authority": False,
        "private_credentials_allowed": False,
        "automatic_strategy_promotion": False,
    }


def test_snapshot_has_exact_12_cells_and_fails_closed_on_tamper(tmp_path: Path) -> None:
    root = _snapshot(tmp_path)
    manifest = json.loads((root / "snapshot-manifest.json").read_text(encoding="utf-8"))
    assert manifest["symbols"] == list(snapshot.SYMBOLS)
    assert len(manifest["cells"]) == 12
    target = root / "bybit_market" / "SOLUSDT" / "hour4.parquet"
    frame = pd.read_parquet(target)
    frame.loc[0, "close"] = float(frame.loc[0, "close"]) * 2
    frame.to_parquet(target, index=False)
    assert snapshot.verify_snapshot(root, manifest)["decision"] == "reject"


def test_discovery_v2_verifies_four_symbol_training_holdout_contract(tmp_path: Path) -> None:
    root = _snapshot(tmp_path)
    manifest_path = _manifest(tmp_path, root)
    result = discovery.run(manifest_path, tmp_path / "output", source_sha=SOURCE_SHA)
    assert discovery.verify_discovery(result)["decision"] == "pass"
    assert result["symbols"] == list(snapshot.SYMBOLS)
    assert result["hypothesis_count"] == 9
    assert len(result["cells"]) == 9
    assert all(row["selection_source"] == "training_only" for row in result["cells"])
    assert all(row["eligible_symbols"] == list(snapshot.SYMBOLS) for row in result["cells"])
    assert result["automatic_strategy_promotion"] is False
    assert result["live_trading_authority"] is False


def test_discovery_v2_zero_proposals_remains_valid(tmp_path: Path) -> None:
    root = _snapshot(tmp_path)
    value = json.loads(MANIFEST.read_text(encoding="utf-8"))
    value["dataset"]["dataset_root"] = str(root)
    for name in ("training", "locked"):
        value["gates"][name]["minimum_positive_ratio"] = 1.0
        value["gates"][name]["minimum_median_return"] = 10.0
    path = tmp_path / "strict.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    result = discovery.discover(discovery.load_manifest(path), source_sha=SOURCE_SHA)
    assert discovery.verify_discovery(result)["decision"] == "pass"
    assert result["research_proposal_count"] == 0


def test_requalification_covers_all_four_symbols_without_promotion(tmp_path: Path) -> None:
    root = _snapshot(tmp_path)
    manifest_path = _manifest(tmp_path, root, permissive=True)
    discovery.run(manifest_path, tmp_path / "output", source_sha=SOURCE_SHA)
    discovery_value = json.loads((tmp_path / "output" / "multipair_strategy_discovery.json").read_text())
    queue = json.loads((tmp_path / "output" / "research_proposals.json").read_text())
    assert discovery_value["research_proposal_count"] > 0

    def evaluator(proposal, symbol, source_sha, now_ms, state_root):
        return {
            "symbol": symbol,
            "family": proposal["family"],
            "timeframe": proposal["timeframe"],
            "variant_id": proposal["variant_id"],
            "runtime_dataset_binding_sha256": "1" * 64,
            "runtime_last_open_time_ms": now_ms - 1,
            "qualification_status": "paper_candidate",
            "pipeline_digest": "2" * 64,
            "qualification_digest": "3" * 64,
            "kill_reasons": [],
            "deterministic_replay_verified": True,
            "data_origin": "canonical_public_bybit_runtime",
            "closed_candle_finality_verified": True,
            "paper_only": True,
            "live_trading_authority": False,
            "paper_execution_started": False,
            "automatic_strategy_promotion": False,
            "deterministic_risk_final_authority": True,
        }

    result = requal.build_requalification(
        discovery_value,
        queue,
        source_sha=SOURCE_SHA,
        discovery_source_sha=SOURCE_SHA,
        state_root=tmp_path / "runtime",
        now_ms=NOW_MS,
        evaluator=evaluator,
    )
    assert requal.verify_requalification(result)["decision"] == "pass"
    assert result["status"] == "EVALUATED"
    assert result["qualified_for_review_count"] == result["proposal_count"]
    assert all(set(row["evaluated_symbols"]) == set(snapshot.SYMBOLS) for row in result["proposal_results"])
    assert result["candidate_creation_authority"] is False
    assert result["paper_execution_started"] is False
    assert result["automatic_strategy_promotion"] is False
    assert result["live_trading_authority"] is False


def test_tampered_snapshot_or_queue_fails_closed(tmp_path: Path) -> None:
    root = _snapshot(tmp_path)
    manifest_path = _manifest(tmp_path, root, permissive=True)
    result = discovery.run(manifest_path, tmp_path / "output", source_sha=SOURCE_SHA)
    queue = json.loads((tmp_path / "output" / "research_proposals.json").read_text())
    tampered = deepcopy(result)
    tampered["automatic_strategy_promotion"] = True
    assert discovery.verify_discovery(tampered)["decision"] == "reject"
    queue["symbols"] = ["BTCUSDT", "ETHUSDT"]
    try:
        requal.build_requalification(
            result, queue, source_sha=SOURCE_SHA, discovery_source_sha=SOURCE_SHA,
            state_root=tmp_path / "runtime", now_ms=NOW_MS,
            evaluator=lambda *args, **kwargs: {},
        )
    except requal.MultiPairProposalRequalificationError:
        pass
    else:
        raise AssertionError("tampered queue must fail closed")
