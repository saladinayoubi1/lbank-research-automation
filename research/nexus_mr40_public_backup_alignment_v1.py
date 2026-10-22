"""One-shot, public read-only Bitget/LBank 4h research source receipt.

NEVER a Bybit substitute, strategy signal, Paper order source or proof of fill.
No tasks, schedulers, websockets, credentials or trading endpoints.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import time
import urllib.request
from datetime import datetime, timezone
from decimal import Decimal as D
from pathlib import Path

STEP=14_400_000
GATE_MARGIN_MS=120_000
SOURCES=("Bitget","LBank")


def canon(obj):
    return json.dumps(obj,sort_keys=True,separators=(",",":"),ensure_ascii=False,allow_nan=False).encode()


def normalized_rows(body,venue):
    doc=json.loads(body)
    if venue=="Bitget":
        if doc.get("code")!="00000":raise ValueError("bitget_public_response_invalid")
        raw=doc.get("data")
        if not isinstance(raw,list):raise ValueError("missing_bitget_rows")
    elif venue=="LBank":
        if str(doc.get("result")).lower()!="true" or doc.get("error_code")!=0:
            raise ValueError("lbank_public_response_invalid")
        raw=doc.get("data")
        if not isinstance(raw,list):raise ValueError("missing_lbank_rows")
    else:
        raise ValueError("invalid_venue")
    out={}
    for source in raw:
        if not isinstance(source,list) or len(source)!=(7 if venue=="Bitget" else 6):
            raise ValueError("invalid_public_ohlcv_row")
        ms=int(source[0])*(1000 if venue=="LBank" else 1)
        if ms%STEP:raise ValueError("non_four_hour_time_alignment")
        o,h,l,c,v=[D(str(x)) for x in source[1:6]]
        if (not all(x.is_finite() for x in (o,h,l,c,v))
            or min(o,h,l,c,v)<=0 or h<max(o,c) or l>min(o,c)):
            raise ValueError("malformed_public_ohlcv")
        if ms in out:raise ValueError("duplicate_public_bar")
        out[ms]={"timestamp_ms":ms,"open":str(o),"high":str(h),
                 "low":str(l),"close":str(c),"base_volume":str(v)}
    return out


def overlap(rows1,rows2,received_ms):
    # Never include unfinished bars in parity or diagnostics.
    cutoff=received_ms-GATE_MARGIN_MS
    complete1={k:v for k,v in rows1.items() if k+STEP<=cutoff}
    complete2={k:v for k,v in rows2.items() if k+STEP<=cutoff}
    common=sorted(complete1.keys()&complete2.keys())
    diffs=[]
    for ts in common:
        a=D(complete1[ts]["close"]);b=D(complete2[ts]["close"])
        mid=(a+b)/2
        diffs.append({"timestamp_ms":ts,"utc":datetime.fromtimestamp(ts/1000,timezone.utc).isoformat(),
                      "bitget_close":str(a),"lbank_close":str(b),
                      "absolute_close_difference_usdt":str(abs(a-b)),
                      "close_diff_bp_of_mid":str((abs(a-b)/mid*D(10000)).quantize(D("0.0001")))})
    consecutive=all(common[i]-common[i-1]==STEP for i in range(1,len(common)))
    ready=len(common)>=2 and consecutive
    return {"bitget_closed_bars":len(complete1),"lbank_closed_bars":len(complete2),
            "matching_closed_bars":len(common),"consecutive":consecutive,
            "read_only_research_backup_source_ready":ready,
            "bybit_feed_replaced_or_verified":False,
            "closed_bar_compare":diffs}


def capture(policy_file,output):
    if output.exists():raise ValueError("refuse_overwrite")
    p=json.loads(policy_file.read_bytes())
    if (p["schema"]!="nexus.mr40.public-backup-source-alignment.v1"
        or p["safety"]["orders"]!=0 or p["safety"]["private_api"] is not False
        or p["safety"]["promote"] is not False):
        raise ValueError("frozen_protocol_invalid")
    now=int(time.time()*1000)
    anchors={
        "Bitget":"https://api.bitget.com/api/v3/market/candles?category=SPOT&symbol=BTCUSDT&interval=4H&limit=8",
        "LBank":("https://api.lbank.info/v2/kline.do?symbol=btc_usdt&size=8&type=hour4&time="
                 +str(now//1000-48*3600))
    }
    sources={}
    rows={}
    for venue in SOURCES:
        url=anchors[venue]
        req=urllib.request.Request(url,headers={"User-Agent":"NEXUS-Research-Public-Only/1.0"})
        with urllib.request.urlopen(req,timeout=8) as result:
            if result.status!=200:raise ValueError("public_http_status_not_200")
            raw=result.read(100000)
        # Sensitive data disallowed: public GET URLs only, no keys or Authorization.
        t=int(time.time()*1000)
        market=normalized_rows(raw,venue)
        rows[venue]=market
        sources[venue]={"endpoint":url,
                        "http_status":200,"received_utc_ms":t,
                        "raw_sha256":hashlib.sha256(raw).hexdigest(),
                        "raw_json":json.loads(raw),
                        "parsed_bars":len(market)}
    # Conservative: use the earlier of completion times for causal gating.
    gate_ms=min(sources[x]["received_utc_ms"] for x in SOURCES)
    comparison=overlap(rows["Bitget"],rows["LBank"],gate_ms)
    doc={"schema":"nexus.mr40.public-backup-source-alignment.results.v1",
         "protocol_sha256":hashlib.sha256(policy_file.read_bytes()).hexdigest(),
         "venues":["Bitget","LBank"],"bybit_live_available":False,
         "uses_market_data_only":True,"historically_seen_session_date":True,
         "genuinely_unseen_forward_strategy_sample":False,
         "paper_changed":False,"actual_orders":0,"promote":False,
         "sources":sources,"alignment":comparison}
    doc["digest"]=hashlib.sha256(canon(doc)).hexdigest()
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(doc,ensure_ascii=False,sort_keys=True,indent=2)+"\n",encoding="utf8")
    print(json.dumps({"digest":doc["digest"],"research_only":True,"alignment":comparison},ensure_ascii=False))


if __name__=="__main__":
    a=argparse.ArgumentParser()
    a.add_argument("--policy",required=True,type=Path)
    a.add_argument("--output",required=True,type=Path)
    args=a.parse_args()
    capture(args.policy,args.output)
