"""No-order historical MR40 last-pair Bybit SPOT trade-print timing markout.

Not a fill simulator. This is NOT OOS, never uses Bybit private API/Paper.
Fixed latest signal pair Oct14 16:00 ENTRY, Oct19 04:00 EXIT.
"""
from __future__ import annotations
import argparse,csv,gzip,hashlib,io,json,urllib.request
from datetime import datetime,timezone
from decimal import Decimal as D
from pathlib import Path
from research.nexus_mr40_independent_closed_signal_v1 import (
    frozen_rows,ClosedMR40,STEP as STEP4)
from research.nexus_mr40_bybit_confirm_latency_tick_proxy_v1 import canon,date_ms

URL_PREFIX="https://public.bybit.com/spot/BTCUSDT/BTCUSDT_"
DAYS=("2026-10-14","2026-10-19")
OPEN_MOMENTS=("2026-10-14T16:00:00+00:00","2026-10-19T04:00:00+00:00")
EVENT_IDX=(8481,8508)
LAT=(0,817,1500)
QUOTE=D("500")
MAX_DOWNLOAD=16_000_000
SOURCE_HEAD_OCT14=7_328_212
SOURCE_HEAD_OCT19=6_221_547
SOURCE_SHA_OCT19="7e092815d5be383a04156be15e7f679decb05811b769ea8b8826d36247b934ec"
HEADER=("id","timestamp","price","volume","side","rpi")
SCHEMA="nexus.mr40.latest_completed_signal_pair_4h_execution_proxy.v1"


def expected_event_schedule(folder):
    source=frozen_rows(folder)
    m=ClosedMR40()
    signals=[]
    for row in source:
        item=m.feed(row,confirmed=True,source_verified=True)
        if item.first_entry_close or item.natural_exit_close:
            signals.append((item.start_ms+STEP4,"ENTRY" if item.first_entry_close else "EXIT",item.bar_index))
    if (len(signals)!=94
        or len([x for x in signals if x[1]=="ENTRY"])!=47
        or len([x for x in signals if x[1]=="EXIT"])!=47
        or tuple(x[2] for x in signals[-2:])!=EVENT_IDX
        or signals[-2][1]!="ENTRY"
        or signals[-1][1]!="EXIT"):
        raise ValueError("not_last_completed_frozen_MR40_signal_pair")
    expected=tuple(int(datetime.fromisoformat(s).timestamp()*1000) for s in OPEN_MOMENTS)
    if tuple(x[0] for x in signals[-2:])!=expected:
        raise ValueError("unexpected_last_pair_next_open_times")
    return expected


def get_public_day(date,folder):
    destination=folder/("Bybit_BTCUSDT_Spot_"+date+".csv.gz")
    if date=="2026-10-19":
        if not destination.exists() or hashlib.sha256(destination.read_bytes()).hexdigest()!=SOURCE_SHA_OCT19:
            raise ValueError("prior_pinned_Oct19_public_source_unavailable_or_modified")
        raw=destination.read_bytes()
        return destination,{"day":date,"gzip_bytes":len(raw),"gzip_sha256":SOURCE_SHA_OCT19,"source":"previously_SHA_pinned_public_archive"}
    if destination.exists():
        raise ValueError("refuse_overwrite_public_Oct14_source_archive")
    url=URL_PREFIX+date+".csv.gz"
    with urllib.request.urlopen(urllib.request.Request(url,method="HEAD",headers={"User-Agent":"NEXUS-fixed-historical-research"}),timeout=12) as head:
        content_length=int(head.headers["Content-Length"])
        if head.status!=200 or content_length!=SOURCE_HEAD_OCT14:
            raise ValueError("Oct14_HEAD_size_or_status_changed")
    with urllib.request.urlopen(urllib.request.Request(url,headers={"User-Agent":"NEXUS-fixed-historical-research"}),timeout=25) as response:
        raw=response.read(MAX_DOWNLOAD+1)
        if response.status!=200:
            raise ValueError("Oct14_GET_not_HTTP200")
    if len(raw)!=SOURCE_HEAD_OCT14 or len(raw)>MAX_DOWNLOAD:
        raise ValueError("Oct14_gzip_length_mismatch")
    # CRC: explicitly fully decompress once before source is accepted.
    uncompressed=gzip.decompress(raw)
    if len(uncompressed)<100000:
        raise ValueError("Oct14_source_csv_truncated")
    folder.mkdir(parents=True,exist_ok=True)
    destination.write_bytes(raw)
    return destination,{"day":date,"gzip_bytes":len(raw),"gzip_sha256":hashlib.sha256(raw).hexdigest(),
       "csv_sha256":hashlib.sha256(uncompressed).hexdigest(),"source":"new_official_Spot_csv.gz_public_GET_after_locked_date_selection"}


def inspect_trade_day(path,date,target_ms):
    start=date_ms(date)
    end=start+86_400_000
    if target_ms<start or target_ms>=end or target_ms%STEP4:
        raise ValueError("target_window_not_same_utc_day_or_unaligned")
    found={key:None for key in LAT}
    last=None
    ids=set()
    trade_count=0
    with gzip.open(path,mode="rt",encoding="utf-8-sig",newline="") as f:
        reader=csv.DictReader(f)
        if tuple(reader.fieldnames or ())!=HEADER:
            raise ValueError("unexpected_Spot_trade_fields")
        for r in reader:
            ts=int(r["timestamp"]);trade_id=r["id"]
            if not start<=ts<end:raise ValueError("trade_timestamp_outside_locked_day")
            if last is not None and ts<last:raise ValueError("source_trade_timestamps_not_monotonic")
            last=ts
            if not trade_id or trade_id in ids:
                raise ValueError("invalid_or_duplicate_source_trade_id")
            ids.add(trade_id)
            px=D(r["price"]);volume=D(r["volume"])
            if not all(v.is_finite() and v>0 for v in (px,volume)):
                raise ValueError("invalid_spot_price_or_volume")
            if r["side"].lower() not in ("buy","sell") or r["rpi"] not in ("0","1"):
                raise ValueError("unrecognized_spot_trade_fields")
            if target_ms<=ts<target_ms+STEP4:
                for lag in LAT:
                    if found[lag] is None and ts>=target_ms+lag:
                        found[lag]={"timestamp_ms":ts,"delay_from_candle_open_ms":ts-target_ms,
                                    "price":str(px),"trade_id":trade_id}
            trade_count+=1
    if any(v is None for v in found.values()):
        raise ValueError("missing_spot_print_on_selected_exit_or_entry_time")
    return found,trade_count


def stats_pair(entry,exit):
    base_en=D(entry[0]["price"])
    base_ex=D(exit[0]["price"])
    result=[]
    for lag in LAT:
        en=D(entry[lag]["price"]);ex=D(exit[lag]["price"])
        buy_delta=(en-base_en)/base_en*D(10000)
        sell_delta=(base_ex-ex)/base_ex*D(10000)
        gross_pct=(ex/en-D(1))*D(100)
        gross_quote=QUOTE*(ex/en-D(1))
        result.append({
            "latency_ms":lag,
            "entry_reference_print":entry[lag],
            "exit_reference_print":exit[lag],
            "entry_buy_adverse_vs_zero_lag_bps":str(buy_delta),
            "exit_sell_adverse_vs_zero_lag_bps":str(sell_delta),
            "hypothetical_unfilled_full_500_quote_gross_return_pct":str(gross_pct),
            "hypothetical_unfilled_full_500_quote_gross_markout_usdt":str(gross_quote),
            "signal_trade_executed":False
        })
    baseline=D(result[0]["hypothetical_unfilled_full_500_quote_gross_markout_usdt"])
    for item in result:
        item["gross_markout_delta_vs_zero_lag_reference_USDT"]=str(
            D(item["hypothetical_unfilled_full_500_quote_gross_markout_usdt"])-baseline)
    return result


def run(protocol,source_inputs,archive_dir,output):
    if output.exists():raise ValueError("refuse_overwrite_last_pair_evidence")
    p=json.loads(protocol.read_bytes())
    wanted=p["latest_completed_pair"]
    if (p.get("schema")!=SCHEMA
        or wanted["entry_next_open_utc"]!="2026-10-14T16:00:00Z"
        or wanted["exit_next_open_utc"]!="2026-10-19T04:00:00Z"
        or tuple(wanted["source_days_only"])!=DAYS
        or tuple([p["latency_cases"]["reference_ms"],
                  p["latency_cases"]["after_public_confirm_receipt_ceil_ms"],
                  p["latency_cases"]["stress_ms"]])!=LAT
        or p["constraints"]["orders"]!=0 or p["constraints"]["promote"] is not False):
        raise ValueError("last_completed_pair_protocol_drift")
    event_times=expected_event_schedule(source_inputs)
    evidence=[]
    found=[]
    for date,t in zip(DAYS,event_times):
        filepath,receipt=get_public_day(date,archive_dir)
        samples,count=inspect_trade_day(filepath,date,t)
        receipt["complete_day_spot_trade_print_count"]=count
        evidence.append(receipt)
        found.append(samples)
    comparisons=stats_pair(found[0],found[1])
    report={
        "schema":"nexus.mr40.latest_completed_pair_spot_4h_print_timing_proxy.results.v1",
        "protocol_sha256":hashlib.sha256(protocol.read_bytes()).hexdigest(),
        "frozen_independent_signal_indices":list(EVENT_IDX),
        "events_utc":list(OPEN_MOMENTS),
        "source_days_utc":list(DAYS),
        "public_trade_archive_sha_receipts":evidence,
        "trade_print_markouts_not_fills":comparisons,
        "gross_quote_notional_illustration_usdt":"500",
        "signal_dates_preselected_from_frozen_history":True,
        "data_classification":"HISTORICAL_POSTHOC_EXECUTION_COST_PROXY",
        "real_order_fill_or_actual_MR40_PNL_proven":False,
        "broker_spread_depth_and_fees_not_modeled":True,
        "paper_changed":False,"orders":0,"private_api":False,"live":False,"promote":False
    }
    report["digest"]=hashlib.sha256(canon(report)).hexdigest()
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(report,sort_keys=True,indent=2,ensure_ascii=False)+"\n",encoding="utf8")
    print(json.dumps({"digest":report["digest"],"days":evidence,
                      "comparisons":comparisons},ensure_ascii=False))


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    for x in ("protocol","source_inputs","archive_dir","output"):
        parser.add_argument("--"+x,required=True,type=Path)
    run(**vars(parser.parse_args()))
