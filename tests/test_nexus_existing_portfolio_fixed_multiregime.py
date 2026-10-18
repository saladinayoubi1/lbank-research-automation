"""Independent historical evidence reconciliation for frozen original portfolio v3.

No inference of strategy alpha, external fills, or future OOS is permitted.
"""
from __future__ import annotations
import hashlib
import json
from pathlib import Path

import pytest

from nexus_demo_archive_replay import ARCHIVE_SHA256
from scripts import nexus_existing_portfolio_fixed_multiregime as replay
from scripts import nexus_existing_portfolio_shared500_diagnostic as guard
from scripts.nexus_strategy_finder_shared_cash_eval import PINNED_BYBIT_PARQUET_SHA256

ROOT=Path(__file__).resolve().parents[1]
EVIDENCE=ROOT/"docs/evidence/portfolio-v3-original-500-calibration-20261018/fixed-dual-rotation-2023-2026-six-regimes-vs-passive.json"
DIGEST="63afc60f7e35fbe456a4a43b3dc061e6b253d33d46e60b0fa95725ca29050077"
Q1_PRIOR="67c3817359fb4b9a225cc89c6abcd5a405b5602c4e3f20d822056fa1515ad746"
REGIMES=(
 "2023_09_to_2024_03","2024_03_to_2024_09","2024_09_to_2025_03",
 "2025_03_to_2025_10","2025_10_to_2026_04","2026_04_to_2026_08",
)
BASELINES={"original_v3_dual_rotation_fixed",
 "passive_BTC_Spot_100_percent","passive_ETH_Spot_100_percent",
 "passive_50_BTC_50_ETH_Spot","cash_100_percent"}
COSTS={"conservative","stress","severe"}


def report():
    d=json.loads(EVIDENCE.read_text("utf8"))
    content={k:v for k,v in d.items() if k!="digest"}
    assert guard._digest(content)==d["digest"]==DIGEST
    return d


def test_result_digest_exact_and_global_research_boundary():
    r=report()
    assert r["schema"]=="nexus.portfolio-v3-500-source-six-regimes-vs-passive.v1"
    assert r["objective"]=="FALSIFY_FIXED_ORIGINAL_ROTATION_VS_PASSIVE_BASELINES"
    assert r["no_parameter_search"] is True
    assert r["source_previously_inspected_not_prospective"] is True
    assert r["original_portfolio_engine_reused_without_execution_changes"] is True
    assert r["original_engine_no_physical_stop"] is True
    assert r["no_exchange_order"] is True and r["live_enabled"] is False
    assert r["paper_eligible"] is False
    assert r["portfolio_initial_cash_per_era_usdt"]==500
    assert r["execution_fill_is_not_round_trip"] is True
    assert r["periods_overlap_for_Q1_cross_check_and_continuous_not_independent_samples"] is True


def test_six_original_physical_source_sha_and_existing_candidate_id_reconcile():
    r=report()
    assert r["source_original_parquet_sha256"]==PINNED_BYBIT_PARQUET_SHA256
    assert r["source_semantic_archive_sha256"]==ARCHIVE_SHA256
    config,digest=guard._load_contract(ROOT/guard.DEFAULT_CONFIG)
    assert r["original_candidate_contract_digest"]==digest
    assert r["original_pre_registered_fixed_candidate_id"]==guard.original.candidate_id(
        config["candidate"]["family"],config["candidate"]["params"])


def test_all_six_disjoint_halfyear_regimes_four_predeclared_benchmarks_and_costs():
    r=report()
    eras={k:v for k,v in r["periods"].items() if k in REGIMES}
    assert len(eras)==6
    for era in eras.values():
        assert era["each_approach_starts_at_500_USDT"] is True
        assert set(era["strategies"])==BASELINES
        for method,runs in era["strategies"].items():
            assert set(runs)==COSTS
            for label,out in runs.items():
                assert out["btc_fills"]+out["eth_fills"]==out["asset_fill_count"]
                assert out["paid_fees_usdt"]>=0
                assert out["min_cash_usdt"]>=0
                assert out["end_cash_usdt"]>=0
                assert out["end_cash_usdt"]==pytest.approx(
                    500+out["net_usdt"],abs=1e-6)
            if method=="cash_100_percent":
                assert all(row["net_usdt"]==0 and row["asset_fill_count"]==0
                           for row in runs.values())


def test_fixed_mechanism_fails_half_of_six_separate_periods_and_has_no_alpha_claim():
    r=report()
    selected=[r["periods"][name]["strategies"]
              ["original_v3_dual_rotation_fixed"]["conservative"] for name in REGIMES]
    assert [x["net_usdt"]>0 for x in selected]==[True,False,True,True,False,False]
    assert [x["asset_fill_count"] for x in selected]==[26,27,22,24,7,4]
    assert [x["net_usdt"] for x in selected]==[
        230.86441467,-60.31238593,184.72124778,
        158.98838602,-46.45442647,-99.58193912]


def test_fixed_q1_cross_check_reproduces_original_500_evidence():
    r=report()
    old=json.loads((ROOT/"docs/evidence/portfolio-v3-original-500-calibration-20261018/"
                    "fixed-dual-rotation-2025q1-original.json").read_text("utf8"))
    assert old["result_sha256"]==Q1_PRIOR
    assert r["original_Q1_reproduction_verification"] is True
    follow=(r["periods"]["2025_Q1_REPEAT_PRIOR_FIXED"]["strategies"]
            ["original_v3_dual_rotation_fixed"])
    assert follow["conservative"]["net_usdt"]==old["segments"]["2025_Q1_CONTINUOUS"]["conservative"]["net_pnl_usdt"]
    assert follow["stress"]["net_usdt"]==old["segments"]["2025_Q1_CONTINUOUS"]["stress"]["net_pnl_usdt"]
    assert follow["severe"]["net_usdt"]==old["segments"]["2025_Q1_CONTINUOUS"]["severe"]["net_pnl_usdt"]


def test_continuous_fixed_strategy_underperforms_passive_btc_and_half_half():
    strategies=report()["periods"]["2023_09_to_2026_08_CONTINUOUS"]["strategies"]
    original=strategies["original_v3_dual_rotation_fixed"]["conservative"]
    btc=strategies["passive_BTC_Spot_100_percent"]["conservative"]
    fifty=strategies["passive_50_BTC_50_ETH_Spot"]["conservative"]
    assert original["net_usdt"]==343.66115005
    assert original["max_drawdown_pct"]==34.43365449
    assert original["asset_fill_count"]==106
    assert btc["net_usdt"]==702.11337634
    assert fifty["net_usdt"]==382.01406091
    assert original["net_usdt"]<btc["net_usdt"]
    assert original["net_usdt"]<fifty["net_usdt"]
    assert strategies["cash_100_percent"]["conservative"]["net_usdt"]==0


def test_passive_return_difference_must_show_higher_passive_max_drawdown():
    strategies=report()["periods"]["2023_09_to_2026_08_CONTINUOUS"]["strategies"]
    rotation=strategies["original_v3_dual_rotation_fixed"]["conservative"]
    btc=strategies["passive_BTC_Spot_100_percent"]["conservative"]
    half=strategies["passive_50_BTC_50_ETH_Spot"]["conservative"]
    eth=strategies["passive_ETH_Spot_100_percent"]["conservative"]
    assert btc["max_drawdown_pct"]==53.44397804
    assert half["max_drawdown_pct"]==58.44468459
    assert eth["max_drawdown_pct"]==68.02878299
    assert rotation["max_drawdown_pct"]==34.43365449
    assert rotation["max_drawdown_pct"]<btc["max_drawdown_pct"]
    assert rotation["max_drawdown_pct"]<half["max_drawdown_pct"]
    # More passive absolute USDT P/L does NOT imply more risk-adjusted alpha.


def test_cost_stress_deterioration_reproducibly_non_improving_in_six_eras():
    r=report()
    for name in REGIMES:
        p=r["periods"][name]["strategies"]["original_v3_dual_rotation_fixed"]
        assert p["conservative"]["net_usdt"]>=p["stress"]["net_usdt"]
        assert p["stress"]["net_usdt"]>=p["severe"]["net_usdt"]


def test_overlapping_q1_and_eras_cannot_be_reported_as_additive_cash():
    r=report()["periods"]
    assert r["2023_09_to_2026_08_CONTINUOUS"]["start"]=="2023-09-01"
    assert r["2023_09_to_2026_08_CONTINUOUS"]["end"]=="2026-08-01"
    assert r["2025_Q1_REPEAT_PRIOR_FIXED"]["start"]=="2025-01-01"
    assert r["2025_Q1_REPEAT_PRIOR_FIXED"]["end"]=="2025-04-01"
    assert sum(r[k]["strategies"]["original_v3_dual_rotation_fixed"]
        ["conservative"]["net_usdt"] for k in REGIMES)!=pytest.approx(
        r["2023_09_to_2026_08_CONTINUOUS"]["strategies"]
        ["original_v3_dual_rotation_fixed"]["conservative"]["net_usdt"])


def test_old_execution_engine_is_not_modified_by_replay_module():
    source=(ROOT/"scripts/nexus_existing_portfolio_fixed_multiregime.py").read_text("utf8")
    for forbidden in ("run_search(","enumerate_candidates(","create_order(","place_order("):
        assert forbidden not in source
    assert "engine.exact_backtest(" in source
    assert "verify_pinned_market_files(archive)" in source
    assert source.index("verify_pinned_market_files(archive)")<source.index("engine.load_market(")
    assert "paper_eligible" in source and "live_enabled" in source


def test_source_verification_failure_prevents_any_market_read(monkeypatch,tmp_path):
    def rejected(_):
        raise RuntimeError("TAMPERED_OR_UNKNOWN_ARCHIVE")
    def forbidden(*args,**kwargs):
        raise AssertionError("market must not load before six original byte hashes")
    monkeypatch.setattr(replay,"verify_pinned_market_files",rejected)
    monkeypatch.setattr(replay.engine,"load_market",forbidden)
    with pytest.raises(RuntimeError,match="TAMPERED_OR_UNKNOWN_ARCHIVE"):
        replay.run(tmp_path/"missing",tmp_path/"should-not-exist.json")
    assert not (tmp_path/"should-not-exist.json").exists()
