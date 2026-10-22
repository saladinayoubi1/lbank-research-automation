"""Descriptive-only observed BTC spot 1-minute stop-threshold trace.

This does NOT relax failed exact OHLC parity, estimate order-book depth,
estimate executable stop fill, or run a trading strategy.
"""
from __future__ import annotations
import argparse,hashlib,json
from decimal import Decimal as D
from pathlib import Path
from datetime import datetime,timezone

RAW_SHA="b6c9b7aa60334f72c7fc9218f9edfa7d1c506aaf45c2d8ef74783887fbd4f096"
PARENT_DIGEST="555dce436bb17c454bcb3bf17f10ced98e5e19ebcf70c34d9f29dae1001b7368"
T0=1760112000000;T1=1760155200000
def canon(o):return json.dumps(o,sort_keys=True,separators=(",",":"),ensure_ascii=False,allow_nan=False).encode()
def iso(ms):return datetime.fromtimestamp(ms/1000,timezone.utc).isoformat()
def main(raw_file,strict_audit,protocol,output):
    if output.exists():raise ValueError("no_overwrite")
    proto=json.loads(protocol.read_bytes())
    if proto["schema"]!="mr40.20251010.minute-price-trace.v1" or proto["raw_api_sha256"]!=RAW_SHA or proto["parent_primary_result_digest"]!=PARENT_DIGEST:raise ValueError("protocol_invalid")
    raw=raw_file.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=RAW_SHA:raise ValueError("not_original_response")
    orig=json.loads(strict_audit.read_bytes())
    d=orig.pop("digest")
    if d!=PARENT_DIGEST or hashlib.sha256(canon(orig)).hexdigest()!=d or orig["four_hour_parity_pass"] is not False:raise ValueError("primary_gate_not_failed")
    for block in orig["four_hour_reconciliation"]:
        if any(x!=0 for x in block["absolute_deltas_usdt"][1:]):raise ValueError("hlc_not_reconciled")
    response=json.loads(raw)
    if response["retCode"]!=0 or response["result"]["category"]!="spot" or response["result"]["symbol"]!="BTCUSDT":raise ValueError("venue_mismatch")
    data=sorted((r for r in response["result"]["list"] if T0<=int(r[0])<T1),key=lambda x:int(x[0]))
    if [int(r[0]) for r in data]!=list(range(T0,T1,60000)):raise ValueError("minute_gap")
    entry=D(proto["entry_price"]);stop=entry*D(".96")
    hits=[(i,row) for i,row in enumerate(data) if D(row[3])<=stop]
    if not hits:raise ValueError("no_observed_stop_touch")
    i,row=hits[0]
    v=lambda j:{"utc":iso(int(data[j][0])),"open":data[j][1],"high":data[j][2],"low":data[j][3],"close":data[j][4]}
    worst_i=min(range(i,min(i+5,len(data))),key=lambda j:D(data[j][3]))
    final={"schema":"mr40.20251010.descriptive-minute-price-trace.results.v1",
       "raw_api_sha256":RAW_SHA,"primary_audit_digest":PARENT_DIGEST,
       "primary_4h_parity_pass":False,
       "observed_first_touch":{"minute":i,"utc":iso(int(row[0])),
         "minutes_since_entry_open":i,"stop_reference_usdt_per_btc":str(stop),
         "ohlc":v(i),"btc_traded_volume_in_minute":row[5],"reported_quote_turnover_usdt_in_minute":row[6],
         "minute_open_below_reference":D(row[1])<=stop,
         "close_below_reference":D(row[4])<stop,
         "low_below_reference_pct":round(100*float(1-D(row[3])/stop),5),
         "close_below_reference_pct":round(100*float(1-D(row[4])/stop),5)},
       "preceding_minute_close":data[i-1][4] if i else None,
       "minute_after_touch":v(i+1) if i+1<len(data) else None,
       "minute_at_low_in_first_five":v(worst_i),
       "close_5_minutes_after_first_touch":data[i+5][4] if i+5<len(data) else None,
       "close_15_minutes_after_first_touch":data[i+15][4] if i+15<len(data) else None,
       "touched_in_first_4h_trade_bar":i<240,
       "no_execution_price_or_pnl":True,
       "limitations":["Underlying four-hour OPEN reconciliation failed: original strict study remains rejected",
          "One-minute OHLC cannot resolve intra-minute order sequencing",
          "A stop-market can fill worse due to spreads, order-book depth, execution latency, or exchange outages",
          "This is a historical diagnostic, not a new entry strategy or forecast"]}
    final["digest"]=hashlib.sha256(canon(final)).hexdigest()
    output.write_bytes(canon(final)+b"\n")
    print(json.dumps({"digest":final["digest"],"first_touch":final["observed_first_touch"],
                      "previous_close":final["preceding_minute_close"],
                      "next_minute":final["minute_after_touch"],
                      "worst_5min":final["minute_at_low_in_first_five"],
                      "primary_gate_pass":False},ensure_ascii=False),flush=True)

if __name__=="__main__":
    parser=argparse.ArgumentParser()
    for key in ("raw_file","strict_audit","protocol","output"):
        parser.add_argument("--"+key.replace("_","-"),required=True,type=Path)
    main(**vars(parser.parse_args()))
