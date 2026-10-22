"""Research-only sensitivity of fixed cash reserve fractions on pinned 47 MR40 LONG trades.

The observed data and exact trade signals are unchanged. This DOES NOT select
a new sizing policy, execute an order, or certify performance out of sample.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from decimal import Decimal as D
from pathlib import Path

from research.nexus_mr40_independent_closed_signal_v1 import (
    canon, frozen_rows, oracle_ledger, ROWS_SHA, LEDGER_SHA, STEP
)
from research.nexus_mr40_frozen_47_spot_fee_audit_v1 import (
    get_pairs, match_frozen_comparator, START, factor
)
from research.nexus_mr40_all47_intratrade_ohlc_equity_bounds_v1 import (
    dd_fraction, intrapos_risk
)

PROTOCOL = "nexus.mr40.position_fraction_open_proxy_risk_sensitivity_v1"
FRACTIONS = (D("0.25"), D("0.50"), D("0.75"), D("1.00"))
FEE = D("0.001")
PREV_FEE_SHA = "074b74042e62fab437e2d49ce4d8d71c401e301a1d0ad727ed2704a4b012de3d"
PREV_RISK_SHA = "c401f4920d8f51abe2ed77c11aa3a9616df8cde2d0dd958d7dfd0a59c6cac051"
PREV_RISK_DIGEST = "6ec8b21dc24ef1de962c4b439f870420493cecab570c53311eb836dbe7240ba9"
GROUP = "OFFICIAL_SPOT_VIP0_TAKER_REFERENCE"


def possible_equity(quote_before, fraction, entry, price, fee=FEE):
    """Cash reserve plus liquidation at price after both illustrative taker fees."""
    if not (D(0) < fraction <= D(1) and entry>0 and price>0 and D(0)<=fee<D(1)):
        raise ValueError("unsafe_sizing_or_price")
    return quote_before*((D(1)-fraction)+fraction*(D(1)-fee)**2*price/entry)


def evaluate_fraction(rows,pairs,fraction,fee=FEE):
    if not pairs or fraction not in FRACTIONS:
        raise ValueError("fraction_or_positions_not_preregistered")
    cash=START
    realized_peak=START
    preceding_high_peak=START
    high_first_peak=START
    realized_dd=D(0)
    bound_lower=D(0)
    bound_upper=D(0)
    lifetime_bars=0
    for pair in pairs:
        ent=pair["entry_next_open_index"]
        ex=pair["exit_next_open_index"]
        if not (0<=ent<ex<len(rows)):
            raise ValueError("unexpected_position_window")
        if rows[ent][0]!=pair["entry_next_open_ms"] or rows[ex][0]!=pair["exit_next_open_ms"]:
            raise ValueError("wrong_position_timestamps")
        entry=D(pair["entry_next_open_price"])
        exit_price=D(pair["exit_next_open_price"])
        if entry!=D(str(rows[ent][1])) or exit_price!=D(str(rows[ex][1])):
            raise ValueError("source_next_open_changed")
        before=cash
        for j in range(ent,ex):
            k=rows[j]
            if k[0]!=rows[ent][0]+(j-ent)*STEP:
                raise ValueError("missing_market_bar_in_position")
            high=D(str(k[2]))
            low=D(str(k[3]))
            op=D(str(k[1]))
            close=D(str(k[4]))
            if not (low>0 and low<=min(op,close) and high>=max(op,close)):
                raise ValueError("corrupt_ohlcv_high_or_low")
            hi_eq=possible_equity(before,fraction,entry,high,fee)
            lo_eq=possible_equity(before,fraction,entry,low,fee)
            # High from a completed PRIOR candle is guaranteed to precede
            # the low of the CURRENT candle, even without intra-bar sequencing.
            bound_lower=max(bound_lower,dd_fraction(preceding_high_peak,lo_eq))
            preceding_high_peak=max(preceding_high_peak,hi_eq)
            # Worst chronological arrangement of same-bar extremes for DD.
            high_first_peak=max(high_first_peak,hi_eq)
            bound_upper=max(bound_upper,dd_fraction(high_first_peak,lo_eq))
            lifetime_bars+=1
        # Already flat at exit candle OPEN, so never use exit candle high/low.
        cash=possible_equity(before,fraction,entry,exit_price,fee)
        realized_peak=max(realized_peak,cash)
        realized_dd=max(realized_dd,dd_fraction(realized_peak,cash))
        preceding_high_peak=max(preceding_high_peak,cash)
        high_first_peak=max(high_first_peak,cash)
        bound_lower=max(bound_lower,dd_fraction(preceding_high_peak,cash))
        bound_upper=max(bound_upper,dd_fraction(high_first_peak,cash))
    if not (D(0)<=realized_dd<=bound_lower<=bound_upper<=D(1)):
        raise ValueError("invalid_risk_envelope")
    return {
        "fraction_of_quoted_capital":str(fraction),
        "positions":len(pairs),
        "held_4h_bars":lifetime_bars,
        "initial_quote_usdt":str(START),
        "compound_exit_equity_usdt":str(cash),
        "compound_exit_net_return_pct":str((cash/START-D(1))*D(100)),
        "realized_only_max_dd_pct":str(realized_dd*D(100)),
        "prior_high_to_current_low_global_OHLC_dd_lower_pct":str(bound_lower*D(100)),
        "adversarial_same_bar_high_first_OHLC_dd_upper_pct":str(bound_upper*D(100)),
        "intrabar_high_low_order_unobserved":True,
        "fees_are_public_reference_not_private_account_actual":True,
        "not_executable_fill_or_future_proof":True,
    }


def locked_protocol(config):
    if not isinstance(config,dict) or not all(
        isinstance(config.get(name),dict)
        for name in ("source","fixed_scenarios","safety","verification")
    ):
        raise ValueError("preregistered_fraction_protocol_changed")
    if (
        config.get("schema")!=PROTOCOL
        or config["source"]["market_rows_sha256"]!=ROWS_SHA
        or config["source"]["ledger_sha256"]!=LEDGER_SHA
        or config["source"]["original_full_all47_fee_audit_file_sha256"]!=PREV_FEE_SHA
        or config["source"]["original_full_all47_OHLC_risk_file_sha256"]!=PREV_RISK_SHA
        or config["source"]["original_risk_report_digest"]!=PREV_RISK_DIGEST
        or config["source"]["n_trades"]!=47
        or tuple(config["fixed_scenarios"]["position_fraction_of_current_total_quote_capital"])!=tuple(str(f) for f in FRACTIONS)
        or config["fixed_scenarios"]["start_quote_usdt"]!="500"
        or config["safety"]["orders"]!=0
        or config["safety"]["live"] is not False
        or config["safety"]["promote"] is not False
        or config["verification"]["no_optimization_score_or_best_fraction_ranking"] is not True
    ):
        raise ValueError("preregistered_fraction_protocol_changed")


def verify_old_reports(old_fee,old_risk,pairs):
    if old_fee.get("verified_pairs")!=[{**row,"no_real_order_or_fill":True} for row in pairs]:
        raise ValueError("unmatched_old_47_fee_pairs")
    if (old_risk.get("market_source_sha256")!=ROWS_SHA
        or old_risk.get("source_splits")!={"train":25,"evaluation":22,"total":47}):
        raise ValueError("old_risk_source_changed")
    return old_fee,old_risk


def compare_reference(current,fee_record,risk_record):
    """For fraction 1.00, preserve exact earlier VIP0 fee and OHLC DD outcome."""
    checks=[
        ("compound_exit_equity_usdt",fee_record["closed_trade_equity_end_usdt"]),
        ("realized_only_max_dd_pct",fee_record["max_closed_trade_only_drawdown_pct"]),
        ("prior_high_to_current_low_global_OHLC_dd_lower_pct",risk_record["guaranteed_minimum_drawdown_from_prior_4h_highs_to_lows_pct"]),
        ("adversarial_same_bar_high_first_OHLC_dd_upper_pct",risk_record["adversarial_high_before_low_max_dd_upper_bound_pct"]),
    ]
    for key,target in checks:
        if abs(D(current[key])-D(target))>D("1e-18"):
            raise ValueError("original_full_invested_fee_or_floating_risk_parity_failed_"+key)
    if current["held_4h_bars"]!=risk_record["total_held_4h_bars"]:
        raise ValueError("original_position_duration_parity_failed")


def run(protocol,source_dir,ledger,fee_report,risk_report,out):
    if out.exists():
        raise ValueError("refuse_overwrite")
    raw_protocol=protocol.read_bytes()
    locked_protocol(json.loads(raw_protocol))
    fee_bytes=fee_report.read_bytes()
    risk_bytes=risk_report.read_bytes()
    if (hashlib.sha256(fee_bytes).hexdigest()!=PREV_FEE_SHA
        or hashlib.sha256(risk_bytes).hexdigest()!=PREV_RISK_SHA):
        raise ValueError("source_audit_hash_not_pinned")
    old_fee=json.loads(fee_bytes)
    old_risk=json.loads(risk_bytes)
    risk_digest=old_risk.pop("digest")
    if risk_digest!=PREV_RISK_DIGEST or hashlib.sha256(canon(old_risk)).hexdigest()!=risk_digest:
        raise ValueError("prior_risk_logical_content_changed")
    rows=frozen_rows(source_dir)
    pairs=get_pairs(rows)
    match_frozen_comparator(pairs,oracle_ledger(ledger))
    verify_old_reports(old_fee,old_risk,pairs)
    cohorts={
        "train_2023_2024":[p for p in pairs if p["window"]=="train"],
        "evaluation_2025_2026oct19":[p for p in pairs if p["window"]=="evaluation"],
        "combined_2023_2026oct19":pairs,
    }
    groups={}
    for k,sub in cohorts.items():
        groups[k]={}
        fee_key=("combined_chronological_2023_2026oct19" if k.startswith("combined") else k)
        for fraction in FRACTIONS:
            measure=evaluate_fraction(rows,sub,fraction)
            if fraction==D(1):
                compare_reference(measure,
                                  old_fee["groups"][fee_key][GROUP],
                                  old_risk["groups"][fee_key][GROUP])
            groups[k][str(fraction)]=measure
    result={
        "schema":"nexus.mr40.preregistered_fixed_cash_fraction_risk_envelope.results.v1",
        "protocol_sha256":hashlib.sha256(raw_protocol).hexdigest(),
        "market_rows_sha256":ROWS_SHA,
        "oracle_ledger_sha256":LEDGER_SHA,
        "baseline_fee_fullfile_sha256":PREV_FEE_SHA,
        "baseline_risk_fullfile_sha256":PREV_RISK_SHA,
        "same_frozen_47_MR40_events_and_chronology":True,
        "public_spot_VIP0_taker_fee_each_side_reference":"0.001",
        "initial_quote_usdt":"500",
        "groups":groups,
        "numeric_scenarios_precommitted_not_selected_after_outcome":True,
        "not_sizing_optimization_or_recommendation":True,
        "source_currently_unseen_forward_risk_proof":False,
        "signal_or_live_execution_observed":False,
        "intrabar_order_and_real_fills_unobserved":True,
        "demo_paper_modified":False,"private_api":False,"orders":0,"live":False,
        "merge":False,"promote":False,
    }
    result["digest"]=hashlib.sha256(canon(result)).hexdigest()
    out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(result,sort_keys=True,ensure_ascii=False,indent=2)+chr(10),encoding="utf-8")
    print(json.dumps({
        "digest":result["digest"],"n_total":len(pairs),
        "results":groups,"eligible_for_paper_promotion":False
    },ensure_ascii=False))


if __name__=="__main__":
    ap=argparse.ArgumentParser()
    for arg in ("protocol","source_dir","ledger","fee_report","risk_report","out"):
        ap.add_argument("--"+arg,type=Path,required=True)
    run(**vars(ap.parse_args()))
