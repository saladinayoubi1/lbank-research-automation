"""Evaluate frozen v3 20% prior-closed-4h risk switch on original market only.

This does NOT optimize thresholds, forecast future profits, or permit Demo.
Original v3 passive/cost accounting stays an untouched direct comparator.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import bybit_portfolio_search_v3 as engine
from nexus_demo_archive_replay import ARCHIVE_SHA256
from research.portfolio_v3_original_fill_journal import fifo_journal
from scripts.nexus_existing_portfolio_shared500_diagnostic import (
    ROOT,DEFAULT_CONFIG,_load_contract,_validate_source
)
from scripts.nexus_strategy_finder_shared_cash_eval import (
    verify_pinned_market_files,write_once
)

SCHEMA="nexus.portfolio-v3-causal-dd20-source-cost-diagnostic.v1"
RISK_POLICY={
    "schema":"nexus.portfolio-v3-causal-close-dd20-nextopen.v1",
    "max_closed_bar_drawdown_fraction":0.20,
    "halt_rest_of_research_period":True,
    "exit":"next_4h_open_sell_first_no_reentry",
    "live_authority":False,
}
SCOPES={
    "2025_Q1_PREVIOUSLY_INSPECTED":{"start":"2025-01-01","end":"2025-04-01"},
    "2023_2026_CONTINUOUS_PREVIOUSLY_INSPECTED":{"start":"2023-09-01","end":"2026-08-01"},
}


def _digest(obj:dict)->str:
    return hashlib.sha256(json.dumps(
        obj,sort_keys=True,separators=(",",":"),allow_nan=False
    ).encode()).hexdigest()


def run(archive_root:Path)->dict:
    cfg,config_sha=_load_contract(ROOT/DEFAULT_CONFIG)
    source_files=verify_pinned_market_files(archive_root)
    market=engine.load_market(archive_root,["btc_usdt","eth_usdt"])
    _validate_source(market)
    candidate=cfg["candidate"]
    state=engine.build_structural_state(market,candidate)
    vol=engine.realized_vol(market["close"],candidate["params"]["vol_days"])
    weights=engine.construct_weights(state,vol,candidate)
    mask=engine._candidate_rebalance_mask(len(weights),candidate)
    out={
        "schema":SCHEMA,
        "source_six_raw_sha256":source_files,
        "source_semantic_sha256":ARCHIVE_SHA256,
        "engine_module_sha256":hashlib.sha256(Path(engine.__file__).read_bytes().replace(
            b"\r\n",b"\n")).hexdigest(),
        "original_reviewed_fixed_candidate_id":engine.candidate_id(
            candidate["family"],candidate["params"]),
        "original_fixed_config_digest":config_sha,
        "one_shared_spot_cash_initial_usdt":500.0,
        "risk_policy_exact_frozen":RISK_POLICY,
        "source_already_inspected_not_future_holdout":True,
        "decision_after_completed_4h_candle":True,
        "forced_exit_only_at_actual_next_4h_open":True,
        "gap_loss_can_exceed_20pct":True,
        "single_threshold_fixed_before_this_risk_policy_replay":True,
        "prior_historical_original_drawdown_already_known":True,
        "threshold_selection_not_prospective_blind":True,
        "not_an_auto_trade_approval":True,
        "no_true_exchange_depth_proof":True,
        "no_new_strategy_generated":True,
        "paper_eligible":False,"live_enabled":False,"real_orders":0,
        "scopes":{},
    }
    for name,period in SCOPES.items():
        rows={}
        for label,profile in cfg["execution"].items():
            baseline=engine.exact_backtest(
                market,weights,period,profile,rebalance_mask=mask)
            tape={}
            guarded=engine.exact_backtest(
                market,weights,period,profile,rebalance_mask=mask,
                risk_policy=RISK_POLICY,fill_trace=tape,
            )
            fifo=fifo_journal(tape,guarded)
            if (abs(fifo["net_profit_usdt"]-guarded["total_return"]*500)>2e-6
                or abs(fifo["total_fees_usdt"]-guarded["total_fees"])>2e-6
                or abs(fifo["observed_max_drawdown_pct"]-100*guarded["max_drawdown"])>1e-7):
                raise RuntimeError("original source risk accounting mismatch")
            rows[label]={
                "unmodified_original":{"net_pnl_usdt":round(500*baseline["total_return"],8),
                    "max_drawdown_pct":round(100*baseline["max_drawdown"],8),
                    "fill_events":baseline["fill_count"],
                    "model_fees_usdt":round(baseline["total_fees"],8)},
                "causal_risk20":{"net_pnl_usdt":round(500*guarded["total_return"],8),
                    "max_drawdown_pct":round(100*guarded["max_drawdown"],8),
                    "fill_events":guarded["fill_count"],
                    "model_fees_usdt":round(guarded["total_fees"],8),
                    "fifo_matched_lot_segments":fifo["closed_fifo_lot_segments"],
                    "fifo_winning_segments":fifo["winning_fifo_lot_segments"],
                    "fifo_average_net_per_matched_segment_usdt":
                        fifo["mean_net_pnl_per_fifo_matched_segment_usdt"],
                    "monthly_fifo_exit":fifo["monthly_by_fifo_exit_month"],
                    "risk_audit":guarded["causal_risk_audit"]},
                "independent_fifo_digest":fifo["digest"],
            }
        out["scopes"][name]={
            "period":period,
            "profiles":rows,
            "independent_500_usdt_period_reset":True,
        }
    out["digest"]=_digest(out)
    return out


def main()->int:
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--archive-root",required=True,type=Path)
    p.add_argument("--output",required=True,type=Path)
    args=p.parse_args()
    result=run(args.archive_root)
    write_once(args.output,result)
    print(json.dumps({
        "digest":result["digest"],
        "model":"causal_post_4h_close_20pct_next_open_no_reentry",
        "scopes":{k:{p:{"original_net":v["unmodified_original"]["net_pnl_usdt"],
                             "causal_net":v["causal_risk20"]["net_pnl_usdt"],
                             "causal_dd_pct":v["causal_risk20"]["max_drawdown_pct"],
                             "triggered_at":v["causal_risk20"]["risk_audit"][
                                 "trigger_observed_after_close_utc"]}
                        for p,v in t["profiles"].items()}
                  for k,t in result["scopes"].items()},
        "paper_eligible":False,"live_enabled":False,
    },sort_keys=True))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
