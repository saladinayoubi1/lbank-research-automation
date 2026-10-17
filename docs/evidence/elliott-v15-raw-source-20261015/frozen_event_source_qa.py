"""Read-only, bounded V15 raw-pivot provenance QA of FROZEN old price events.

No re-running the original producer/backtest, no new signal discovery or
strategy tuning; independently confirm already recorded first price-events.
The old trace must remain immutable. Source of truth: six frozen Bybit hashes.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import pandas as pd

from nexus_elliott_source_bound_v15 import (
    _closed_history, _independent_selected_pivots,
    certify_seven_pivots_from_closed_15m,
)

# Immutable byte identities from the earlier first-market producer.
FROZEN_15M_SHA = {
    "BTCUSDT":"c3afe92899dda8fe52937c955323cc8e04bf8f200a68eb8651e55d6020981226",
    "ETHUSDT":"ce603440650d0022b1a17a7922da743a3b6219ba9afd89ad4362b70fbe3bbfa1",
}
PAIR_DIR = {"BTCUSDT":"btc_usdt","ETHUSDT":"eth_usdt"}
ANCHOR_FIELDS = (
    ("lagged_elliott5_origin_index", "index", 0),
    ("lagged_elliott5_origin_low", "price", 0),
    ("lagged_elliott5_wave1_index", "index", 5),
    ("lagged_elliott5_wave1_high", "price", 5),
    ("lagged_elliott5_wave2_index", "index", 6),
    ("lagged_elliott5_wave2_low", "price", 6),
    ("lagged_elliott5_confirmed_at", "confirmed_at", 6),
)


def file_sha(path: Path) -> str:
    sha=hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda:handle.read(1024*1024),b""):
            sha.update(chunk)
    return sha.hexdigest()


def unique_frozen_price_events(trace: dict) -> tuple[list[dict],int]:
    if trace.get("live_enabled") is not False or trace.get("schema") is None:
        raise ValueError("trace is not a valid frozen research-only record")
    source={}
    duplicated=0
    for row in trace["rows"]:
        symbol=row["symbol"]
        if symbol not in PAIR_DIR:
            raise ValueError("unexpected symbol in old trace")
        for event in row["price_events"]:
            index=event["bar_index"]
            if type(index) is not int or index < 0:
                raise ValueError("invalid frozen decision index")
            k=(symbol,index)
            if k in source:
                for name in ("decision_at","open_at","setup"):
                    if event[name]!=source[k][name]:
                        raise ValueError("duplicate price event records differ in structure")
                duplicated+=1
            else:
                source[k]={"symbol":symbol,**event}
    return sorted(source.values(),key=lambda x:(x["symbol"],x["bar_index"])),duplicated


def audit(archive:Path,trace_path:Path) -> dict:
    trace=json.loads(trace_path.read_text(encoding="utf-8"))
    records,dups=unique_frozen_price_events(trace)
    result={
        "schema":"nexus.elliott-v15-frozen-event-raw-source-qa.v1",
        "research_only":True,"live_enabled":False,"simulator_invoked":False,
        "price_event_producer_rerun":False,"new_events_discovered":False,
        "original_frozen_trace_sha256":file_sha(trace_path),
        "market_sha256":FROZEN_15M_SHA,"unique_events":len(records),
        "duplicated_cost_profile_events":dups,"events":[],
    }
    if not records:
        raise AssertionError("empty frozen event trace")
    frames={}
    for symbol in PAIR_DIR:
        path=archive/"bybit_market"/PAIR_DIR[symbol]/"minute15.parquet"
        if file_sha(path)!=FROZEN_15M_SHA[symbol]:
            raise AssertionError("unrecognized immutable price archive "+symbol)
        frames[symbol]=pd.read_parquet(path)
    for event in records:
        symbol=event["symbol"]
        d=event["bar_index"]
        if d>=len(frames[symbol]):
            raise AssertionError("decision after source data")
        # Strict source chronology and all events up through previous bar,
        # no price information from candles after this archived event.
        prefix=frames[symbol].iloc[:d+1].copy()
        decision=pd.Timestamp(event["decision_at"])
        source_prices,times=_closed_history(prefix,d,decision)
        if times[-1]!=pd.Timestamp(event["open_at"]):
            raise AssertionError("recorded event OPEN does not match archived time")
        known=_independent_selected_pivots(source_prices,d)
        findings=[]
        if len(known)!=7:
            findings.append("RECONSTRUCTION_HAS_NOT_SEVEN_PIVOTS")
        else:
            setup=event["setup"]
            for key,attr,slot in ANCHOR_FIELDS:
                claimed=setup[key]
                observed=getattr(known[slot],attr)
                if float(claimed)!=float(observed):
                    findings.append("FROZEN_TRACE_"+key+"_DOES_NOT_MATCH_RAW")
        if len(known)==7:
            verdict=certify_seven_pivots_from_closed_15m(
                prefix, known,d,decision_close_utc=decision
            )
            if not verdict.source_bound:
                findings.append("REVIEW_"+verdict.reason)
        result["events"].append({
            "symbol":symbol,"part":event.get("part"),"decision_index":d,
            "decision_utc":str(decision),"setup_origin":event["setup"].get(
                "lagged_elliott5_origin_index"),
            "seven_pivots_count":len(known),
            "source_verified":not findings,"failures":findings,
            "source_bound_recursive_count_proven":False,
            "trigger_bar_is_new_trading_signal":False,
        })
    result["failures"]=sum(int(not x["source_verified"]) for x in result["events"])
    result["disposition"]=(
        "PASS_FROZEN_PRICE_EVENT_PIVOT_SOURCE_QA" if result["failures"]==0 else
        "FAIL_FROZEN_PRICE_EVENT_PIVOT_SOURCE_QA"
    )
    return result


def main():
    p=argparse.ArgumentParser()
    p.add_argument("--archive",type=Path,required=True)
    p.add_argument("--trace",type=Path,required=True)
    p.add_argument("--out",type=Path,required=True)
    args=p.parse_args()
    result=audit(args.archive,args.trace)
    args.out.parent.mkdir(parents=True,exist_ok=True)
    args.out.write_text(json.dumps(result,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    print(json.dumps({
        "disposition":result["disposition"],"unique_events":result["unique_events"],
        "failures":result["failures"],"duplicated_cost_profile_events":
        result["duplicated_cost_profile_events"]
    },sort_keys=True))
    if result["failures"]:
        raise SystemExit(2)


if __name__=="__main__":
    main()
