"""Read-only 47-trade adverse LOW event clock, no stops, orders or tuning."""
import argparse,hashlib,json
from datetime import datetime,timezone
from decimal import Decimal as D
from pathlib import Path
from research.nexus_mr40_independent_closed_signal_v1 import frozen_rows,oracle_ledger,canon,STEP,ROWS_SHA,LEDGER_SHA
from research.nexus_mr40_frozen_47_spot_fee_audit_v1 import get_pairs,match_frozen_comparator

PROTO="nexus.mr40.all47_early_mid_late_adverse_timing.protocol.v1"
RISK_SHA="c401f4920d8f51abe2ed77c11aa3a9616df8cde2d0dd958d7dfd0a59c6cac051"
RISK_DIGEST="6ec8b21dc24ef1de962c4b439f870420493cecab570c53311eb836dbe7240ba9"
BANDS=(("EARLY_0_TO_24_HOURS",0,24),("MIDDLE_24_TO_120_HOURS",24,120),("LATE_FROM_120_HOURS",120,None))
LIMITS=(5,10,15)

def utc(ts):
    return datetime.fromtimestamp(ts/1000,timezone.utc).isoformat()

def band(hours):
    if type(hours) is not int or hours<0 or hours%4:raise ValueError("invalid_4h_offset")
    for name,lo,hi in BANDS:
        if hours>=lo and (hi is None or hours<hi):return name
    raise ValueError("unclassified_bar")

def inspect_one(rows,pair):
    a,b=pair["entry_next_open_index"],pair["exit_next_open_index"]
    if not 0<=a<b<len(rows):raise ValueError("invalid_pair_candle_indices")
    entry=D(pair["entry_next_open_price"])
    if entry<=0 or entry!=D(str(rows[a][1])):raise ValueError("untrusted_entry_price")
    if rows[a][0]!=pair["entry_next_open_ms"] or rows[b][0]!=pair["exit_next_open_ms"]:
        raise ValueError("incorrect_frozen_pair_clocks")
    cells={name:{"held_bars":0,"worst_adverse_pct":"0","breach_bar_count":{str(t):0 for t in LIMITS}}
           for name,_,_ in BANDS}
    first={str(t):None for t in LIMITS}
    worst=None
    for i in range(a,b):
        row=rows[i]
        if row[0]!=rows[a][0]+(i-a)*STEP:raise ValueError("market_bar_gap")
        low=D(str(row[3]));hi=D(str(row[2]))
        if not low.is_finite() or not hi.is_finite() or low<=0 or low>hi:
            raise ValueError("bad_ohlc_candle")
        age=4*(i-a);key=band(age)
        adverse=max(D(0),(D(1)-low/entry)*D(100))
        c=cells[key];c["held_bars"]+=1
        c["worst_adverse_pct"]=str(max(D(c["worst_adverse_pct"]),adverse))
        if worst is None or low<D(worst["low"]):
            worst={"low":str(low),"start_utc":utc(row[0]),"hour_age":age,"band":key}
        for t in LIMITS:
            if low<=entry*(D(1)-D(t)/D(100)):
                c["breach_bar_count"][str(t)]+=1
                if first[str(t)] is None:
                    first[str(t)]={"band":key,"bar_start_utc":utc(row[0]),
                                   "bar_end_utc":utc(row[0]+STEP),"hour_age_at_bar_start":age,
                                   "exact_intrabar_touch_time_not_known":True}
    if sum(v["held_bars"] for v in cells.values())!=b-a:
        raise ValueError("held_bars_unaccounted")
    adverse=(D(1)-D(worst["low"])/entry)*D(100)
    return {
        "entry_signal_index":pair["entry_signal_index"],
        "exit_signal_index":pair["exit_signal_index"],
        "entry_open_utc":utc(rows[a][0]),"exit_open_utc":utc(rows[b][0]),
        "held_hours":4*(b-a),"entry_open_price":str(entry),
        "whole_position_adverse_price_MAE_pct":str(adverse),
        "worst_low":worst,"by_time_band":cells,"first_threshold_breach":first,
        "no_order_or_stop_execution":True
    }

def aggregate(records):
    if not records:raise ValueError("empty_risk_window")
    result={}
    for name,_,_ in BANDS:
        available=[v for v in records if v["by_time_band"][name]["held_bars"]>0]
        result[name]={
            "n_all_positions":len(records),
            "n_exposed_positions":len(available),
            "total_exposed_4h_candles":sum(x["by_time_band"][name]["held_bars"] for x in available),
            "n_with_any_breach_during_band":{
                str(t):sum(x["by_time_band"][name]["breach_bar_count"][str(t)]>0 for x in available)
                for t in LIMITS},
            "n_with_FIRST_breach_during_band":{
                str(t):sum(x["first_threshold_breach"][str(t)] is not None and
                           x["first_threshold_breach"][str(t)]["band"]==name for x in available)
                for t in LIMITS},
            "conditional_on_time_exposed_not_causal":True,
        }
    return {"positions":len(records),"bands":result,
            "ever_breached":{str(t):sum(x["first_threshold_breach"][str(t)] is not None for x in records) for t in LIMITS},
            "no_hold_cap_or_stop_selected":True}

def validate_protocol(p):
    expected=[{"label":k,"lower_inclusive_hour":lo,"upper_exclusive_hour":hi} for k,lo,hi in BANDS]
    s=p["source"];f=p["fixed_diagnostic"]
    if (p.get("schema")!=PROTO or
        f["bands_full_fourhour_bar_offset_from_entry"]!=expected or
        f["price_adverse_thresholds_pct"]!=list(LIMITS) or
        s["frozen_4h_rows_digest"]!=ROWS_SHA or
        s["authentic_ledger_gzip_sha256"]!=LEDGER_SHA or
        s["complete_47_position_risk_report_file_sha256"]!=RISK_SHA or
        s["complete_47_position_risk_report_logical_digest"]!=RISK_DIGEST or
        s["pairs"]!=47 or p["safety"]["orders"]!=0 or
        p["safety"]["auto_promote"] is not False or p["safety"]["live"] is not False):
        raise ValueError("risk_timing_protocol_drift")

def run(protocol,inputs,ledger,risk,out):
    if out.exists():raise ValueError("refuse_overwrite")
    pb=protocol.read_bytes();validate_protocol(json.loads(pb))
    rows=frozen_rows(inputs);pairs=get_pairs(rows)
    match_frozen_comparator(pairs,oracle_ledger(ledger))
    b=risk.read_bytes()
    if hashlib.sha256(b).hexdigest()!=RISK_SHA:raise ValueError("risk_source_SHA_drift")
    old=json.loads(b);digest=old.pop("digest",None)
    if digest!=RISK_DIGEST or hashlib.sha256(canon(old)).hexdigest()!=RISK_DIGEST:
        raise ValueError("risk_source_payload_drift")
    previous=old["groups"]["combined_chronological_2023_2026oct19"]["OFFICIAL_SPOT_VIP0_TAKER_REFERENCE"]["per_position"]
    if len(previous)!=47 or len(pairs)!=47:raise ValueError("wrong_pair_count")
    record=[]
    for i,p in enumerate(pairs):
        o=inspect_one(rows,p);prior=previous[i]
        if (prior["trade_index"]!=i+1 or
            prior["entry_signal_index"]!=o["entry_signal_index"] or
            prior["exit_signal_index"]!=o["exit_signal_index"] or
            prior["entry_open_utc"]!=o["entry_open_utc"] or
            prior["exit_open_utc"]!=o["exit_open_utc"] or
            prior["holding_hours"]!=o["held_hours"] or
            prior["lowest_held_candle_open_utc"]!=o["worst_low"]["start_utc"] or
            abs(D(prior["MAE_price_only_pct_from_entry_OPEN"])+D(o["whole_position_adverse_price_MAE_pct"]))>D("1e-18")):
            raise ValueError("independent_47_position_low_parity_failed")
        o["trade_index"]=i+1;o["window"]=p["window"];record.append(o)
    tr=[x for x in record if x["window"]=="train"]
    ev=[x for x in record if x["window"]=="evaluation"]
    if len(tr)!=25 or len(ev)!=22:raise ValueError("historical_window_mismatch")
    report={"schema":"nexus.mr40.all47_fixed_adverse_event_timing.results.v1",
        "protocol_sha256":hashlib.sha256(pb).hexdigest(),"previous_risk_sha256":RISK_SHA,
        "source_frozen_OHLC_sha256":ROWS_SHA,"source_ledger_sha256":LEDGER_SHA,
        "group_stats":{"all_47":aggregate(record),"train_25":aggregate(tr),"evaluation_22":aggregate(ev)},
        "per_position":record,
        "classification":"DESCRIPTIVE_KNOWN_SAMPLE_NOT_CAUSAL_OR_FORWARD_OOS",
        "no_stops_backtested":True,"no_new_strategy_parameters":True,
        "paper_changed":False,"orders":0,"private_API":False,"live":False,"merge":False,"promote":False}
    report["digest"]=hashlib.sha256(canon(report)).hexdigest()
    out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(report,sort_keys=True,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
    print(json.dumps({"digest":report["digest"],"groups":report["group_stats"],
        "top_two":sorted(record,key=lambda x:-D(x["whole_position_adverse_price_MAE_pct"]))[:2]},
        ensure_ascii=False))

if __name__=="__main__":
    a=argparse.ArgumentParser()
    for name in ("protocol","inputs","ledger","risk","out"):
        a.add_argument("--"+name,required=True,type=Path)
    q=a.parse_args()
    run(q.protocol,q.inputs,q.ledger,q.risk,q.out)
