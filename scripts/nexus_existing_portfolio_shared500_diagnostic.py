"""Physical fixed 500-USDT research calibration of EXISTING Bybit portfolio v3.

Do not construct a new rotation engine. This bridge invokes only existing
bybit_portfolio_search_v3 build_structural_state -> construct_weights ->
exact_backtest with its original globally anchored 4h scheduled rebalance.
The historical window and one old candidate were frozen before evaluating
the Q1 evidence; no search/selection/re-ranking or Demo qualification.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

import bybit_portfolio_search_v3 as original
from nexus_demo_archive_replay import ARCHIVE_SHA256
from scripts.nexus_strategy_finder_shared_cash_eval import (
    verify_pinned_market_files,write_once
)

SCHEMA="nexus.portfolio-original-engine-shared500-calibration-result.v1"
CONTRACT_SCHEMA="nexus.portfolio-original-engine-shared500-fixed-calibration.v1"
DEFAULT_CONFIG=Path("research/portfolio_existing_engine_shared500_calibration_v1.json")
ROOT=Path(__file__).resolve().parents[1]
SYMBOLS=("btc_usdt","eth_usdt")


class OriginalPortfolioDiagnosticError(ValueError):
    pass


def _digest(obj:Any)->str:
    return hashlib.sha256(
        json.dumps(obj,sort_keys=True,separators=(",",":"),allow_nan=False).encode()
    ).hexdigest()


def _load_contract(path:Path)->tuple[dict[str,Any],str]:
    if not isinstance(path,Path) or path.is_symlink() or not path.is_file():
        raise OriginalPortfolioDiagnosticError("no safe fixed portfolio config")
    content=path.read_bytes()
    if not 100<=len(content)<=16_384:
        raise OriginalPortfolioDiagnosticError("invalid fixed portfolio config size")
    try:
        config=json.loads(content.decode("utf8"))
    except (ValueError,UnicodeError) as exc:
        raise OriginalPortfolioDiagnosticError("invalid fixed portfolio config JSON") from exc
    if (type(config) is not dict or
        set(config)!={"schema","research_only","paper_only","live_trading_authority",
             "automatic_paper_promotion","legacy_execution_engine","legacy_experiment",
             "source_authentication","source_original_archive_identity",
             "source_legacy_v3_manifest_claim",
             "legacy_manifest_claim_unverified_against_original_pinned_source",
             "model","candidate","scope","execution","comparison_policy",
             "qualification_authority"} or
        config["schema"]!=CONTRACT_SCHEMA or
        config["research_only"] is not True or config["paper_only"] is not True or
        config["live_trading_authority"] is not False or
        config["automatic_paper_promotion"] is not False or
        config["qualification_authority"] is not False or
        config["legacy_execution_engine"]!="bybit_portfolio_search_v3.exact_backtest" or
        config["legacy_experiment"]!="experiments/bybit_portfolio_search_v3.json" or
        config["source_authentication"]!="six_exact_local_immutable_Bybit_Spot_source_sha256" or
        config["source_original_archive_identity"]!=ARCHIVE_SHA256 or
        config["legacy_manifest_claim_unverified_against_original_pinned_source"] is not True or
        config["model"]!="fixed_existing_dual_rotation_not_a_new_strategy" or
        config["comparison_policy"]!="no_parameter_tuning_or_selection_after_observed_outcome"):
        raise OriginalPortfolioDiagnosticError("portfolio config not frozen as research-only")
    candidate=config["candidate"]
    expected={
        "family":"dual_rotation",
        "params":{
            "lookbacks":[30,90,180],"absolute_days":90,
            "ma_filter_days":0,"minimum_absolute_return":0,
            "allocation":"winner","vol_days":30,"target_vol":0.3,
            "rebalance_days":7,"quantum":0.25,
        },
    }
    if candidate!=expected or config["scope"]!={"start":"2025-01-01",
            "end":"2025-04-01","historical_preinspected":True}:
        raise OriginalPortfolioDiagnosticError("unreviewed rotation variant or evaluation window")
    profiles={
        "conservative":{"initial_cash":500,"fee_bps":10,"slippage_bps":5},
        "stress":{"initial_cash":500,"fee_bps":15,"slippage_bps":10},
        "severe":{"initial_cash":500,"fee_bps":25,"slippage_bps":15},
    }
    if config["execution"]!=profiles:
        raise OriginalPortfolioDiagnosticError("unreviewed shared-cash fees or capital")
    legacy=ROOT/"experiments"/"bybit_portfolio_search_v3.json"
    if not legacy.is_file():
        raise OriginalPortfolioDiagnosticError("original portfolio v3 manifest required")
    legacy_cfg=json.loads(legacy.read_text(encoding="utf8"))
    if (legacy_cfg["experiment_id"]!="bybit_portfolio_search_v3_2026-08-04" or
        legacy_cfg["dataset"]["archive_sha256"]!=config["source_legacy_v3_manifest_claim"] or
        legacy_cfg["dataset"]["archive_sha256"]==ARCHIVE_SHA256):
        raise OriginalPortfolioDiagnosticError("legacy manifest identity or provenance discrepancy changed")
    # The selected baseline must be a genuine member of the old v3 search
    # vocabulary. This does NOT run old search, nor rank a new candidate.
    section=legacy_cfg["search"]
    params=candidate["params"]
    if (params["lookbacks"] not in section["dual_rotation"]["lookback_sets"] or
        params["absolute_days"] not in section["dual_rotation"]["absolute_days"] or
        params["ma_filter_days"] not in section["dual_rotation"]["ma_filter_days"] or
        params["minimum_absolute_return"] not in section["dual_rotation"]["minimum_absolute_return"] or
        params["allocation"] not in section["dual_rotation"]["allocation"] or
        params["vol_days"] not in section["risk"]["vol_days"] or
        params["target_vol"] not in section["risk"]["target_vol"] or
        params["rebalance_days"] not in section["risk"]["rebalance_days"] or
        params["quantum"]!=section["risk"]["quantum"]):
        raise OriginalPortfolioDiagnosticError("baseline is not one original fixed search candidate")
    return config,_digest(config)


def _validate_source(market:dict[str,Any])->None:
    if market.get("symbols")!=list(SYMBOLS):
        raise OriginalPortfolioDiagnosticError("wrong underlying spot pair ordering")
    times=pd.to_datetime(market["timestamps"],utc=True)
    if (len(times)<1000 or times.duplicated().any() or
        not times.is_monotonic_increasing or
        not (times.diff().dropna()==pd.Timedelta(hours=4)).all()):
        raise OriginalPortfolioDiagnosticError("original spot portfolio 4h UTC continuity failed")
    for key in ("open","high","low","close"):
        value=np.asarray(market[key],dtype=float)
        if value.shape!=(len(times),2) or not np.isfinite(value).all() or (value<=0).any():
            raise OriginalPortfolioDiagnosticError("invalid verified spot OHLC "+key)
    op,hi,lo,cl=(market[x] for x in ("open","high","low","close"))
    if ((hi<np.maximum(np.maximum(op,cl),lo)).any()
        or (lo>np.minimum(np.minimum(op,cl),hi)).any()):
        raise OriginalPortfolioDiagnosticError("original market price envelope invalid")
    if (times.iloc[0]>pd.Timestamp("2023-01-01T00:00:00Z") or
        times.iloc[-1]<pd.Timestamp("2025-04-01T00:00:00Z")):
        raise OriginalPortfolioDiagnosticError("source lacks 180-day minimum causal warmup")


def run(archive_root:Path,config_path:Path=ROOT/DEFAULT_CONFIG)->dict[str,Any]:
    config,config_digest=_load_contract(config_path)
    # No disk market read or strategy ranking until all 6 physical files attest.
    source_sha=verify_pinned_market_files(archive_root)
    market=original.load_market(archive_root,list(SYMBOLS))
    _validate_source(market)
    candidate=config["candidate"]
    old_id=original.candidate_id(candidate["family"],candidate["params"])
    structure=original.build_structural_state(market,candidate)
    risk=original.realized_vol(market["close"],candidate["params"]["vol_days"])
    weights=original.construct_weights(structure,risk,candidate)
    if (weights.shape!=market["close"].shape or
        not np.isfinite(weights).all() or (weights<0).any() or
        (weights.sum(axis=1)>1.0000000001).any()):
        raise OriginalPortfolioDiagnosticError("invalid original long-only portfolio allocation")
    schedule=original._candidate_rebalance_mask(len(weights),candidate)
    segments={
        "2025_Q1_CONTINUOUS":{"start":"2025-01-01","end":"2025-04-01"},
        "2025_01_RESET_500":{"start":"2025-01-01","end":"2025-02-01"},
        "2025_02_RESET_500":{"start":"2025-02-01","end":"2025-03-01"},
        "2025_03_RESET_500":{"start":"2025-03-01","end":"2025-04-01"},
    }
    trials={}
    for part,dates in segments.items():
        per_profile={}
        for label,profile in config["execution"].items():
            out=original.exact_backtest(market,weights,dates,profile,
                                        rebalance_mask=schedule)
            if (out["minimum_cash_usdt"] < -1e-7 or
                out["fill_count"]<0 or out["total_fees"]<0 or
                not np.isfinite(list(out.values())).all() or
                len(out["asset_fill_counts"])!=2):
                raise OriginalPortfolioDiagnosticError("original portfolio cash accounting failed")
            per_profile[label]={
                "start_usdt":500.0,
                "ending_cash_usdt":round(500*(1+out["total_return"]),8),
                "net_pnl_usdt":round(500*out["total_return"],8),
                "return_pct":round(100*out["total_return"],8),
                "max_drawdown_pct":round(100*out["max_drawdown"],8),
                "asset_fill_events":out["fill_count"],
                "btc_fill_events":out["asset_fill_counts"][0],
                "eth_fill_events":out["asset_fill_counts"][1],
                "fees_usdt":round(out["total_fees"],8),
                "turnover_multiple":round(out["turnover"],8),
                "rebalance_event_count":out["rebalance_event_count"],
                "minimum_cash_usdt":round(out["minimum_cash_usdt"],8),
                "mean_net_pnl_per_closed_position_usdt":None,
                "closed_position_count":None,
                "note":"Fills are executions, not round-trips. Original v3 does not emit a per-position trade journal.",
            }
        trials[part]=per_profile
    result={
        "schema":SCHEMA,
        "status":"ORIGINAL_ROTATION_ENGINE_FIXED_SHARED500_HISTORICAL_DIAGNOSTIC_ONLY",
        "source_original_pinned_six_parquet_sha256":source_sha,
        "source_canonical_archive_sha256":ARCHIVE_SHA256,
        "legacy_manifest_claim_sha256":config["source_legacy_v3_manifest_claim"],
        "legacy_manifest_claim_not_current_verified_archive_sha":True,
        "source_period_already_inspected":True,
        "original_engine_module_sha256":hashlib.sha256(
            Path(original.__file__).read_bytes().replace(b"\r\n",b"\n")
        ).hexdigest(),
        "existing_candidate_id":old_id,
        "existing_candidate":candidate,
        "fixed_config_digest":config_digest,
        "source_symbols":list(SYMBOLS),
        "timeframe":"hour4",
        "source_close_bars":len(market["timestamps"]),
        "exact_existing_engine_not_rewritten":True,
        "selection_based_on_historical_returns":False,
        "no_minimum_trade_count_gate":True,
        "shared_wallet_initial_cash_usdt":500,
        "no_new_strategy_created":True,
        "three_monthly_resets_not_continuous_account":True,
        "original_execution_no_stop_loss":True,
        "price_gap_risk_not_bounded":True,
        "no_demo_qualification":True,
        "automatic_paper_promotion":False,"live_enabled":False,"orders":0,
        "segments":trials,
    }
    result["result_sha256"]=_digest(result)
    return result


def main()->int:
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--archive-root",type=Path,required=True)
    p.add_argument("--output",type=Path,required=True)
    args=p.parse_args()
    obj=run(args.archive_root)
    write_once(args.output,obj)
    print(json.dumps({
        "fixed_candidate":obj["existing_candidate_id"],
        "result_sha256":obj["result_sha256"],
        "segments":{name:{profile:{"net_usdt":v["net_pnl_usdt"],
                         "asset_fills":v["asset_fill_events"]}
                       for profile,v in modes.items()}
                    for name,modes in obj["segments"].items()},
        "automatic_paper_promotion":False,"live_enabled":False,
    },sort_keys=True))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
