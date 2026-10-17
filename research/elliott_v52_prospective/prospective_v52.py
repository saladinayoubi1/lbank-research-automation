"""V52 preregistered *offline* Bybit Spot source/score admission gate.

Proof of a day requires independent reread of exact SHA-pinned raw gzip and
exact SHA-pinned 1440-minute parquet. No download, API, scheduling, orders,
or P/L. The capture start predates registration; Oct16-17 are WARMUP ONLY.
"""
from __future__ import annotations
import csv
from dataclasses import dataclass
from datetime import datetime,timezone,timedelta
from decimal import Decimal,InvalidOperation
import gzip
import hashlib
import json
import math
from pathlib import Path
import re
import numpy as np
import pandas as pd

PROTOCOL_PATH=Path(__file__).with_name("protocol_v52.json")
PROTOCOL_SHA256="f853b8a5b896227998c30b0f5ea05a61364f1000fae610c767e81ad841c303e4"
SOURCE_START=pd.Timestamp("2026-10-16T00:00:00Z")
SCORE_START=pd.Timestamp("2026-10-18T00:00:00Z")
SCORE_END=pd.Timestamp("2026-11-16T00:00:00Z")
VALID_SYMBOLS=frozenset(("BTCUSDT","ETHUSDT"))
BARS_PER_DAY=1440
STEP_MS=60000
EXPECTED_COLUMNS=("timestamp","open","high","low","close","volume","trade_count")
RESEARCH_ONLY=True
LIVE_ENABLED=False
PAPER_ELIGIBLE=False
ENTRY_SIGNAL=False
AUTOMATED_DEMO=False

class ProspectiveGateError(ValueError):pass

@dataclass(frozen=True)
class VerifiedDay:
    symbol:str
    day_utc:str
    source_trades:int
    exact_candles:int
    ohlcv_checks:int
    count_checks:int
    official_gzip_sha256:str
    minute_parquet_sha256:str
    complete_source:bool=True
    research_only:bool=True
    entry_signal:bool=False
    paper_eligible:bool=False

def _utc(value):
    try:dt=pd.Timestamp(value)
    except Exception as exc:raise ProspectiveGateError("invalid UTC time") from exc
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ProspectiveGateError("timezone-aware UTC required")
    return dt.tz_convert("UTC")

def read_frozen_protocol():
    if hashlib.sha256(PROTOCOL_PATH.read_bytes().replace(b"\r\n",b"\n")).hexdigest()!=PROTOCOL_SHA256:
        raise ProspectiveGateError("preregistered protocol SHA256 changed")
    spec=json.loads(PROTOCOL_PATH.read_text(encoding="utf8"))
    if (spec.get("schema")!="nexus.elliott.v52.predeclared-prospective-qa.v1" or
        spec["capture_window_utc"]["start_inclusive"]!="2026-10-16T00:00:00Z" or
        spec["scored_qa_window_utc"]["start_inclusive"]!="2026-10-18T00:00:00Z" or
        spec["scored_qa_window_utc"]["end_exclusive"]!="2026-11-16T00:00:00Z" or
        spec["wave_protocol"]["frozen_child_segments"]!=[5,3,5,3,5,5,3,5] or
        spec["wave_protocol"]["child_timeframe_minutes"]!=3 or
        spec["output_contract"]["entry_signal"] is not False or
        spec["output_contract"]["live_enabled"] is not False or
        spec["output_contract"]["paper_eligible"] is not False):
        raise ProspectiveGateError("preregistered protocol changed or invalid")
    return spec

def validate_scoring_event_time(event_close_utc,*,first_parent_confirmed_close_utc):
    read_frozen_protocol()
    event=_utc(event_close_utc)
    confirmed=_utc(first_parent_confirmed_close_utc)
    if not SCORE_START<=event<SCORE_END:
        raise ProspectiveGateError("outside delayed-start scored prospective subwindow")
    if event.value%(60*1_000_000_000):
        raise ProspectiveGateError("decision off UTC 1m grid")
    if confirmed>event:
        raise ProspectiveGateError("future parent confirmation")
    return event

def _sha_file(p:Path):
    h=hashlib.sha256()
    with p.open("rb") as f:
        for data in iter(lambda:f.read(1048576),b""):
            h.update(data)
    return h.hexdigest()

def verify_official_day_source(symbol,day_utc,archive_path,archive_sha256,
                               minute_path,minute_sha256,*,observed_utc=None):
    """Decoupled raw trade oracle; reject incomplete days, historical or faked bars.

    observed_utc override is ONLY for deterministic offline tests; real call
    must omit it and use the actual machine UTC clock.
    """
    read_frozen_protocol()
    if symbol not in VALID_SYMBOLS:raise ProspectiveGateError("unsupported symbol")
    try:day=pd.Timestamp(day_utc)
    except Exception as exc:raise ProspectiveGateError("invalid day") from exc
    if day.tzinfo is None:raise ProspectiveGateError("day must specify UTC zone")
    day=day.tz_convert("UTC")
    if day.time()!=pd.Timestamp("00:00:00").time():
        raise ProspectiveGateError("day must begin midnight UTC")
    if not SOURCE_START<=day<SCORE_END:
        raise ProspectiveGateError("historical/outside-window archive rejected")
    now=_utc(observed_utc) if observed_utc is not None else pd.Timestamp(datetime.now(timezone.utc))
    if now<day+pd.Timedelta(days=1):
        raise ProspectiveGateError("daily archive not yet past full UTC day")
    if any(not isinstance(v,str) or not re.fullmatch(r"[a-f0-9]{64}",v)
           for v in (archive_sha256,minute_sha256)):
        raise ProspectiveGateError("external SHA256 evidence required")
    raw=Path(archive_path);parquet=Path(minute_path)
    if raw.name!=f"{symbol}_{day.date()}.csv.gz" or not raw.is_file():
        raise ProspectiveGateError("official exact day archive filename/path missing")
    if not parquet.name.endswith(".parquet") or not parquet.is_file():
        raise ProspectiveGateError("physical minute parquet missing")
    if _sha_file(raw)!=archive_sha256 or _sha_file(parquet)!=minute_sha256:
        raise ProspectiveGateError("source SHA mismatch")
    begin=int(day.timestamp()*1000)
    bars={}
    trades=0;last=-1
    try:
        with gzip.open(raw,"rt",encoding="utf-8-sig",newline="") as inp:
            reader=csv.reader(inp)
            if next(reader)!=["id","timestamp","price","volume","side","rpi"]:
                raise ProspectiveGateError("unexpected Bybit Spot trade schema")
            for rec in reader:
                if len(rec)!=6:raise ProspectiveGateError("malformed trade row")
                ts=int(rec[1]);price=Decimal(rec[2]);volume=Decimal(rec[3])
                if (not begin<=ts<begin+86400000 or ts<last or
                    not price.is_finite() or not volume.is_finite() or
                    price<=0 or volume<0):
                    raise ProspectiveGateError("trade timestamp/order/price/volume invalid")
                last=ts;trades+=1
                minute=(ts-begin)//STEP_MS
                prior=bars.get(minute)
                if prior is None:
                    bars[minute]=[price,price,price,price,volume,1]
                else:
                    prior[1]=max(prior[1],price)
                    prior[2]=min(prior[2],price)
                    prior[3]=price
                    prior[4]+=volume
                    prior[5]+=1
    except (OSError,ValueError,InvalidOperation,UnicodeError) as exc:
        if isinstance(exc,ProspectiveGateError):raise
        raise ProspectiveGateError("unreadable or corrupt raw gzip trades") from exc
    if set(bars)!=set(range(BARS_PER_DAY)):
        raise ProspectiveGateError("incomplete source minutes: no synthetic fill")
    try:df=pd.read_parquet(parquet)
    except Exception as exc:raise ProspectiveGateError("bad minute parquet") from exc
    if not set(EXPECTED_COLUMNS).issubset(df.columns) or len(df)!=BARS_PER_DAY:
        raise ProspectiveGateError("minute schema/count mismatch")
    if any(_utc(x)!=day+pd.Timedelta(minutes=i) for i,x in enumerate(df["timestamp"])):
        raise ProspectiveGateError("minute timestamps not exact contiguous UTC grid")
    if not pd.api.types.is_integer_dtype(df["trade_count"]):
        raise ProspectiveGateError("physical minute trade count not integer")
    checks=0
    for idx,reference in bars.items():
        for col,want in zip(("open","high","low","close","volume"),reference[:5]):
            val=float(df[col].iat[idx]);checks+=1
            if not math.isfinite(val) or not math.isclose(val,float(want),rel_tol=1e-11,abs_tol=1e-8):
                raise ProspectiveGateError(f"minute OHLCV independent mismatch at {idx}/{col}")
        if int(df["trade_count"].iat[idx])!=reference[5]:
            raise ProspectiveGateError(f"minute trade count mismatch at {idx}")
    return VerifiedDay(symbol,day.date().isoformat(),trades,BARS_PER_DAY,checks,
                       BARS_PER_DAY,archive_sha256,minute_sha256)
