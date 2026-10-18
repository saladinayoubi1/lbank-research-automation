"""Opt-in original-v3 real market exact-fill journal, no trading connector.

Reuses source-pinned original Bybit v3 500-USDT candidate and the original
exact_backtest; only captures optional per-fill trace and independently
reconciles positions, shared cash, fees, and marked drawdown. No entry changes,
risk-filter tuning, paper qualification, or live exchange call.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import bybit_portfolio_search_v3 as engine
from nexus_demo_archive_replay import ARCHIVE_SHA256
from research.portfolio_v3_original_fill_journal import fifo_journal
from scripts.nexus_strategy_finder_shared_cash_eval import (
    verify_pinned_market_files,write_once
)
from scripts import nexus_existing_portfolio_shared500_diagnostic as fixed

ROOT=Path(__file__).resolve().parents[1]
SCOPES={
    "2025Q1":{"start":"2025-01-01","end":"2025-04-01"},
    "2023_2026_CONTINUOUS":{"start":"2023-09-01","end":"2026-08-01"},
}
KNOWN_NORMAL={
    "2025Q1":(8.43707258,9,6.74354902),
    "2023_2026_CONTINUOUS":(343.66115005,106,34.43365449),
}


def run(archive_root:Path,scope:str)->dict:
    if scope not in SCOPES:
        raise ValueError("only the original two frozen research periods allowed")
    cfg,config_digest=fixed._load_contract(ROOT/fixed.DEFAULT_CONFIG)
    physical_source=verify_pinned_market_files(archive_root)
    market=engine.load_market(archive_root,list(fixed.SYMBOLS))
    fixed._validate_source(market)
    c=cfg["candidate"]
    state=engine.build_structural_state(market,c)
    risk=engine.realized_vol(market["close"],c["params"]["vol_days"])
    weights=engine.construct_weights(state,risk,c)
    mask=engine._candidate_rebalance_mask(len(weights),c)
    trial={}
    metrics={}
    for label,profile in cfg["execution"].items():
        tape={}
        original=engine.exact_backtest(
            market,weights,SCOPES[scope],profile,
            rebalance_mask=mask,fill_trace=tape,
        )
        assert original["minimum_cash_usdt"]>=-1e-9
        journal=fifo_journal(tape,original)
        trial[label]=journal
        metrics[label]=original
    expected_net,expected_fills,expected_dd=KNOWN_NORMAL[scope]
    actual=metrics["conservative"]
    if (round(500*actual["total_return"],8)!=expected_net
        or actual["fill_count"]!=expected_fills
        or round(100*actual["max_drawdown"],8)!=expected_dd):
        raise ValueError("recording changed original exact engine historical metrics")
    report={
        "schema":"nexus.portfolio-v3-fixed-500-original-source-journal-audit.v1",
        "fixed_old_strategy_id":engine.candidate_id(c["family"],c["params"]),
        "same_immutable_reviewed_candidate":True,
        "source_six_raw_parquet_sha256":physical_source,
        "source_semantic_sha256":ARCHIVE_SHA256,
        "original_v3_engine_module_sha256":hashlib.sha256(
            Path(engine.__file__).read_bytes().replace(b"\r\n",b"\n")
        ).hexdigest(),
        "scope":scope,
        "scored_period":SCOPES[scope],
        "original_fixed_config_digest":config_digest,
        "capital_initial_shared_usdt":500,
        "source_historical_preinspected_not_untouched_OOS":True,
        "no_original_execution_policy_change":True,
        "per_trade_physical_hard_stop_absent":True,
        "max_drawdown_enforced_as_live_stop":False,
        "profitable_future_claim":False,
        "paper_eligible":False,"live_enabled":False,"orders":0,
        "original_exact_metric_summaries":metrics,
        "reconciled_trace_journals":trial,
    }
    report["report_digest"]=hashlib.sha256(json.dumps(
        report,sort_keys=True,separators=(",",":"),allow_nan=False
    ).encode()).hexdigest()
    return report


def main()->int:
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--archive-root",type=Path,required=True)
    ap.add_argument("--scope",choices=list(SCOPES),required=True)
    ap.add_argument("--output",type=Path,required=True)
    args=ap.parse_args()
    output=run(args.archive_root,args.scope)
    write_once(args.output,output)
    print(json.dumps({
        "digest":output["report_digest"],
        "scope":args.scope,
        "conservative_pnl_usdt":output["reconciled_trace_journals"]["conservative"]["net_profit_usdt"],
        "original_buy_sell_fill_events":output["reconciled_trace_journals"]["conservative"]["exact_original_buy_sell_fill_events"],
        "fifo_closed_lot_segments":output["reconciled_trace_journals"]["conservative"]["closed_fifo_lot_segments"],
        "fifo_mean_net_profit_usdt":output["reconciled_trace_journals"]["conservative"]["mean_net_pnl_per_fifo_matched_segment_usdt"],
        "paper_eligible":False,"live_enabled":False,"orders":0,
    },sort_keys=True))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
