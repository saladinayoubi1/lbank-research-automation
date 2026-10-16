"""V55 safe, offline physical daily archive intake, no download or orders.

This module does not authenticate a remote Bybit request. It requires an
existing immutable exact-name raw archive and a declared official source URL;
it independently streams source trades into complete 1m OHLCV, then calls
V52's *separately implemented* full raw-trade oracle before a PASS receipt.
Never fills missing minutes, overwrites an existing archive, or uses Live.
"""
from __future__ import annotations
from dataclasses import asdict
from datetime import datetime,timezone
from decimal import Decimal
import csv
import gzip
import hashlib
import json
from pathlib import Path
import tempfile
import pandas as pd

from prospective_v52 import (
    ProspectiveGateError, VALID_SYMBOLS, SOURCE_START,SCORE_END,
    BARS_PER_DAY, verify_official_day_source,read_frozen_protocol,
)

RESEARCH_ONLY=True
LIVE_ENABLED=False
PAPER_ELIGIBLE=False
ENTRY_SIGNAL=False
AUTO_DEMO=False

def _sha(path:Path):
    h=hashlib.sha256()
    with path.open("rb") as f:
        for b in iter(lambda:f.read(1048576),b""):h.update(b)
    return h.hexdigest()

def build_verified_1m_day(symbol,day_utc,raw_archive,output_directory,
                          *,declared_source_url,fixture_mode=False,
                          observed_utc=None):
    """Build immutable physical 1m source after completed UTC day and re-oracle.

    observed_utc is allowed ONLY in marked synthetic fixture mode in the OS
    temporary directory. Real market validation always checks actual UTC.
    """
    read_frozen_protocol()
    if symbol not in VALID_SYMBOLS:raise ProspectiveGateError("unsupported Bybit symbol")
    try:day=pd.Timestamp(day_utc)
    except Exception as exc:raise ProspectiveGateError("invalid UTC source day") from exc
    if day.tzinfo is None or day.utcoffset() is None:raise ProspectiveGateError("naive source day")
    day=day.tz_convert("UTC")
    if (day.hour,day.minute,day.second,day.microsecond)!=(0,0,0,0) or not SOURCE_START<=day<SCORE_END:
        raise ProspectiveGateError("unsupported historical or non-midnight UTC source day")
    now=pd.Timestamp(datetime.now(timezone.utc)) if observed_utc is None else pd.Timestamp(observed_utc)
    if observed_utc is not None and not fixture_mode:
        raise ProspectiveGateError("clock overrides forbidden for real market ingestion")
    if now.tzinfo is None or now.utcoffset() is None:
        raise ProspectiveGateError("naive audit clock")
    if now.tz_convert("UTC")<day+pd.Timedelta(days=1):
        raise ProspectiveGateError("full official UTC source day not yet complete")
    name=f"{symbol}_{day.date()}.csv.gz"
    expected_url=f"https://public.bybit.com/spot/{symbol}/{name}"
    if declared_source_url!=expected_url:
        raise ProspectiveGateError("official Spot source URL declaration mismatch")
    archive=Path(raw_archive)
    output=Path(output_directory)
    if archive.name!=name or not archive.is_file() or not archive.stat().st_size:
        raise ProspectiveGateError("raw archive missing or wrong exact date/symbol")
    if output.exists():raise ProspectiveGateError("refuse existing output directory/overwrite")
    if fixture_mode:
        if not output.resolve().is_relative_to(Path(tempfile.gettempdir()).resolve()):
            raise ProspectiveGateError("synthetic fixture must remain in OS temp")
    rawsha=_sha(archive)
    start=int(day.timestamp()*1000)
    prev=-1;trades=0;minutes={}
    try:
        with gzip.open(archive,"rt",encoding="utf-8-sig",newline="") as inp:
            reader=csv.reader(inp)
            if next(reader)!=["id","timestamp","price","volume","side","rpi"]:
                raise ProspectiveGateError("Bybit Spot raw trade schema changed")
            for cells in reader:
                if len(cells)!=6:raise ProspectiveGateError("invalid trade CSV width")
                timestamp=int(cells[1]);price=Decimal(cells[2]);size=Decimal(cells[3])
                if (timestamp<prev or not start<=timestamp<start+86400000 or
                    not price.is_finite() or not size.is_finite() or price<=0 or size<0):
                    raise ProspectiveGateError("invalid timestamp, chronology, price or size")
                prev=timestamp;trades+=1
                i=(timestamp-start)//60000
                bucket=minutes.get(i)
                if bucket is None:
                    minutes[i]=[price,price,price,price,size,1]
                else:
                    bucket[1]=max(bucket[1],price);bucket[2]=min(bucket[2],price)
                    bucket[3]=price;bucket[4]+=size;bucket[5]+=1
    except (OSError,EOFError,UnicodeError,ValueError) as exc:
        if isinstance(exc,ProspectiveGateError):raise
        raise ProspectiveGateError("unreadable physical daily raw trade archive") from exc
    if set(minutes)!=set(range(BARS_PER_DAY)):
        raise ProspectiveGateError("missing trade-bearing minute; no synthetic fills")
    fields=[]
    for i in range(BARS_PER_DAY):
        val=minutes[i]
        fields.append({
            "timestamp":day+pd.Timedelta(minutes=i),
            "open":float(val[0]),"high":float(val[1]),"low":float(val[2]),
            "close":float(val[3]),"volume":float(val[4]),"trade_count":int(val[5]),
        })
    frame=pd.DataFrame(fields)
    output.mkdir(parents=True,exist_ok=False)
    parquet=output/f"{symbol}_{day.date()}_1m_from_official_raw.parquet"
    frame.to_parquet(parquet,index=False)
    minute_sha=_sha(parquet)
    independent=verify_official_day_source(
        symbol,day,archive,rawsha,parquet,minute_sha,
        observed_utc=now if fixture_mode else None,
    )
    if independent.source_trades!=trades:
        raise ProspectiveGateError("producer vs independent trade count differs")
    receipt={
        "schema":"nexus.elliott-v55-source-intake-v1",
        "created_utc":datetime.now(timezone.utc).isoformat(),
        "declared_source_url":declared_source_url,
        "source_url_is_proven_by_download":False,
        "fixture_mode":bool(fixture_mode),
        "raw_path":str(archive),"raw_sha256":rawsha,
        "parquet_path":str(parquet),"parquet_sha256":minute_sha,
        "independent_v52_result":asdict(independent),
        "research_only":True,"entry_signal":False,
        "paper_eligible":False,"live_enabled":False,"pnl":None,
        "status":"SYNTHETIC_TEST_ONLY" if fixture_mode else "PASS_OFFLINE_INDEPENDENT_1M_SOURCE_ONLY",
    }
    dest=output/"SOURCE_INTAKE_RECEIPT.json"
    dest.write_text(json.dumps(receipt,indent=2,ensure_ascii=False)+"\n",encoding="utf8")
    return receipt
