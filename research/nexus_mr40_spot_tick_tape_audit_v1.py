"""Read-only BTCUSDT SPOT public trade tape audit on 2025-10-10.

Not a trading simulator. No account access, order requests, slippage or PNL estimates.
The 4h-to-1m exact parity gate in the parent study remains FAILED.
"""
from __future__ import annotations
import argparse,csv,datetime as dt,gzip,hashlib,io,json
from collections import defaultdict
from decimal import Decimal as D
from pathlib import Path

DAY_SHA="df094454ca458a41c0908fa0c15d73286804509b3eeb1330c98a4c53d13f487b"
MINUTE_SHA="b6c9b7aa60334f72c7fc9218f9edfa7d1c506aaf45c2d8ef74783887fbd4f096"
SCHEMA="mr40.bybit-spot-ticks.20251010.v1"
START=dt.datetime(2025,10,10,tzinfo=dt.timezone.utc)
DAY_START=int(START.timestamp()*1000)
DAY_END=DAY_START+86_400_000
UTC=lambda hour,minute=0: DAY_START+(hour*60+minute)*60000
WINDOW_START=UTC(20,54);WINDOW_END=UTC(21,4)
FOCUS_START=UTC(20,56);FOCUS_END=FOCUS_START+60000
STOP=D("114312.3916320000")
def iso(ms):return dt.datetime.fromtimestamp(ms/1000,dt.timezone.utc).isoformat(timespec="milliseconds")
def canon(x):return json.dumps(x,sort_keys=True,separators=(",",":"),ensure_ascii=False,allow_nan=False).encode()
def number(x):return str(x)
def main(archive,minute_source,policy_path,output):
    if output.exists():raise ValueError("refuse_overwrite")
    policy=json.loads(policy_path.read_bytes())
    if policy["schema"]!=SCHEMA or policy["expected_head_bytes"]!=16190304 or D(policy["existing_stop_price"])!=STOP:
        raise ValueError("protocol_drift")
    if archive.stat().st_size!=16190304:raise ValueError("full_archive_size_mismatch")
    if hashlib.sha256(archive.read_bytes()).hexdigest()!=DAY_SHA:raise ValueError("source_archive_digest_drift")
    original=minute_source.read_bytes()
    if hashlib.sha256(original).hexdigest()!=MINUTE_SHA:raise ValueError("minute_source_drift")
    minute_api=json.loads(original)
    spot=minute_api["result"]
    if minute_api["retCode"]!=0 or spot["symbol"]!="BTCUSDT" or spot["category"]!="spot":
        raise ValueError("wrong_minute_source_product")
    minute=next(r for r in spot["list"] if int(r[0])==FOCUS_START)
    minute_reference=[D(v) for v in minute[1:5]]
    h=hashlib.sha256()
    count=0;prev_ts=None;first_ts=None;last_ts=None;max_duplicate_ts=0
    day_first=None;day_last=None;event_count=0;event_vol=D(0);event_quote=D(0)
    event_low=None;event_high=None;event_first=None;event_last=None
    event_below_count=0;event_below_volume=D(0)
    first_cross=None;prev_print=None;first_recovery=None;last_below=None
    largest_down_price_gap=None;gap_timestamp=None
    focus_rows=[];seconds=defaultdict(lambda:{"count":0,"below_count":0,"base_volume":D(0),"below_volume":D(0),"high":None,"low":None})
    total_window=0;window_below=0
    minute_volumes=defaultdict(lambda:{"count":0,"btc_volume":D(0),"low":None,"high":None})
    with gzip.open(archive,"rt",encoding="utf-8-sig",newline="") as stream:
        reader=csv.DictReader(stream)
        fields=reader.fieldnames
        if fields!=["id","timestamp","price","volume","side","rpi"]:
            raise ValueError("unexpected_spot_trade_schema:"+str(fields))
        for row in reader:
            count+=1
            t=int(row["timestamp"]);price=D(row["price"]);v=D(row["volume"])
            if not(DAY_START<=t<DAY_END and price>0 and v>0 and row["side"] in ("buy","sell") and row["rpi"] in ("0","1")):
                raise ValueError("malformed_public_trade")
            if prev_ts is not None and t<prev_ts:raise ValueError("not_time_sorted")
            if prev_ts is not None and t==prev_ts:max_duplicate_ts+=1
            prev_ts=t
            if day_first is None:day_first=t
            day_last=t
            if not(WINDOW_START<=t<WINDOW_END):continue
            total_window+=1
            m_bucket=(t//60000)*60000
            m=minute_volumes[m_bucket];m["count"]+=1;m["btc_volume"]+=v
            m["high"]=price if m["high"] is None else max(m["high"],price)
            m["low"]=price if m["low"] is None else min(m["low"],price)
            if price<=STOP:window_below+=1
            if prev_print is not None:
                diff=price-prev_print[1]
                if largest_down_price_gap is None or diff<largest_down_price_gap:
                    largest_down_price_gap=diff;gap_timestamp=t
            if first_cross is None and price<=STOP:
                first_cross={"timestamp_ms":t,"utc":iso(t),"price":str(price),"volume_btc":str(v),
                             "side":row["side"],"previous_print":(
                             {"timestamp_ms":prev_print[0],"utc":iso(prev_print[0]),"price":str(prev_print[1])}
                             if prev_print else None)}
            elif first_cross is not None and first_recovery is None and price>=STOP:
                first_recovery={"timestamp_ms":t,"utc":iso(t),"price":str(price),
                                "elapsed_ms_after_first_cross":t-first_cross["timestamp_ms"]}
            if price<=STOP:last_below=t
            prev_print=(t,price)
            if FOCUS_START<=t<FOCUS_END:
                event_count+=1;event_vol+=v;event_quote+=v*price
                event_first=price if event_first is None else event_first
                event_last=price
                event_high=price if event_high is None else max(event_high,price)
                event_low=price if event_low is None else min(event_low,price)
                if price<=STOP:event_below_count+=1;event_below_volume+=v
                s_bucket=(t//1000)*1000
                d=seconds[s_bucket];d["count"]+=1;d["base_volume"]+=v
                d["high"]=price if d["high"] is None else max(d["high"],price)
                d["low"]=price if d["low"] is None else min(d["low"],price)
                if price<=STOP:d["below_count"]+=1;d["below_volume"]+=v
                focus_rows.append((str(t),str(price),str(v),row["side"],row["rpi"],row["id"]))
    if count==0 or not(day_first<FOCUS_START<day_last) or event_count==0:raise ValueError("incomplete_source_day")
    if [int(x[0]) for x in focus_rows]!=sorted(int(x[0]) for x in focus_rows):
        raise ValueError("focus_trade_time_order")
    tape=[event_first,event_high,event_low,event_last]
    price_diffs=[abs(a-b) for a,b in zip(tape,minute_reference)]
    parity=all(x<=D(".01") for x in price_diffs)
    window_minutes=[]
    for ts in range(WINDOW_START,WINDOW_END,60000):
        m=minute_volumes.get(ts)
        window_minutes.append({"utc":iso(ts),"count":m["count"] if m else 0,
                               "btc_volume":str(m["btc_volume"]) if m else "0",
                               "low":str(m["low"]) if m and m["low"] is not None else None,
                               "high":str(m["high"]) if m and m["high"] is not None else None})
    one_second=[{"utc":iso(t),"count":z["count"],"below_stop_count":z["below_count"],
                 "btc_volume":str(z["base_volume"]),"below_stop_btc_volume":str(z["below_volume"]),
                 "high":str(z["high"]),"low":str(z["low"])}
                for t,z in sorted(seconds.items())]
    report={
      "schema":"mr40.bybit-spot-trade-tape.audit.v1",
      "source":{"archive_url":policy["archive_url"],"day_archive_bytes":archive.stat().st_size,
                "day_archive_sha256":DAY_SHA,"schema":fields,"all_day_print_count":count,
                "first_print_utc":iso(day_first),"last_print_utc":iso(day_last),
                "adjacent_same_timestamp_ms_count":max_duplicate_ts},
      "policy_sha256":hashlib.sha256(policy_path.read_bytes()).hexdigest(),
      "parent_4h_exact_ohlc_parity_remains_failed":True,
      "minute_source_sha256":MINUTE_SHA,
      "minute_reference":{"start_utc":iso(FOCUS_START),"ohlc":[str(x) for x in minute_reference]},
      "tick_trade_ohlc":[str(x) for x in tape],
      "tick_vs_1minute_ohlc_abs_deltas":[str(x) for x in price_diffs],
      "one_minute_parity_pass":parity,
      "focus_minute_print_count":event_count,
      "focus_minute_btc_volume":str(event_vol),
      "focus_minute_quote_turnover_from_prints":str(event_quote),
      "focus_minute_print_count_at_or_below_stop":event_below_count,
      "focus_minute_btc_volume_at_or_below_stop":str(event_below_volume),
      "focus_minute_print_fraction_at_or_below_stop":event_below_count/event_count,
      "window_print_count":total_window,"window_print_count_at_or_below_stop":window_below,
      "window_minute_buckets":window_minutes,
      "focus_second_buckets":one_second,
      "cutout":{"start_utc":iso(FOCUS_START),"end_utc":iso(FOCUS_END),"columns":["timestamp_ms","price","volume_btc","taker_side","rpi","trade_id"]},
      "inference":"No bid/ask order book or user order execution. Public trades cannot prove fill price, stop slippage or PnL. No strategy rerun."
    }
    if parity:
        report["event"]={"reference_stop":str(STOP),"first_cross":first_cross,
                         "first_recovery_print_at_or_above_stop":first_recovery,
                         "last_trade_at_or_below_stop_utc":iso(last_below) if last_below is not None else None,
                         "max_print_to_print_downward_price_change":str(largest_down_price_gap),
                         "time_of_largest_observed_downward_print_jump":iso(gap_timestamp) if gap_timestamp else None,
                         "low_below_stop_pct":round(100*float((STOP-event_low)/STOP),6)}
    else:
        report["event"]={"accepted":False,"reason":"tick print OHLC diverged from pinned spot 1-minute candle; no source-reconciled event claim"}
    report["digest"]=hashlib.sha256(canon(report)).hexdigest()
    output.mkdir(parents=True)
    (output/"summary.json").write_bytes(canon(report)+b"\n")
    with gzip.open(output/"one_minute_trade_tape.csv.gz","wt",encoding="utf-8",newline="",mtime=None) as f:
        writer=csv.writer(f);writer.writerow(report["cutout"]["columns"]);writer.writerows(focus_rows)
    print(json.dumps({"source_sha":DAY_SHA,"day_trades":count,"focus_trades":event_count,
      "parity":parity,"diffs":[str(z) for z in price_diffs],
      "below":event_below_count,"below_btc":str(event_below_volume),
      "first_cross":report["event"].get("first_cross"),
      "recovery":report["event"].get("first_recovery_print_at_or_above_stop"),
      "low_below_pct":report["event"].get("low_below_stop_pct"),
      "digest":report["digest"]},ensure_ascii=False),flush=True)

if __name__=="__main__":
    p=argparse.ArgumentParser()
    for n in ("archive","minute_source","policy_path","output"):
        p.add_argument("--"+n.replace("_","-"),required=True,type=Path)
    main(**vars(p.parse_args()))
