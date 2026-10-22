"""All 47 frozen MR40 Bybit Spot LONG pairs: tier-aware 2-sided fee-only audit.

READ ONLY. Not OOS, executable fills, account fee discovery or an exchange order.
The independent closed-bar engine creates all decisions before frozen ledger is
loaded as a post-hoc comparator. Prices are OPEN proxies, not executable quotes.
"""
from __future__ import annotations
import argparse,hashlib,json
from datetime import datetime,timezone
from decimal import Decimal as D,localcontext
from pathlib import Path
from research.nexus_mr40_independent_closed_signal_v1 import (
    ClosedMR40,frozen_rows,oracle_ledger,canon,STEP,ms,ROWS_SHA,LEDGER_SHA
)

SCHEMA="nexus.mr40.frozen_47_fee_sensitivity_20261022.v1"
START=D("500")
RATES={
    "ZERO_FEE_UPPER_BOUND":D("0"),
    "OFFICIAL_SPOT_VIP3_TAKER_REFERENCE":D("0.00075"),
    "OFFICIAL_SPOT_VIP0_TAKER_REFERENCE":D("0.001"),
}


def get_pairs(rows):
    engine=ClosedMR40()
    entries=[]
    exits=[]
    for bar in rows:
        sig=engine.feed(bar,confirmed=True,source_verified=True)
        if sig.first_entry_close:entries.append(sig.bar_index)
        if sig.natural_exit_close:exits.append(sig.bar_index)
    if len(rows)!=8514 or len(entries)!=47 or len(exits)!=47:
        raise ValueError("frozen_47_47_signal_count_changed")
    prior_exit=-1
    pairs=[]
    for ent,ex in zip(entries,exits):
        if ent<=prior_exit or ent>=ex or ex+1>=len(rows):
            raise ValueError("overlapping_or_invalid_next_open_pair")
        a=rows[ent+1]
        b=rows[ex+1]
        if a[0]!=rows[ent][0]+STEP or b[0]!=rows[ex][0]+STEP:
            raise ValueError("missing_4h_next_open")
        entry_price=D(str(a[1]));exit_price=D(str(b[1]))
        if entry_price<=0 or exit_price<=0:raise ValueError("invalid_price")
        category="train" if a[0]<ms("2025-01-01") else "evaluation"
        pairs.append({
            "entry_signal_index":ent,"exit_signal_index":ex,
            "entry_next_open_index":ent+1,"exit_next_open_index":ex+1,
            "entry_next_open_ms":a[0],"exit_next_open_ms":b[0],
            "entry_next_open_price":str(entry_price),
            "exit_next_open_price":str(exit_price),
            "window":category
        })
        prior_exit=ex
    if sum(p["window"]=="train" for p in pairs)!=25 or sum(p["window"]=="evaluation" for p in pairs)!=22:
        raise ValueError("frozen_25_train_22_eval_split_changed")
    return pairs


def match_frozen_comparator(pairs,prior):
    for group in ("train","evaluation"):
        actual=[x for x in pairs if x["window"]==group]
        saved=prior[group]["positions"]
        if len(actual)!=len(saved):raise ValueError("prior_position_count_changed")
        for generated,stored in zip(actual,saved):
            if (generated["entry_signal_index"]!=stored["entry"]["signal_index"]
                or generated["exit_signal_index"]!=stored["exit"]["signal_index"]
                or generated["entry_next_open_index"]!=stored["entry"]["bar_index"]
                or generated["exit_next_open_index"]!=stored["exit"]["bar_index"]
                or generated["entry_next_open_ms"]!=stored["entry"]["fill_ms"]
                or generated["exit_next_open_ms"]!=stored["exit"]["fill_ms"]):
                raise ValueError("frozen_ledger_temporal_parity_failed")


def factor(pair,fee):
    return ((D(1)-fee)*D(pair["exit_next_open_price"])/
            D(pair["entry_next_open_price"])*(D(1)-fee))


def summarize(pairs):
    if not pairs:raise ValueError("no_pairs")
    scenarios={}
    for name,fee in RATES.items():
        balance=START
        peak=START
        max_drawdown=D(0)
        win=0
        individual=[]
        fixed_500_sum=D(0)
        for k,pair in enumerate(pairs):
            multiplier=factor(pair,fee)
            pnl_fixed=START*(multiplier-D(1))
            fixed_500_sum+=pnl_fixed
            balance=balance*multiplier
            if balance>peak:peak=balance
            dd=(peak-balance)/peak
            if dd>max_drawdown:max_drawdown=dd
            if multiplier>D(1):win+=1
            individual.append({
                "position_index_in_window":k+1,
                "signal_entry_index":pair["entry_signal_index"],
                "signal_exit_index":pair["exit_signal_index"],
                "fixed_quote_pnl_usdt":str(pnl_fixed),
                "post_close_equity_usdt":str(balance),
                "closed_only_drawdown_pct_from_prior_peak":str(dd*D(100)),
                "gross_fee_basis_is_unexecutable_next_open":True,
            })
        scenarios[name]={
            "fee_per_side_decimal":str(fee),
            "round_trip_flat_price_fee_drag_pct":str((D(1)-(D(1)-fee)**2)*D(100)),
            "closed_positions":len(pairs),
            "positive_net_positions":win,
            "negative_net_positions":len(pairs)-win,
            "equity_start_usdt":"500",
            "closed_trade_equity_end_usdt":str(balance),
            "compounded_realized_only_return_pct":str((balance/START-D(1))*D(100)),
            "max_closed_trade_only_drawdown_pct":str(max_drawdown*D(100)),
            "fixed_500_quote_per_trade_total_pnl_usdt_NO_COMPOUND":str(fixed_500_sum),
            "per_trade":individual,
        }
    return scenarios


def run(lock,inputs,ledger,output):
    if output.exists():raise ValueError("refuse_overwrite_frozen_fee_study")
    p=json.loads(lock.read_bytes())
    if (p.get("schema")!=SCHEMA or p["data"]["market_digest"]!=ROWS_SHA
        or p["data"]["previous_comparison_ledger_gzip_sha256"]!=LEDGER_SHA
        or p["data"]["total_completed_long_pairs"]!=47
        or p["account_model"]["starting_quote_usdt"]!="500"
        or p["fail_closed"]["no_orders"] is not True
        or p["fail_closed"]["promote"] is not False):
        raise ValueError("fee_study_protocol_drift")
    definitions=p["public_fee_source"]["scenarios"]
    got={s["name"]:(s["buy_taker"],s["sell_taker"]) for s in definitions}
    if (set(got)!=set(RATES)
        or any(got[name]!=(str(fee),str(fee)) for name,fee in RATES.items())):
        raise ValueError("official_spot_fee_scenario_drift")
    rows=frozen_rows(inputs)
    independent_pairs=get_pairs(rows)
    prior=oracle_ledger(ledger)  # comparison AFTER generating decisions
    match_frozen_comparator(independent_pairs,prior)
    splits={
        "train_2023_2024":[t for t in independent_pairs if t["window"]=="train"],
        "evaluation_2025_2026oct19":[t for t in independent_pairs if t["window"]=="evaluation"],
        "combined_chronological_2023_2026oct19":independent_pairs,
    }
    report={
        "schema":"nexus.mr40.frozen47_fee_only_open_price_audit.results.v1",
        "protocol_sha256":hashlib.sha256(lock.read_bytes()).hexdigest(),
        "market_sha256":ROWS_SHA,"ledger_SHA256_only_as_posthoc_oracle":LEDGER_SHA,
        "all_47_entry_exit_next_open_parity":True,
        "pricing_basis":"FROZEN_HISTORICAL_4H_NEXT_OPEN_PROXY_NO_EXECUTABLE_QUOTES",
        "official_fee_url":p["public_fee_source"]["url"],
        "actual_account_region_vip_rate_known":False,
        "starting_quote_usdt":str(START),
        "total_pairs":len(independent_pairs),
        "verified_pairs":[{**r,"no_real_order_or_fill":True} for r in independent_pairs],
        "groups":{label:summarize(items) for label,items in splits.items()},
        "intratrade_drawdown_measured":False,
        "historical_seen_sample_only":True,
        "not_OOS_edge_confirmation":True,
        "spread_slippage_latency_not_included":True,
        "paper_changed":False,"orders":0,"private_API":False,"live":False,"merge":False,"promote":False,
    }
    report["digest"]=hashlib.sha256(canon(report)).hexdigest()
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(report,sort_keys=True,indent=2,ensure_ascii=False)+"\n",encoding="utf8")
    concise={
        "digest":report["digest"],"pairs":len(independent_pairs),
        "train":len(splits["train_2023_2024"]),"evaluation":len(splits["evaluation_2025_2026oct19"]),
        "groups":{w:{name:{k:v for k,v in metric.items() if k!="per_trade"} for name,metric in scenarios.items()} for w,scenarios in report["groups"].items()}
    }
    print(json.dumps(concise,ensure_ascii=False))


if __name__=="__main__":
    a=argparse.ArgumentParser()
    for name in ("lock","inputs","ledger","output"):a.add_argument("--"+name,required=True,type=Path)
    run(**vars(a.parse_args()))
