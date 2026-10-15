"""Two-file Bybit OFFICIAL public spot raw trade acquisition proof, 2026-10-08.

Strictly READ-ONLY network GET (no private API, no credentials, no 403 retry,
no fallback service, no alternative origin); writes only to a fresh isolated
QA folder. Not a backtest, simulated trade, strategy promotion, or proof
that the preceding 90 days form a contiguous model-v2 market history.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import os
from pathlib import Path
from datetime import datetime,timezone

import requests

import bybit_spot_archive_audit as audit
import bybit_spot_backfill as backfill

SOURCE_BASE="https://public.bybit.com/spot"
SYMBOLS=("BTCUSDT","ETHUSDT")
DATE="2026-10-08"
CHUNK=1024*1024
MAX_BYTES=100_000_000
RESEARCH_ONLY=True
LIVE_ENABLED=False
AUTO_DEMO=False
ORDER_ACCESS=False


def fetch_into_fresh_dir(root:Path) -> dict:
    if root.exists():
        raise FileExistsError("Use a fresh isolated capture directory; no overwrite")
    if root.resolve() in (Path("C:/NEXUS").resolve(),Path("E:/NEXUS-QA").resolve()):
        raise ValueError("protected root selected")
    root.mkdir(parents=True,exist_ok=False)
    files=[]
    for symbol in SYMBOLS:
        filename=f"{symbol}_{DATE}.csv.gz"
        url=f"{SOURCE_BASE}/{symbol}/{filename}"
        dest=root/filename
        part=root/(filename+".part")
        if dest.exists() or part.exists():
            raise FileExistsError("source capture file must not already exist")
        h=hashlib.sha256()
        received=0
        # Explicit zero retries/redirects, no auth/session from NEXUS.
        with requests.Session() as session:
            with session.get(url,stream=True,timeout=(12,35),
                             allow_redirects=False,
                             headers={"Accept":"application/octet-stream"}) as resp:
                if resp.status_code!=200:
                    raise RuntimeError(f"official public archive unavailable HTTP {resp.status_code} for {symbol}; NO RETRY")
                cl=resp.headers.get("Content-Length")
                expected=int(cl) if cl and cl.isdecimal() else None
                if expected is not None and not 0<expected<=MAX_BYTES:
                    raise ValueError("unexpected public raw source file size")
                with part.open("xb") as sink:
                    for piece in resp.iter_content(chunk_size=CHUNK):
                        if not piece:
                            continue
                        received+=len(piece)
                        if received>MAX_BYTES:
                            raise ValueError("download size cap exceeded")
                        sink.write(piece)
                        h.update(piece)
                capture={
                    "symbol":symbol,"date_utc":DATE,"source_url":url,
                    "http_status":resp.status_code,
                    "content_length_header":expected,
                    "download_bytes":received,"sha256":h.hexdigest(),
                    "reported_last_modified":resp.headers.get("Last-Modified"),
                    "retrieved_at_utc":datetime.now(timezone.utc).isoformat(),
                }
        if received==0 or (expected is not None and received!=expected):
            raise ValueError("short/mismatched public source download")
        # Drain gzip including footer CRC/size check, without altering source.
        rows=0
        with gzip.open(part,"rt",encoding="utf-8",errors="strict",newline="") as gz:
            reader=csv.reader(gz)
            first=next(reader,None)
            if not first:
                raise ValueError("empty gzip data")
            for row in reader:
                if row:
                    rows+=1
            capture["first_csv_row"]=first[:8]
        if rows<100:
            raise ValueError("far too few archive source rows")
        capture["gzip_csv_data_rows"]=rows
        # Independently verify trade-side/price/id/daily-grid contracts
        # using existing NEXUS source validation.
        raw,decoder=audit.read_trade_archive(part)
        valid,quality=backfill.validate_trade_range(raw,symbol,DATE,DATE)
        if len(valid)<100 or quality.get("duplicate_trade_id_count",0) or quality.get("invalid_numeric_rows",0) or (
            quality.get("outside_range_rows",0)
        ):
            raise ValueError("raw market trade source validation rejected")
        capture["rows_validated"]=int(len(valid))
        capture["decoder"]=decoder
        capture["quality"]=quality
        os.replace(part,dest)
        files.append(capture)
    receipt={
        "schema":"nexus.elliott-v21-public-spot-raw-source-capture.v1",
        "disposition":"PASS_TWO_OFFICIAL_DAILY_RAW_SOURCE_FILES_ONLY",
        "research_only":True,"live_enabled":False,
        "auto_demo":False,"orders_placed":0,
        "network_access":"Only direct GET to public.bybit.com/spot, zero retries, no redirects",
        "source_provider":"Bybit public Spot trade archive",
        "source_date_utc":DATE,"files":files,
        "candidate_files_not_contiguous_with_v20":True,
        "prospective_v17_eligible":False,
        "no_old_archive_changes":True,
    }
    (root/"CAPTURE_RECEIPT.json").write_text(json.dumps(receipt,indent=2,sort_keys=True,default=str)+"\n",encoding="utf-8")
    return receipt


def main():
    p=argparse.ArgumentParser()
    p.add_argument("--new-root",type=Path,required=True)
    args=p.parse_args()
    r=fetch_into_fresh_dir(args.new_root)
    print(json.dumps({
        "disposition":r["disposition"],
        "symbol_sha256":{x["symbol"]:x["sha256"] for x in r["files"]},
        "byte_lengths":{x["symbol"]:x["download_bytes"] for x in r["files"]},
        "validated_rows":{x["symbol"]:x["rows_validated"] for x in r["files"]},
        "future_study_allowed":False,
    },sort_keys=True))


if __name__=="__main__":
    main()
