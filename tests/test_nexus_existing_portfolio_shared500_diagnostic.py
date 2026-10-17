"""Fixed legacy portfolio-v3 500 USDT source/accounting gate tests.

No simulated market results are presented as pristine future evidence.
"""
from __future__ import annotations
from copy import deepcopy
import hashlib,json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from nexus_demo_archive_replay import ARCHIVE_SHA256
from scripts import nexus_existing_portfolio_shared500_diagnostic as mod
from scripts.nexus_strategy_finder_shared_cash_eval import PINNED_BYBIT_PARQUET_SHA256

ROOT=Path(__file__).resolve().parents[1]
EVIDENCE=ROOT/"docs/evidence/portfolio-v3-original-500-calibration-20261018/fixed-dual-rotation-2025q1-original.json"
RESULT_DIGEST="67c3817359fb4b9a225cc89c6abcd5a405b5602c4e3f20d822056fa1515ad746"


def fixed():
    return json.loads((ROOT/mod.DEFAULT_CONFIG).read_text("utf8"))


def altered(tmp_path,value):
    f=tmp_path/"test.json"
    f.write_text(json.dumps(value),encoding="utf8")
    return f


def test_frozen_contract_is_original_existing_v3_vocabulary_and_500():
    contract,digest=mod._load_contract(ROOT/mod.DEFAULT_CONFIG)
    assert len(digest)==64
    assert contract["candidate"]["family"]=="dual_rotation"
    assert contract["candidate"]["params"]["lookbacks"]==[30,90,180]
    assert set(contract["execution"])=={"conservative","stress","severe"}
    assert all(x["initial_cash"]==500 for x in contract["execution"].values())
    assert contract["legacy_manifest_claim_unverified_against_original_pinned_source"] is True
    assert contract["source_legacy_v3_manifest_claim"]!=ARCHIVE_SHA256


@pytest.mark.parametrize("alter",[
    lambda d:d["candidate"]["params"].update(lookbacks=[60,120,240]),
    lambda d:d["candidate"]["params"].update(target_vol=0.5),
    lambda d:d["execution"]["conservative"].update(initial_cash=10000),
    lambda d:d["execution"]["stress"].update(fee_bps=0),
    lambda d:d.update(live_trading_authority=True),
    lambda d:d.update(automatic_paper_promotion=True),
    lambda d:d["scope"].update(start="2025-02-01"),
    lambda d:d.update(source_original_archive_identity="a"*64),
])
def test_attempted_experiment_risk_live_parameter_or_window_edits_fail_closed(tmp_path,alter):
    config=fixed()
    alter(config)
    with pytest.raises(mod.OriginalPortfolioDiagnosticError):
        mod._load_contract(altered(tmp_path,config))


def test_bad_or_unknown_unlocked_market_never_enters_original_loader(monkeypatch,tmp_path):
    def wrong_source(_):
        raise mod.OriginalPortfolioDiagnosticError("source untrusted")
    def unexpected_loader(*_,**__):
        raise AssertionError("original market read before six raw SHA checks")
    monkeypatch.setattr(mod,"verify_pinned_market_files",wrong_source)
    monkeypatch.setattr(mod.original,"load_market",unexpected_loader)
    with pytest.raises(mod.OriginalPortfolioDiagnosticError,match="source untrusted"):
        mod.run(tmp_path)


def test_invalid_market_utc_grid_and_physical_price_envelope_are_rejected():
    times=pd.Series(pd.date_range("2023-01-01",periods=1100,freq="4h",tz="UTC"))
    price=np.full((1100,2),100.0)
    market={"timestamps":times,"symbols":["btc_usdt","eth_usdt"],
            "open":price.copy(),"high":price.copy(),
            "low":price.copy(),"close":price.copy()}
    invalid=deepcopy(market)
    invalid["timestamps"]=pd.Series(times.copy())
    invalid["timestamps"].iloc[44]=invalid["timestamps"].iloc[43]
    with pytest.raises(mod.OriginalPortfolioDiagnosticError,match="continuity"):
        mod._validate_source(invalid)
    invalid=deepcopy(market)
    invalid["high"][250,0]=99
    with pytest.raises(mod.OriginalPortfolioDiagnosticError,match="envelope"):
        mod._validate_source(invalid)
    invalid=deepcopy(market)
    invalid["symbols"]=["eth_usdt","btc_usdt"]
    with pytest.raises(mod.OriginalPortfolioDiagnosticError,match="ordering"):
        mod._validate_source(invalid)


def test_evidence_research_authority_schema_exact_source_and_digest():
    d=json.loads(EVIDENCE.read_text("utf8"))
    core={k:v for k,v in d.items() if k!="result_sha256"}
    assert mod._digest(core)==d["result_sha256"]==RESULT_DIGEST
    assert d["source_original_pinned_six_parquet_sha256"]==PINNED_BYBIT_PARQUET_SHA256
    assert d["source_canonical_archive_sha256"]==ARCHIVE_SHA256
    assert d["legacy_manifest_claim_sha256"]!=ARCHIVE_SHA256
    assert d["source_period_already_inspected"] is True
    assert d["no_new_strategy_created"] is True
    assert d["selection_based_on_historical_returns"] is False
    assert d["no_demo_qualification"] is True
    assert d["live_enabled"] is False and d["orders"]==0
    assert d["original_execution_no_stop_loss"] is True
    assert d["price_gap_risk_not_bounded"] is True


def test_fixed_2025_q1_cost_profile_results_and_monthly_independent_resets():
    d=json.loads(EVIDENCE.read_text("utf8"))
    values={
        "2025_Q1_CONTINUOUS":(8.43707258,7.90278653,7.1014304,9),
        "2025_01_RESET_500":(21.95447081,21.41930095,20.61658671,7),
        "2025_02_RESET_500":(-13.38485559,-13.88278306,-14.62874674,4),
        "2025_03_RESET_500":(0.0,0.0,0.0,0),
    }
    for part,(normal,stress,severe,fill_count) in values.items():
        group=d["segments"][part]
        assert group["conservative"]["net_pnl_usdt"]==normal
        assert group["stress"]["net_pnl_usdt"]==stress
        assert group["severe"]["net_pnl_usdt"]==severe
        assert group["conservative"]["asset_fill_events"]==fill_count
        for outcome in group.values():
            assert outcome["start_usdt"]==500
            assert outcome["closed_position_count"] is None
            assert outcome["mean_net_pnl_per_closed_position_usdt"] is None
            assert outcome["minimum_cash_usdt"]>=0
            assert abs(outcome["ending_cash_usdt"]-500-outcome["net_pnl_usdt"])<1e-5
            assert outcome["asset_fill_events"]==outcome["btc_fill_events"]+outcome["eth_fill_events"]
    # Independent month resets are NOT the single continuously held Q1 book:
    months=sum(d["segments"][x]["conservative"]["net_pnl_usdt"] for x in values if "RESET" in x)
    assert abs(months-d["segments"]["2025_Q1_CONTINUOUS"]["conservative"]["net_pnl_usdt"])>0.01


def test_report_has_no_missing_stop_price_or_fabricated_position_journal():
    d=json.loads(EVIDENCE.read_text("utf8"))
    assert "per_position_trades" not in d
    assert all(x["closed_position_count"] is None for s in d["segments"].values() for x in s.values())
    assert "no qualification" in "no qualification: source history is inspected"


def test_no_runtime_order_or_production_strategy_update():
    code=(ROOT/"scripts/nexus_existing_portfolio_shared500_diagnostic.py").read_text("utf8")
    assert "place_order(" not in code
    assert "create_order(" not in code
    assert "run_search(" not in code
    assert "enumerate_candidates(" not in code
    assert mod.SCHEMA
