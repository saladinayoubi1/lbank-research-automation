"""Offline-only source gap inventory for NEXUS Elliott V20.

File-presence discovery is NOT a provider-authenticity attestation. Never
treat a filename as proof of market data, fill missing bars, call exchange
APIs, invoke strategy signals/backtests, or overwrite the V19 v2 pilot.
"""
from __future__ import annotations

import argparse
from datetime import date, timedelta
from hashlib import sha256
import json
import os
from pathlib import Path
import re

START = date(2026,8,2)
END = date(2026,10,15)
SYMBOLS = ("BTCUSDT","ETHUSDT")
DAY_RE = re.compile(r"^(BTCUSDT|ETHUSDT)_(2026-\d{2}-\d{2})\.csv\.gz$", re.I)
MONTH_RE = re.compile(r"^(BTCUSDT|ETHUSDT)-(2026-\d{2})\.csv\.gz$", re.I)
RESEARCH_ONLY = True
LIVE_ENABLED = AUTO_DEMO = ORDERS_PLACED = False


def file_sha(path:Path)->str:
    h=sha256()
    with path.open("rb") as f:
        for buf in iter(lambda:f.read(1024*1024),b""):
            h.update(buf)
    return h.hexdigest()


def days(start:date=START,end:date=END)->list[date]:
    if end<start:
        raise ValueError("invalid period")
    result=[]
    at=start
    while at<=end:
        result.append(at)
        at+=timedelta(days=1)
    return result


def gather_local_names(roots:list[Path]) -> dict:
    """Discover only cached .csv.gz candidate filenames; never download."""
    filenames={}
    absent=[]
    for root in roots:
        if not root.is_dir():
            absent.append(str(root))
            continue
        for parent, dirs, files in os.walk(root,followlinks=False):
            dirs[:]=[x for x in dirs if not (Path(parent)/x).is_symlink()]
            for name in files:
                d=DAY_RE.fullmatch(name)
                m=MONTH_RE.fullmatch(name)
                if not d and not m:
                    continue
                match=d if d is not None else m
                sym,period=match.groups()
                if sym.upper() not in SYMBOLS:
                    continue
                # Real paths are retained for local forensic use but NOT
                # transmitted as raw source bytes.
                key=(sym.upper(), "daily" if d else "monthly", period)
                filenames.setdefault(key,[]).append(Path(parent)/name)
    return {"files":filenames,"unavailable_search_roots":absent}


def snapshot_v19_pilot(pilot:Path)->dict:
    receipt=pilot/"V19_QA_RECEIPT.json"
    if not receipt.is_file():
        raise ValueError("source-qualified V19 pilot receipt absent")
    doc=json.loads(receipt.read_text(encoding="utf-8"))
    if doc.get("disposition")!="PASS_TWO_DAY_OFFLINE_V2_ARCHIVE_NO_FUTURE_BRIDGE" or (
        doc.get("july31_material_mismatches")!=0 or
        doc.get("july31_field_comparisons")!=1260 or
        doc.get("prospective_bridge_complete") is not False
    ):
        raise ValueError("V19 pilot receipt cannot qualify source")
    if doc.get("network_requests")!=0 or doc.get("orders_placed")!=0:
        raise ValueError("V19 pilot has unexpected authority")
    archive=doc.get("source_archives",[])
    frames=doc.get("timeframe_series",{})
    if len(archive)!=4 or set(frames)!=set(SYMBOLS):
        raise ValueError("incomplete V19 source inventory")
    hashes=[]
    for symbol in SYMBOLS:
        if set(frames[symbol])!={"minute15","hour1","hour4"}:
            raise ValueError("incomplete V19 15m/1h/4h streams")
        alias=symbol.lower().replace("usdt","_usdt")
        for tf, record in frames[symbol].items():
            path=pilot/"bybit_market"/alias/(tf+".parquet")
            if not path.is_file() or file_sha(path)!=record["sha256"]:
                raise ValueError("V19 frozen local parquet SHA256 mismatch")
            hashes.append(record["sha256"])
    return {"v19_pilot_present":True,"v19_pilot_6_parquet_hashes_verified":True,
            "two_day_range":"2026-07-31..2026-08-01",
            "source_files_reported":len(archive),
            "frozen_parquet_hashes":hashes,
            "future_source_proven":False}


def coverage_from_names(found:dict,*,start:date=START,end:date=END)->dict:
    located=found["files"]
    unavailable=[]
    opportunities=[]
    present_by_symbol={s:0 for s in SYMBOLS}
    for day in days(start,end):
        date_s=day.isoformat()
        for symbol in SYMBOLS:
            daily=located.get((symbol,"daily",date_s),[])
            month=located.get((symbol,"monthly",date_s[:7]),[])
            if daily or month:
                present_by_symbol[symbol]+=1
                opportunities.append({
                    "symbol":symbol,"date_utc":date_s,
                    "candidate_file_type":"daily" if daily else "monthly",
                    "file_name_only_unverified":True,
                    "matching_local_candidates":len(daily or month),
                })
            else:
                unavailable.append({"symbol":symbol,"date_utc":date_s,
                                    "reason":"NO_LOCAL_DAILY_OR_MONTHLY_RAW_GZIP_FOUND"})
    return {
        "required_date_range_utc":{"start":start.isoformat(),"end":end.isoformat()},
        "expected_daily_pair_slots":len(days(start,end))*len(SYMBOLS),
        "candidate_covered_day_slots":len(opportunities),
        "missing_day_slots":len(unavailable),
        "first_missing_day":unavailable[0]["date_utc"] if unavailable else None,
        "coverage_by_symbol":present_by_symbol,
        "missing_examples":unavailable[:8],
        "local_file_candidates":opportunities[:16],
        "search_roots_unavailable":found["unavailable_search_roots"],
        "all_source_days_available_from_local_cache":not unavailable,
    }


def inspect(*,pilot:Path,roots:list[Path])->dict:
    before=snapshot_v19_pilot(pilot)
    local=gather_local_names(roots)
    summary=coverage_from_names(local)
    return {
        "schema":"nexus.elliott-v20-local-raw-source-gap.v1",
        "research_only":True,"live_enabled":False,"auto_demo":False,
        "orders_placed":0,"external_network_requests":0,
        "provider_authenticity_rechecked":False,
        "existing_archives_modified":False,"market_evaluations":0,
        "continuation_accepted":False,
        "v19_integrity":before,
        "source_search_roots":[str(p) for p in roots],
        "source_coverage":summary,
        "disposition":(
            "BLOCKED_MISSING_LOCAL_RAW_TRADE_DAYS" if
            summary["missing_day_slots"] else
            "CANDIDATE_FILES_PRESENT_BUT_NOT_PROVIDER_VERIFIED"
        ),
    }


def main():
    p=argparse.ArgumentParser()
    p.add_argument("--pilot",type=Path,required=True)
    p.add_argument("--root",type=Path,action="append",required=True)
    p.add_argument("--receipt",type=Path,required=True)
    args=p.parse_args()
    result=inspect(pilot=args.pilot,roots=args.root)
    args.receipt.parent.mkdir(parents=True,exist_ok=True)
    args.receipt.write_text(json.dumps(result,sort_keys=True,indent=2)+"\n",encoding="utf-8")
    s=result["source_coverage"]
    print(json.dumps({"disposition":result["disposition"],
         "expected_day_slots":s["expected_daily_pair_slots"],
         "missing_day_slots":s["missing_day_slots"],
         "first_missing_day":s["first_missing_day"],
         "v19_6_sha256_verified":result["v19_integrity"]["v19_pilot_6_parquet_hashes_verified"]
    },sort_keys=True))


if __name__=="__main__":
    main()
