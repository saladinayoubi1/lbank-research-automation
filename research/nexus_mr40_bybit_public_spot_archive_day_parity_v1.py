"""Research ONLY: official Bybit Spot daily trade CSV -> 1m -> 4h source audit.

Pure public archive GET. No websocket, broker/client order, API key, Paper,
current quote, trading data mutation, profit assumptions or promotion.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import io
import json
import urllib.request
from collections import defaultdict
from datetime import datetime,timezone
from decimal import Decimal as D
from pathlib import Path

STEP1=60000
STEP4=14_400_000
START=1792368000000  # 2026-10-19T00:00:00Z
END=START+86400000
ARCHIVE_URL="https://public.bybit.com/spot/BTCUSDT/BTCUSDT_2026-10-19.csv.gz"
ROWS_SHA="a458d9f83df633df8ee5cab5f2a19de41c4c79c61185b5abd258fdefa80d575a"
HEADER=["id","timestamp","price","volume","side","rpi"]
MAX_DL=12_000_000
LIMIT_PRICE=D("0.01")
LIMIT_VOL=D("0.001")


def canon(v):
    return json.dumps(v,sort_keys=True,separators=(",",":"),ensure_ascii=False,allow_nan=False).encode()


def utc(ms):
    return datetime.fromtimestamp(ms/1000,timezone.utc).isoformat()


def assert_valid_trade(row):
    if set(row)!=set(HEADER):raise ValueError("malformed_trade_schema")
    stamp=int(row["timestamp"]);px=D(row["price"]);volume=D(row["volume"])
    if not START<=stamp<END:raise ValueError("out_of_locked_utc_day")
    if not (px.is_finite() and volume.is_finite() and px>0 and volume>0):
        raise ValueError("nonpositive_or_invalid_trade")
    if row["side"].lower() not in ("buy","sell") or row["rpi"] not in ("0","1"):
        raise ValueError("unexpected_trade_metadata")
    return stamp,px,volume


def parse_archive(raw):
    # CRC32 and truncated gzip are validated by full decompression.
    content=gzip.decompress(raw)
    reader=csv.DictReader(io.StringIO(content.decode("utf8-sig"),newline=""))
    if reader.fieldnames!=HEADER:raise ValueError("unexpected_csv_headers")
    seen=set(); trades=[]
    for line_idx,row in enumerate(reader):
        stamp,px,quantity=assert_valid_trade(row)
        tradeid=row["id"]
        if not tradeid or tradeid in seen:raise ValueError("empty_or_duplicate_trade_id")
        seen.add(tradeid)
        trades.append((stamp,line_idx,px,quantity))
    if not trades:raise ValueError("no_trades_in_archive")
    trades.sort(key=lambda r:(r[0],r[1]))
    return content,trades


def aggregate(trades):
    bars1={}
    bars4={}
    def advance(bars,key,px,quantity):
        if key not in bars:
            bars[key]=[px,px,px,px,quantity,1]
        else:
            x=bars[key];x[1]=max(x[1],px);x[2]=min(x[2],px);x[3]=px
            x[4]+=quantity;x[5]+=1
    for t,_,price,qty in trades:
        advance(bars1,t//STEP1*STEP1,price,qty)
        advance(bars4,t//STEP4*STEP4,price,qty)
    return bars1,bars4


def rebuilt_from_1m(bars1):
    rebuilt={}
    for ts in range(START,END,STEP4):
        samples=[bars1.get(ts+i*STEP1) for i in range(240)]
        if any(x is None for x in samples):
            continue
        rebuilt[ts]=[
            samples[0][0],max(x[1] for x in samples),min(x[2] for x in samples),
            samples[-1][3],sum((x[4] for x in samples),D(0)),
            sum(x[5] for x in samples)
        ]
    return rebuilt


def frozen_candles(folder):
    a=json.loads((folder/"bybit_prepared_inputs.json").read_bytes())["rows"]
    b=json.loads((folder/"bybit_october_input_extension.json").read_bytes())["rows"]
    raw=a+b
    if hashlib.sha256(canon(raw)).hexdigest()!=ROWS_SHA:
        raise ValueError("frozen_market_snapshot_SHA_changed")
    subset={x[0]:[D(str(v)) for v in x[1:6]] for x in raw if START<=x[0]<END}
    return subset


def compare(trades,frozen,protocol):
    bars1,bars4=aggregate(trades)
    rebuilt=rebuilt_from_1m(bars1)
    expected_starts=list(range(START,END,STEP4))
    expected_minutes=list(range(START,END,STEP1))
    complete=(sorted(bars1)==expected_minutes and sorted(bars4)==expected_starts
              and sorted(rebuilt)==expected_starts and sorted(frozen)==expected_starts)
    detail=[]
    for ts in expected_starts:
        t=bars4.get(ts);m=rebuilt.get(ts);f=frozen.get(ts)
        values_equal=(t==m) if t is not None and m is not None else False
        prices=[str(abs(t[i]-f[i])) for i in range(4)] if t and f else []
        volume_err=str(abs(t[4]-f[4])) if t and f else None
        volume_rel=(abs(t[4]-f[4])/max(t[4],f[4])) if t and f and max(t[4],f[4])>0 else None
        pass_now=(bool(values_equal) and t is not None and f is not None
                  and all(D(v)<=LIMIT_PRICE for v in prices)
                  and volume_rel is not None and volume_rel<=LIMIT_VOL)
        detail.append({
            "utc_start":utc(ts),
            "raw_trades_4h":t[5] if t else 0,
            "raw_trade_ohlcv":([str(x) for x in t[:5]] if t else None),
            "minute_rebuilt_matches_trade_4h":values_equal,
            "frozen_4h_ohlcv":([str(x) for x in f] if f else None),
            "price_abs_diffs_usdt":prices,
            "base_volume_abs_diff":volume_err,
            "base_volume_rel_diff":(str(volume_rel) if volume_rel is not None else None),
            "candidate_4h_source_parity":pass_now,
        })
    passed=complete and all(x["candidate_4h_source_parity"] for x in detail)
    return {
        "source_day":"2026-10-19","same_venue":"Bybit Spot BTCUSDT",
        "historical_previously_seen":True,
        "trade_count":len(trades),"one_minute_buckets_present":len(bars1),
        "expected_one_minute_buckets":1440,
        "four_hour_buckets_present":len(bars4),"expected_four_hour_buckets":6,
        "all_1440_minutes_contiguous":sorted(bars1)==expected_minutes,
        "six_4h_reconstructed_from_1m":len(rebuilt),
        "all_6_frozen_4h_present":sorted(frozen)==expected_starts,
        "strict_day_ohlcv_source_parity_pass":passed,
        "per_bar":detail,
        "bybit_public_REST_restored":False,
        "futures_data_used":False,
        "profit_or_fill_proven":False,
        "L2_parity_proven":False,
        "OOS_edge_proven":False,
    }


def execute(policy_file,source_folder,archive_path,output_file):
    if output_file.exists() or archive_path.exists():
        raise ValueError("refuse_overwrite_evidence")
    p=json.loads(policy_file.read_bytes())
    if (p["schema"]!="nexus.mr40.bybit_official_spot_archive_day_source_parity.v1"
        or p["known_metadata_before_lock"]["archive_url"]!=ARCHIVE_URL
        or p["source_pins"]["frozen_ohlcv_rows_sha256"]!=ROWS_SHA
        or p["qualification"]["max_price_absolute_usdt"]!="0.01"
        or p["qualification"]["max_volume_relative_difference"]!="0.001"
        or p["constraints"]["orders"]!=0 or p["constraints"]["promote"] is not False):
        raise ValueError("frozen_study_protocol_drift")
    req=urllib.request.Request(ARCHIVE_URL,headers={"User-Agent":"NEXUS-offline-public-archive-audit/1.0"})
    with urllib.request.urlopen(req,timeout=20) as resp:
        if resp.status!=200:raise ValueError("unexpected_archive_http_status")
        raw=resp.read(MAX_DL+1)
        date_header=resp.headers.get("Last-Modified")
    if len(raw)>MAX_DL or len(raw)!=p["known_metadata_before_lock"]["content_length_bytes"]:
        raise ValueError("archive_length_limit_or_changed")
    content,trades=parse_archive(raw)
    # Archive written only after verified raw gzip and trade headers.
    archive_path.parent.mkdir(parents=True,exist_ok=True)
    archive_path.write_bytes(raw)
    frozen=frozen_candles(source_folder)
    result=compare(trades,frozen,p)
    report={
        "schema":"nexus.mr40.bybit_spot_archive_day_parity.results.v1",
        "protocol_sha256":hashlib.sha256(policy_file.read_bytes()).hexdigest(),
        "archival_url":ARCHIVE_URL,
        "raw_archive_gz_size_bytes":len(raw),
        "raw_archive_sha256":hashlib.sha256(raw).hexdigest(),
        "decompressed_csv_sha256":hashlib.sha256(content).hexdigest(),
        "archive_server_last_modified":date_header,
        "download_source":"PUBLIC Bybit Spot trade archive, no REST V5",
        "frozen_source_4h_rows_digest":ROWS_SHA,
        "result":result,
        "paper_modified":False,"real_orders":0,"live":False,
        "private_api":False,"merge":False,"promote":False,
    }
    report["digest"]=hashlib.sha256(canon(report)).hexdigest()
    output_file.parent.mkdir(parents=True,exist_ok=True)
    output_file.write_text(json.dumps(report,sort_keys=True,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
    print(json.dumps({"digest":report["digest"],"archive_sha256":report["raw_archive_sha256"],
        "summary":{k:v for k,v in result.items() if k!="per_bar"},
        "bar_deltas":[{"utc_start":b["utc_start"],"price":b["price_abs_diffs_usdt"],
                        "volume":b["base_volume_rel_diff"],"pass":b["candidate_4h_source_parity"]}
                      for b in result["per_bar"]]},ensure_ascii=False))


if __name__=="__main__":
    a=argparse.ArgumentParser()
    for name in ("policy","sources","archive","output"):
        a.add_argument("--"+name,required=True,type=Path)
    args=a.parse_args()
    execute(args.policy,args.sources,args.archive,args.output)
