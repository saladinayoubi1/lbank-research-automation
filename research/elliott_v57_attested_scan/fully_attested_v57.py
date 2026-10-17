"""V57 verified-input adapter: re-oracle raw archives before V53 scoring.

V53's VerifiedDay is a plain, forgeable dataclass. V57 never trusts a
caller-supplied VerifiedDay object; it re-opens each V55 raw archive and
physical minute parquet with the entirely separate V52 trade-stream oracle.
No API calls, no orders, no automatic scheduler, no P/L.
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import tempfile
from typing import Sequence
import pandas as pd

from prospective_v52 import (
    ProspectiveGateError, SOURCE_START,SCORE_START,SCORE_END,read_frozen_protocol,
    verify_official_day_source,validate_scoring_event_time,
)
from scan_verified_v53 import scan_verified_complete_days,ProspectiveScan

RESEARCH_ONLY=True
PAPER_ELIGIBLE=False
LIVE_ENABLED=False
ENTRY_SIGNAL=False
AUTO_DEMO=False

@dataclass(frozen=True)
class AttestedDayScan:
    symbol:str
    decision_close_utc:str
    physical_independently_verified_days:int
    receipts_sha256:tuple[str,...]
    scan:ProspectiveScan
    fixture_mode:bool
    source_remote_origin_authenticated:bool=False
    research_only:bool=True
    paper_eligible:bool=False
    live_enabled:bool=False
    entry_signal:bool=False

def _iso_utc(value):
    try:t=pd.Timestamp(value)
    except Exception as exc:raise ProspectiveGateError("invalid scan date") from exc
    if t.tzinfo is None or t.utcoffset() is None:
        raise ProspectiveGateError("UTC-aware scan time required")
    return t.tz_convert("UTC")

def scan_only_fully_oracled_receipts(
    symbol:str,
    receipt_paths:Sequence[Path],
    *,
    decision_close_utc,
    fixture_mode:bool=False,
    observed_utc=None,
)->AttestedDayScan:
    """Only post-day reverified physical V55 outputs are eligible for V53.

    Clock injection is *only* for explicit synthetic tests under OS-temp.
    Original raw archive origin URL is declared, NOT authenticated by TLS by
    these offline modules; the result never claims authenticated remote origin.
    """
    read_frozen_protocol()
    decision=validate_scoring_event_time(
        decision_close_utc,first_parent_confirmed_close_utc=SCORE_START)
    if (decision.hour,decision.minute,decision.second)!=(0,0,0):
        raise ProspectiveGateError("scoring requires full UTC day close")
    if observed_utc is not None and not fixture_mode:
        raise ProspectiveGateError("real-market clock injection forbidden")
    now=_iso_utc(observed_utc) if observed_utc is not None else pd.Timestamp(datetime.now(timezone.utc))
    if now<decision:
        raise ProspectiveGateError("future daily decision not yet actually observable")
    num_days=int((decision-SOURCE_START)/pd.Timedelta(days=1))
    if num_days<2 or len(receipt_paths)!=num_days:
        raise ProspectiveGateError("complete chronological source-day receipts required")
    checked=[];hashes=[]
    for index,rpath in enumerate(receipt_paths):
        path=Path(rpath)
        if path.name!="SOURCE_INTAKE_RECEIPT.json" or not path.is_file() or path.is_symlink():
            raise ProspectiveGateError("invalid or absent physical V55 receipt")
        if fixture_mode and not path.resolve().is_relative_to(Path(tempfile.gettempdir()).resolve()):
            raise ProspectiveGateError("synthetic evidence must remain in OS temp")
        bytedata=path.read_bytes()
        hashes.append(hashlib.sha256(bytedata).hexdigest())
        try:receipt=json.loads(bytedata.decode("utf8"))
        except Exception as exc:raise ProspectiveGateError("malformed physical evidence receipt") from exc
        if not isinstance(receipt,dict):
            raise ProspectiveGateError("malformed receipt shape")
        if receipt.get("schema")!="nexus.elliott-v56-transactional-source-intake.v1":
            raise ProspectiveGateError("unrecognized non-transactional source receipt")
        expected_day=SOURCE_START+pd.Timedelta(days=index)
        expected_symbol=symbol
        daily_name=f"{expected_symbol}_{expected_day.date()}.csv.gz"
        expected_url=f"https://public.bybit.com/spot/{expected_symbol}/{daily_name}"
        if (receipt.get("declared_source_url")!=expected_url or
            receipt.get("fixture_mode") is not fixture_mode or
            receipt.get("source_url_is_proven_by_download") is not False):
            raise ProspectiveGateError("inconsistent source URL or fixture/provenance status")
        expected_status=("SYNTHETIC_TEST_ONLY" if fixture_mode
                         else "PASS_OFFLINE_INDEPENDENT_1M_SOURCE_ONLY")
        if receipt.get("status")!=expected_status or not all(
            receipt.get(x) is False for x in ("entry_signal","paper_eligible","live_enabled")
        ):
            raise ProspectiveGateError("untrusted source status or trade authority")
        raw=Path(receipt.get("raw_path",""))
        parq=Path(receipt.get("parquet_path",""))
        if raw.name!=daily_name or parq.parent.resolve()!=path.parent.resolve():
            raise ProspectiveGateError("source path or published output dir mismatch")
        if not parq.is_file() or parq.is_symlink() or raw.is_symlink():
            raise ProspectiveGateError("source files absent or indirect")
        claimed=receipt.get("independent_v52_result")
        if not isinstance(claimed,dict):
            raise ProspectiveGateError("missing independently verified raw source receipt")
        expected_raw_sha=receipt.get("raw_sha256")
        expected_minute_sha=receipt.get("parquet_sha256")
        # Independent full physical source-day oracle and current hash check.
        fresh=verify_official_day_source(
            symbol,expected_day,raw,expected_raw_sha,
            parq,expected_minute_sha,
            observed_utc=now if fixture_mode else None,
        )
        if claimed!={
            "symbol":fresh.symbol,
            "day_utc":fresh.day_utc,
            "source_trades":fresh.source_trades,
            "exact_candles":fresh.exact_candles,
            "ohlcv_checks":fresh.ohlcv_checks,
            "count_checks":fresh.count_checks,
            "official_gzip_sha256":fresh.official_gzip_sha256,
            "minute_parquet_sha256":fresh.minute_parquet_sha256,
            "complete_source":fresh.complete_source,
            "research_only":fresh.research_only,
            "entry_signal":fresh.entry_signal,
            "paper_eligible":fresh.paper_eligible,
        }:
            raise ProspectiveGateError("recorded day oracle claim differs from fresh independent audit")
        checked.append((fresh,parq))
    scored=scan_verified_complete_days(
        symbol,checked,decision_close_utc=decision)
    return AttestedDayScan(symbol,decision.isoformat(),len(checked),
                           tuple(hashes),scored,fixture_mode)
