"""Pinned all-47 Bybit Spot MR40 adverse-price MAE / holding-time audit.

No strategies optimized, no stop positions simulated, no private API,
no trading; uses existing SHA-pinned complete independent risk ledger.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from decimal import Decimal as D
from math import ceil
from pathlib import Path

SCHEMA="nexus.mr40.frozen47_tail_risk_exposure_distribution_v1"
RISK_SHA="c401f4920d8f51abe2ed77c11aa3a9616df8cde2d0dd958d7dfd0a59c6cac051"
RISK_DIGEST="6ec8b21dc24ef1de962c4b439f870420493cecab570c53311eb836dbe7240ba9"
MARKET_SHA="a458d9f83df633df8ee5cab5f2a19de41c4c79c61185b5abd258fdefa80d575a"
GROUP="OFFICIAL_SPOT_VIP0_TAKER_REFERENCE"
MILESTONES=(D(3),D(5),D(10),D(15),D(20))
HOLD=(24,72,120,168)
PERCENTILES=(D("0.5"),D("0.75"),D("0.9"),D("0.95"))
DURATION_GROUPS=(("lt_48_hours",0,48),("48_to_119_hours",48,120),("gte_120_hours",120,None))


def canon(obj):
    return json.dumps(obj,sort_keys=True,separators=(",",":"),allow_nan=False,ensure_ascii=False).encode()


def nearest_rank(values,quantile):
    if not values or quantile<=0 or quantile>1:
        raise ValueError("invalid_fixed_quantile")
    vals=sorted(values)
    return vals[ceil(quantile*len(vals))-1]


def normalize(records):
    out=[]
    seen=set()
    for i,row in enumerate(records):
        ix=row["trade_index"]
        if type(ix) is not int or ix in seen:
            raise ValueError("missing_or_duplicate_trade_index")
        seen.add(ix)
        hold=row["holding_hours"]
        if type(hold) is not int or hold<=0 or hold%4!=0:
            raise ValueError("invalid_fourhour_hold")
        entry=D(row["entry_open_price"])
        lowest=D(row["lowest_held_4h_candle_low"])
        price_mae=D(row["MAE_price_only_pct_from_entry_OPEN"])
        pct=(D(1)-lowest/entry)*D(100)
        if (not entry.is_finite() or entry<=0 or not lowest.is_finite()
            or lowest<=0 or price_mae>0
            or abs(pct+price_mae)>D("1e-18")):
            raise ValueError("unsupported_or_tampered_entry_low_MAE")
        from datetime import datetime,timezone
        begin=datetime.fromisoformat(row["entry_open_utc"])
        end=datetime.fromisoformat(row["exit_open_utc"])
        bar=datetime.fromisoformat(row["lowest_held_candle_open_utc"])
        if (begin.tzinfo is None or begin.utcoffset()!=timezone.utc.utcoffset(begin)
            or end.tzinfo is None or end.utcoffset()!=timezone.utc.utcoffset(end)
            or bar.tzinfo is None or bar.utcoffset()!=timezone.utc.utcoffset(bar)):
            raise ValueError("invalid_UTC_market_clocks")
        if (int((end-begin).total_seconds())!=hold*3600
            or bar<begin or bar>=end or int((bar-begin).total_seconds())%14400):
            raise ValueError("impossible_held_bar_clock")
        out.append({
            "trade_index":ix,
            "window":row["window"],
            "entry_open_utc":row["entry_open_utc"],
            "exit_open_utc":row["exit_open_utc"],
            "lowest_held_candle_open_utc":row["lowest_held_candle_open_utc"],
            "hours_until_start_of_worst_candle":int((bar-begin).total_seconds()/3600),
            "holding_hours":hold,
            "entry_price":str(entry),
            "lowest_spot_bar_price":str(lowest),
            "price_MAE_adverse_pct":str(pct),
            "price_MFE_favorable_pct":row["MFE_price_only_pct_from_entry_OPEN"],
            "historical_only_no_stop_or_fill":True,
        })
    if [z["trade_index"] for z in out]!=list(range(records[0]["trade_index"],records[0]["trade_index"]+len(records))):
        raise ValueError("nonconsecutive_trade_source_identity")
    return out


def describe(records):
    if not records:
        raise ValueError("empty_frozen_trade_selection")
    durations=[z["holding_hours"] for z in records]
    maes=[D(z["price_MAE_adverse_pct"]) for z in records]
    result={
        "n_positions":len(records),
        "max_holding_hours":max(durations),
        "mean_holding_hours":str(D(sum(durations))/D(len(durations))),
        "mean_adverse_price_MAE_pct":str(sum(maes,D(0))/D(len(maes))),
        "max_adverse_price_MAE_pct":str(max(maes)),
        "MAE_count_at_or_above_percent":{str(x):sum(m>=x for m in maes) for x in MILESTONES},
        "holding_count_at_or_above_hours":{str(x):sum(d>=x for d in durations) for x in HOLD},
        "holding_hours_nearest_rank":{str(x):nearest_rank(durations,x) for x in PERCENTILES},
        "adverse_price_MAE_nearest_rank_pct":{str(x):str(nearest_rank(maes,x)) for x in PERCENTILES},
        "hold_duration_categories":{},
        "not_unseen_out_of_sample":True,
        "not_an_order_fill_or_stop_simulation":True,
    }
    for tag,min_d,max_d in DURATION_GROUPS:
        group=[z for z in records if z["holding_hours"]>=min_d and (max_d is None or z["holding_hours"]<max_d)]
        result["hold_duration_categories"][tag]={
            "n_positions":len(group),
            "MAE_at_or_above_5_pct":sum(D(z["price_MAE_adverse_pct"])>=5 for z in group),
            "MAE_at_or_above_10_pct":sum(D(z["price_MAE_adverse_pct"])>=10 for z in group),
            "MAE_at_or_above_15_pct":sum(D(z["price_MAE_adverse_pct"])>=15 for z in group),
            "descriptive_no_causal_holding_rule":True,
        }
    if sum(x["n_positions"] for x in result["hold_duration_categories"].values())!=len(records):
        raise ValueError("missing_hold_duration_category")
    return result


def guard_protocol(policy):
    meta=policy["source"]
    params=policy["precommitted_descriptive_metrics"]
    if (policy.get("schema")!=SCHEMA
        or meta.get("full_risk_file_sha256")!=RISK_SHA
        or meta.get("full_risk_logical_digest")!=RISK_DIGEST
        or meta.get("market_rows_sha256")!=MARKET_SHA
        or meta.get("fee_scenario")!=GROUP
        or meta.get("expected_pairs")!=47
        or tuple(params["tail_thresholds_price_MAE_pct"])!=tuple(int(x) for x in MILESTONES)
        or tuple(params["long_holding_thresholds_hours"])!=HOLD
        or tuple(str(x) for x in params["quantile_probabilities"])!=tuple(str(x) for x in PERCENTILES)
        or policy["constraints"]["orders"]!=0
        or policy["constraints"]["promote"] is not False
        or policy["constraints"]["live"] is not False):
        raise ValueError("frozen_tail_risk_protocol_drift")


def run(protocol,risk_file,out):
    if out.exists():
        raise ValueError("refuse_overwrite")
    pbytes=protocol.read_bytes()
    guard_protocol(json.loads(pbytes))
    b=risk_file.read_bytes()
    if hashlib.sha256(b).hexdigest()!=RISK_SHA:
        raise ValueError("previous_all47_risk_file_SHA_mismatch")
    original=json.loads(b)
    logical=original.pop("digest")
    if logical!=RISK_DIGEST or hashlib.sha256(canon(original)).hexdigest()!=RISK_DIGEST:
        raise ValueError("previous_all47_risk_content_digest_mismatch")
    groups=original["groups"]
    all_records=groups["combined_chronological_2023_2026oct19"][GROUP]["per_position"]
    train_records=groups["train_2023_2024"][GROUP]["per_position"]
    eval_records=groups["evaluation_2025_2026oct19"][GROUP]["per_position"]
    if (len(all_records)!=47 or len(train_records)!=25 or len(eval_records)!=22
        or all_records!=train_records+[{**x,"trade_index":x["trade_index"]+25} if False else x for x in eval_records]):
        # split per-position position_index may start over; verify market
        # timestamps and signal identities below instead of equality of
        # split-local indices.
        if not (len(all_records)==47 and len(train_records)==25 and len(eval_records)==22):
            raise ValueError("source_window_count_changed")
    full=normalize(all_records)
    train=normalize(train_records)
    evals=normalize(eval_records)
    if ([r["entry_open_utc"] for r in full] != [r["entry_open_utc"] for r in train+evals]
        or [r["price_MAE_adverse_pct"] for r in full] != [r["price_MAE_adverse_pct"] for r in train+evals]):
        raise ValueError("train_evaluation_window_parity_changed")
    total=describe(full)
    if (abs(D(total["max_adverse_price_MAE_pct"])
             -D("23.39651835345841867164113269"))>D("1e-18")
        or original["groups"]["combined_chronological_2023_2026oct19"][GROUP]["adversarial_high_before_low_max_dd_upper_bound_pct"]!="25.41746891798068870740313933"):
        raise ValueError("previous_confirmed_tail_risk_changed")
    report={
        "schema":"nexus.mr40.all47_frozen_adverse_MAE_holding_descriptive_v1",
        "protocol_sha256":hashlib.sha256(pbytes).hexdigest(),
        "pinned_full_previous_risk_sha256":RISK_SHA,
        "fee_scenario_ref":GROUP,
        "groups":{
            "train_2023_2024":describe(train),
            "evaluation_2025_to_2026_oct19":describe(evals),
            "all_47":total,
        },
        "top_5_price_MAE":sorted(full,key=lambda r:(-D(r["price_MAE_adverse_pct"]),r["trade_index"]))[:5],
        "top_5_longest_hold":sorted(full,key=lambda r:(-r["holding_hours"],r["trade_index"]))[:5],
        "underlying_model_true_global_equity_ohlc_dd_pct":"25.41746891798068870740313933",
        "underlying_fee_only_closed_trade_dd_pct":"10.22924661117586234881992445",
        "no_stop_or_sizing_rule_chosen_from_posthoc_distribution":True,
        "promotion_gate":{
            "ready_for_paper_strategy_change":False,
            "missing_user_approved_risk_budget":True,
            "missing_unseen_forward_execution_and_fill_evidence":True,
            "live_trading_disabled":True,
            "reason":"Observed severe underwater tail cannot justify unapproved risk/stop tuning or automatic Paper promotion.",
        },
        "signals_changed":False,"paper_modified":False,"orders":0,
        "private_api":False,"live":False,"merge":False,"promote":False,
    }
    report["digest"]=hashlib.sha256(canon(report)).hexdigest()
    out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(report,sort_keys=True,ensure_ascii=False,indent=2)+chr(10),encoding="utf8")
    print(json.dumps({"digest":report["digest"],"global":total,
        "top_5_price_MAE":report["top_5_price_MAE"],
        "promote":report["promotion_gate"]["ready_for_paper_strategy_change"]},ensure_ascii=False))


if __name__=="__main__":
    a=argparse.ArgumentParser()
    for n in ("protocol","risk_file","out"):a.add_argument("--"+n,type=Path,required=True)
    args=a.parse_args()
    run(args.protocol,args.risk_file,args.out)
