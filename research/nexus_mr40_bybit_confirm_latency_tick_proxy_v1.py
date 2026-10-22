"""Public Bybit Spot trade print timing sensitivity, OFFLINE research ONLY.

Source inputs are two SHA-pinned gzip archives previously verified, 20/21 Oct 2026.
This is HISTORICAL and NOT actual market fill / OOS performance; no trades.
"""
from __future__ import annotations
import argparse
import csv
import gzip
import hashlib
import json
from datetime import datetime,timezone
from decimal import Decimal as D
from pathlib import Path

DAY_MS=86_400_000
FOUR_MS=14_400_000
LATENCIES=(817,1500)
DAYS=("2026-10-20","2026-10-21")
ARCHIVE_SHA=(
 "4ad1f684eff798b925ae69fca6828820bf6086611af2935cb37b8b680cfba5d0",
 "120005f407c3d620cf866823d73ad78948792b88ccb957bcc575089de70db9e9",
)
EXPECTED_COUNTS=(1110780,974028)
HEADER=("id","timestamp","price","volume","side","rpi")
PROTOCOL="nexus.mr40.spot_archive_latency_sensitivity_20261022.v1"


def canon(obj):
    return json.dumps(obj,sort_keys=True,separators=(",",":"),ensure_ascii=False,allow_nan=False).encode()


def date_ms(name):
    return int(datetime.fromisoformat(name).replace(tzinfo=timezone.utc).timestamp()*1000)


def make_windows(day):
    base=date_ms(day)
    return [{
      "utc_fourhour_start_ms":base+k*FOUR_MS,
      "first_boundary_print":None,
      "cutoff_ms_to_first_print":{str(m):None for m in LATENCIES},
    } for k in range(6)]


def capture_print(windows,ts,px,ident):
    base=windows[0]["utc_fourhour_start_ms"]
    k=(ts-base)//FOUR_MS
    if not 0<=k<6:
        raise ValueError("outside_calendar_day")
    w=windows[k]
    start=w["utc_fourhour_start_ms"]
    if w["first_boundary_print"] is None:
        w["first_boundary_print"]={"timestamp_ms":ts,"price":str(px),"trade_id":ident}
    for offset in LATENCIES:
        if ts>=start+offset and w["cutoff_ms_to_first_print"][str(offset)] is None:
            w["cutoff_ms_to_first_print"][str(offset)]={"timestamp_ms":ts,"price":str(px),"trade_id":ident}


def parse_day(path,day,expected_sha,expected_count):
    if hashlib.sha256(path.read_bytes()).hexdigest()!=expected_sha:
        raise ValueError("official_spot_archive_sha256_changed")
    windows=make_windows(day)
    base=date_ms(day)
    last=None
    n=0
    with gzip.open(path,"rt",encoding="utf-8-sig",newline="") as f:
        reader=csv.DictReader(f)
        if tuple(reader.fieldnames or ())!=HEADER:
            raise ValueError("untrusted_spot_archive_csv_header")
        for row in reader:
            ts=int(row["timestamp"])
            if not base<=ts<base+DAY_MS:
                raise ValueError("official_trade_outside_expected_utc_day")
            if last is not None and ts<last:
                raise ValueError("nonmonotonic_spot_source_timestamp")
            last=ts
            px=D(row["price"])
            if not px.is_finite() or px<=0:
                raise ValueError("nonpositive_spot_trade_price")
            if not row["id"]:
                raise ValueError("missing_trade_id")
            capture_print(windows,ts,px,row["id"])
            n+=1
    if n!=expected_count:
        raise ValueError("changed_source_trade_count")
    for w in windows:
        if w["first_boundary_print"] is None:
            raise ValueError("missing_reference_fourhour_start_print")
        for delay in LATENCIES:
            if w["cutoff_ms_to_first_print"][str(delay)] is None:
                raise ValueError("no_delayed_print_within_same_fourhour_bar")
    return windows,n


def summarize(windows):
    data=[]
    for day in windows:
        for w in day:
            baseline=w["first_boundary_print"]
            p0=D(baseline["price"])
            for delay in LATENCIES:
                px=w["cutoff_ms_to_first_print"][str(delay)]
                pd=D(px["price"])
                signed=(pd-p0)/p0*D(10000)
                data.append({
                    "boundary_utc":datetime.fromtimestamp(w["utc_fourhour_start_ms"]/1000,timezone.utc).isoformat(),
                    "latency_assumption_ms":delay,
                    "reference_trade_price":str(p0),
                    "reference_trade_offset_ms":baseline["timestamp_ms"]-w["utc_fourhour_start_ms"],
                    "first_trade_after_cutoff_price":str(pd),
                    "first_trade_after_cutoff_offset_ms":px["timestamp_ms"]-w["utc_fourhour_start_ms"],
                    "signed_spot_trade_price_delta_bps":str(signed),
                    "hypothetical_buy_adverse_if_positive":signed>0,
                    "hypothetical_sell_adverse_if_negative":signed<0,
                    "real_order_fill_proven":False,
                })
    stats={}
    for delay in LATENCIES:
        subset=[D(x["signed_spot_trade_price_delta_bps"]) for x in data if x["latency_assumption_ms"]==delay]
        stats[str(delay)]={
            "samples":len(subset),
            "mean_signed_bps":str(sum(subset,D(0))/len(subset)),
            "mean_absolute_bps":str(sum(map(abs,subset),D(0))/len(subset)),
            "minimum_signed_bps":str(min(subset)),
            "maximum_signed_bps":str(max(subset)),
            "worst_absolute_bps":str(max(map(abs,subset))),
            "price_up_count":sum(x>0 for x in subset),
            "price_down_count":sum(x<0 for x in subset),
            "unchanged_count":sum(x==0 for x in subset),
            "not_executable_fill_or_slippage":True,
        }
    return data,stats


def run(lock,archive_dir,output):
    if output.exists():
        raise ValueError("refuse_overwrite")
    p=json.loads(lock.read_bytes())
    if (p.get("schema")!=PROTOCOL
        or tuple(p["historical_sample"]["full_days_utc"])!=DAYS
        or tuple(p["historical_sample"]["archive_gzip_sha256"])!=ARCHIVE_SHA
        or tuple(p["historical_sample"]["archive_day_trade_counts"])!=EXPECTED_COUNTS
        or tuple(p["cost_free_tick_proxy"]["latency_cases_ms"])!=LATENCIES
        or p["safety"]["real_orders"]!=0 or p["safety"]["promote"] is not False):
        raise ValueError("latency_protocol_locked_fields_changed")
    days=[]
    counts=[]
    for i,date in enumerate(DAYS):
        source=archive_dir/("Bybit_BTCUSDT_Spot_"+date+".csv.gz")
        w,n=parse_day(source,date,ARCHIVE_SHA[i],EXPECTED_COUNTS[i])
        days.append(w)
        counts.append(n)
    point_rows,stats=summarize(days)
    if len(point_rows)!=len(DAYS)*6*len(LATENCIES):
        raise ValueError("not_exactly_twelve_fixed_fourhour_boundaries")
    report={
        "schema":"nexus.mr40.bybit_spot_latency_fixed_boundaries.results.v1",
        "protocol_sha256":hashlib.sha256(lock.read_bytes()).hexdigest(),
        "classification":"HISTORICAL_ALREADY_SEEN_TRADE_PRINT_TIMING_PROXY__NOT_PNL_OR_FILL",
        "market_source":"Bybit BTCUSDT Spot official trade archives; not LBank or Bitget",
        "source_days":list(DAYS),"source_gzip_sha256":list(ARCHIVE_SHA),
        "trades_parsed":counts,
        "independent_true_fourhour_ws_receipt_assumption_ms":816.2316,
        "causally_rounded_first_eligible_trade_offset_ms":817,
        "stress_trade_offset_ms":1500,
        "n_fixed_fourhour_boundaries":12,
        "fixed_cutoff_comparison_rows":point_rows,
        "cost_free_price_delta_statistics_bps":stats,
        "buy_sell_direction_not_selected":True,
        "trade_prints_not_actionable_market_order_fills":True,
        "spread_fee_depth_size_order_impact_not_modeled":True,
        "no_mr40_entry_event_measured_on_these_12_bars":True,
        "no_automatic_paper_signal_promotion":True,
        "paper_changed":False,"orders":0,"live":False,"private_api":False
    }
    report["digest"]=hashlib.sha256(canon(report)).hexdigest()
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(report,sort_keys=True,indent=2,ensure_ascii=False)+"\n",encoding="utf8")
    print(json.dumps({"digest":report["digest"],"sample_days":DAYS,
       "trades":counts,"stats":stats},ensure_ascii=False))


if __name__=="__main__":
    ap=argparse.ArgumentParser()
    ap.add_argument("--lock",required=True,type=Path)
    ap.add_argument("--archive-dir",required=True,type=Path)
    ap.add_argument("--output",required=True,type=Path)
    args=ap.parse_args()
    run(args.lock,args.archive_dir,args.output)
