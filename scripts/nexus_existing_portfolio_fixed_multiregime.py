"""Replay one frozen original 4h rotation candidate vs passive baselines.

Research-only diagnostic, never a qualified strategy or Demo dispatcher.
All six Bybit Spot raw source blobs are SHA-pinned before calling the
unchanged original physical cash execution simulator. Historical windows
are previously inspected, overlapping diagnostic splits are not an
independent OOS validation, and no candidate optimizer executes here.
"""
from __future__ import annotations
import argparse
from pathlib import Path
import json,hashlib
import numpy as np
import pandas as pd

from scripts import nexus_existing_portfolio_shared500_diagnostic as guard
import bybit_portfolio_search_v3 as engine
from scripts.nexus_strategy_finder_shared_cash_eval import verify_pinned_market_files
from nexus_demo_archive_replay import ARCHIVE_SHA256

ROOT=Path(__file__).resolve().parents[1]


def run(archive_root:Path,output_path:Path)->dict:
    root=ROOT
    archive=archive_root
    config,contract_sha=guard._load_contract(root/guard.DEFAULT_CONFIG)
    actual_sha=verify_pinned_market_files(archive)
    market=engine.load_market(archive,list(guard.SYMBOLS))
    guard._validate_source(market)
    c=config["candidate"]
    state=engine.build_structural_state(market,c)
    vol=engine.realized_vol(market["close"],c["params"]["vol_days"])
    weights=engine.construct_weights(state,vol,c)
    mask=engine._candidate_rebalance_mask(len(weights),c)
    zeros=np.zeros_like(weights)
    btc=np.zeros_like(weights);btc[:,0]=1
    eth=np.zeros_like(weights);eth[:,1]=1
    half=np.full_like(weights,.5)
    strategies={
      "original_v3_dual_rotation_fixed":(weights,mask),
      "passive_BTC_Spot_100_percent":(btc,None),
      "passive_ETH_Spot_100_percent":(eth,None),
      "passive_50_BTC_50_ETH_Spot":(half,None),
      "cash_100_percent":(zeros,None),
    }
    periods={
     "2023_09_to_2024_03":{"start":"2023-09-01","end":"2024-03-01"},
     "2024_03_to_2024_09":{"start":"2024-03-01","end":"2024-09-01"},
     "2024_09_to_2025_03":{"start":"2024-09-01","end":"2025-03-01"},
     "2025_03_to_2025_10":{"start":"2025-03-01","end":"2025-10-01"},
     "2025_10_to_2026_04":{"start":"2025-10-01","end":"2026-04-01"},
     "2026_04_to_2026_08":{"start":"2026-04-01","end":"2026-08-01"},
     "2025_Q1_REPEAT_PRIOR_FIXED":{"start":"2025-01-01","end":"2025-04-01"},
     "2023_09_to_2026_08_CONTINUOUS":{"start":"2023-09-01","end":"2026-08-01"},
    }
    evidence={
     "schema":"nexus.portfolio-v3-500-source-six-regimes-vs-passive.v1",
     "objective":"FALSIFY_FIXED_ORIGINAL_ROTATION_VS_PASSIVE_BASELINES",
     "no_parameter_search":True,
     "original_pre_registered_fixed_candidate_id":engine.candidate_id(c["family"],c["params"]),
     "original_candidate_contract_digest":contract_sha,
     "source_original_parquet_sha256":actual_sha,
     "source_semantic_archive_sha256":ARCHIVE_SHA256,
     "original_engine_source_sha256":hashlib.sha256(Path(engine.__file__).read_bytes()).hexdigest(),
     "source_previously_inspected_not_prospective":True,
     "periods_overlap_for_Q1_cross_check_and_continuous_not_independent_samples":True,
     "authoritative_price_source":"cached original signed Bybit Spot OHLC; not verified current Bybit order book",
     "original_engine_no_physical_stop":True,
     "original_portfolio_engine_reused_without_execution_changes":True,
     "portfolio_initial_cash_per_era_usdt":500,
     "execution_fill_is_not_round_trip":True,
     "no_exchange_order":True,"paper_eligible":False,"live_enabled":False,
     "profiles":config["execution"],"periods":{}
    }
    for name,dates in periods.items():
        out={}
        for label,(w,schedule) in strategies.items():
            row={}
            for cost,profile in config["execution"].items():
                result=engine.exact_backtest(market,w,dates,profile,rebalance_mask=schedule)
                if result["minimum_cash_usdt"] < -1e-7:
                    raise RuntimeError("CASH_ACCOUNT_INVARIANT_BROKEN")
                row[cost]={
                   "net_usdt":round(float(result["total_return"])*500,8),
                   "end_cash_usdt":round((1+float(result["total_return"]))*500,8),
                   "max_drawdown_pct":round(100*float(result["max_drawdown"]),8),
                   "asset_fill_count":int(result["fill_count"]),
                   "btc_fills":int(result["asset_fill_counts"][0]),
                   "eth_fills":int(result["asset_fill_counts"][1]),
                   "paid_fees_usdt":round(float(result["total_fees"]),8),
                   "turnover_x_start_cash":round(float(result["turnover"]),8),
                   "min_cash_usdt":round(float(result["minimum_cash_usdt"]),8),
                }
            out[label]=row
        evidence["periods"][name]={"start":dates["start"],"end":dates["end"],
           "each_approach_starts_at_500_USDT":True,"strategies":out}
        first=out["original_v3_dual_rotation_fixed"]
        relative={
          key:round(first["conservative"]["net_usdt"]-
                  out[key]["conservative"]["net_usdt"],6)
          for key in strategies if key!="original_v3_dual_rotation_fixed"
        }
        print("PARTITION",name, "rotation_normal",first["conservative"]["net_usdt"],
              "rotation_stress",first["stress"]["net_usdt"],
              "rotation_severe",first["severe"]["net_usdt"],
              "fills",first["conservative"]["asset_fill_count"],
              "relative_net_USDT",relative,flush=True)
    old=round(evidence["periods"]["2025_Q1_REPEAT_PRIOR_FIXED"]["strategies"]
        ["original_v3_dual_rotation_fixed"]["conservative"]["net_usdt"],8)
    assert old==8.43707258,"FROZEN_Q1_PRIOR_POSITIVE_MISMATCH"
    evidence["original_Q1_reproduction_verification"]=True
    evidence["digest"]=guard._digest(evidence)
    target=output_path
    if target.exists():raise RuntimeError("WRITE_ONCE_OUTPUT_EXISTS")
    target.write_text(json.dumps(evidence,sort_keys=True,indent=2,allow_nan=False)+"\n",encoding="utf8")
    print("EVIDENCE",json.dumps({"file":str(target),"sha256":hashlib.sha256(target.read_bytes()).hexdigest(),
        "digest":evidence["digest"],"regimes":len(periods),
        "strategies":len(strategies),"cash":500,"original_locked":True},
        sort_keys=True),flush=True)
    return evidence

def main()->int:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive-root",type=Path,required=True)
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()
    run(args.archive_root,args.output)
    return 0


if __name__=="__main__":
    raise SystemExit(main())
