"""V59 research-only physical TLS capture -> verified minute -> bounded Elliott trace.

A *local* JSON capture receipt is forgeable; this module validates recorded
TLS-session metadata and physical source identity but NEVER upgrades the
offline proof to exchange-signed remote origin authentication. No API keys,
orders, trading execution, automatic scheduler or P/L.
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import re
import tempfile
from typing import Sequence
import pandas as pd
from prospective_v52 import (
    ProspectiveGateError, SOURCE_START,SCORE_START,read_frozen_protocol,
    validate_scoring_event_time,
)
from fully_attested_v57 import scan_only_fully_oracled_receipts,AttestedDayScan

RESEARCH_ONLY=True
ENTRY_SIGNAL=False
PAPER_ELIGIBLE=False
LIVE_ENABLED=False
AUTO_DEMO=False
SOURCE_ORIGIN_NOT_EXCHANGE_SIGNED=True
_SHA=re.compile(r"^[a-f0-9]{64}$")

@dataclass(frozen=True)
class CaptureChainResult:
    symbol:str
    decision_close_utc:str
    complete_verified_source_days:int
    physical_tls_capture_receipt_hashes:tuple[str,...]
    physical_minute_receipt_hashes:tuple[str,...]
    physical_raw_archive_hashes:tuple[str,...]
    scanner:AttestedDayScan
    source_tls_capture_claim_consistent:bool
    external_exchange_signature_verified:bool=False
    independently_authenticated_offline_origin:bool=False
    trade_entry_enabled:bool=False
    paper_eligible:bool=False
    live_enabled:bool=False
    new_pnl:None=None

def _digest(path):
    h=hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda:stream.read(1048576),b""):h.update(chunk)
    return h.hexdigest()

def _timestamp(value):
    try:t=pd.Timestamp(value)
    except Exception as exc:raise ProspectiveGateError("malformed recorded time") from exc
    if t.tzinfo is None or t.utcoffset() is None:
        raise ProspectiveGateError("naive recorded source time")
    return t.tz_convert("UTC")

def _json_file(path,expected_name):
    p=Path(path)
    if p.name!=expected_name or not p.is_file() or p.is_symlink() or p.parent.is_symlink():
        raise ProspectiveGateError("physical signed-out evidence receipt missing or indirect")
    b=p.read_bytes()
    try:data=json.loads(b.decode("utf8"))
    except Exception as exc:raise ProspectiveGateError("corrupt physical evidence receipt") from exc
    if not isinstance(data,dict):raise ProspectiveGateError("unexpected evidence receipt shape")
    return p,data,hashlib.sha256(b).hexdigest()

def _safe_actual_file(path,name,folder):
    p=Path(path)
    if p.name!=name or not p.is_file() or p.is_symlink():
        raise ProspectiveGateError("recorded source archive file missing or indirect")
    if p.parent.resolve()!=folder.resolve():
        raise ProspectiveGateError("recorded archive not inside physical capture directory")
    return p

def scan_tls_bound_physical_source(
    symbol:str,
    tls_receipt_paths:Sequence[Path],
    minute_receipt_paths:Sequence[Path],
    *,
    decision_close_utc,
    fixture_mode:bool=False,
    observed_utc=None,
)->CaptureChainResult:
    """Explicitly cross-match physically captured TLS bytes, V55/V52 and V57.

    Production clock injection forbidden; synthetic fixture data may use OS
    temp only. Real capture origin is claimed by a local V58 TLS receipt,
    not independently cryptographically signed by Bybit.
    """
    read_frozen_protocol()
    if observed_utc is not None and not fixture_mode:
        raise ProspectiveGateError("real capture chain clock injection forbidden")
    decision=validate_scoring_event_time(
        decision_close_utc,first_parent_confirmed_close_utc=SCORE_START)
    if (decision.hour,decision.minute,decision.second,decision.microsecond)!=(0,0,0,0):
        raise ProspectiveGateError("scored day decision requires UTC midnight")
    now=_timestamp(observed_utc) if observed_utc is not None else pd.Timestamp(datetime.now(timezone.utc))
    if decision>now:
        raise ProspectiveGateError("cannot attest unobserved future UTC day")
    days=int((decision-SOURCE_START)/pd.Timedelta(days=1))
    if days<2 or len(tls_receipt_paths)!=days or len(minute_receipt_paths)!=days:
        raise ProspectiveGateError("missing, extra or out-of-order physical source days")
    capture_hashes=[];minute_hashes=[];raw_hashes=[]
    for k in range(days):
        date=SOURCE_START+pd.Timedelta(days=k)
        filename=f"{symbol}_{date.date()}.csv.gz"
        origin=f"https://public.bybit.com/spot/{symbol}/{filename}"
        tls,cap,tc_hash=_json_file(tls_receipt_paths[k],"SOURCE_TLS_RECEIPT.json")
        src,mid,mi_hash=_json_file(minute_receipt_paths[k],"SOURCE_INTAKE_RECEIPT.json")
        if fixture_mode and (not tls.resolve().is_relative_to(Path(tempfile.gettempdir()).resolve())
                             or not src.resolve().is_relative_to(Path(tempfile.gettempdir()).resolve())):
            raise ProspectiveGateError("synthetic receipts must remain in OS temp")
        if cap.get("schema")!="nexus.elliott-v58-direct-tls-spot-capture.v1":
            raise ProspectiveGateError("capture not emitted by expected V58 schema")
        if mid.get("schema")!="nexus.elliott-v56-transactional-source-intake.v1":
            raise ProspectiveGateError("minute evidence not emitted by expected V56 schema")
        if (cap.get("symbol")!=symbol or cap.get("day_utc")!=date.date().isoformat() or
            cap.get("actual_request_scheme")!="https" or
            cap.get("actual_request_host")!="public.bybit.com" or
            cap.get("actual_request_path")!=f"/spot/{symbol}/{filename}" or
            cap.get("actual_request_url")!=origin or mid.get("declared_source_url")!=origin):
            raise ProspectiveGateError("actual source URL, date or market mismatch")
        if (cap.get("fixture_mode") is not fixture_mode or
            mid.get("fixture_mode") is not fixture_mode or
            cap.get("remote_origin_tls_verified") is not (not fixture_mode) or
            mid.get("source_url_is_proven_by_download") is not False):
            raise ProspectiveGateError("synthetic/production origin flags inconsistent")
        if cap.get("status")!=("SYNTHETIC_TRANSPORT_TEST_ONLY" if fixture_mode else
                              "PASS_TLS_VERIFIED_SOURCE_CAPTURE_ONLY"):
            raise ProspectiveGateError("TLS capture not in accepted state")
        if mid.get("status")!=("SYNTHETIC_TEST_ONLY" if fixture_mode else
                              "PASS_OFFLINE_INDEPENDENT_1M_SOURCE_ONLY"):
            raise ProspectiveGateError("independent minute source not in accepted state")
        if (cap.get("http_status")!=200 or cap.get("redirects_followed") is not False or
            cap.get("tls_system_trust_hostname_verification") is not True or
            cap.get("tls_version") not in ("TLSv1.2","TLSv1.3") or
            cap.get("gzip_crc_verified") is not True):
            raise ProspectiveGateError("unverified or redirected TLS capture claim")
        for record in (cap,mid):
            if any(record.get(flag) is not False for flag in ("entry_signal","paper_eligible","live_enabled")):
                raise ProspectiveGateError("inconsistent research-only mode flags")
        captured=_timestamp(cap.get("captured_utc"))
        if captured<date+pd.Timedelta(days=1) or captured>now:
            raise ProspectiveGateError("archive recorded capture time is impossible")
        raw=_safe_actual_file(cap.get("archive_path",""),filename,tls.parent)
        if raw.resolve()!=Path(mid.get("raw_path","")).resolve():
            raise ProspectiveGateError("minute oracle did not consume captured raw archive")
        sha=cap.get("sha256")
        if not isinstance(sha,str) or _SHA.fullmatch(sha) is None or sha!=mid.get("raw_sha256"):
            raise ProspectiveGateError("capture and minute receipt archive SHA mismatch")
        if _digest(raw)!=sha:
            raise ProspectiveGateError("original captured archive bytes changed since capture")
        if type(cap.get("compressed_bytes")) is not int or raw.stat().st_size!=cap["compressed_bytes"]:
            raise ProspectiveGateError("raw byte length differs from recorded transfer size")
        physical_parq=Path(mid.get("parquet_path",""))
        if physical_parq.parent.resolve()!=src.parent.resolve() or not physical_parq.is_file() or physical_parq.is_symlink():
            raise ProspectiveGateError("final minute parquet not inside its evidence folder")
        if not isinstance(mid.get("parquet_sha256"),str) or _SHA.fullmatch(mid["parquet_sha256"]) is None:
            raise ProspectiveGateError("minute parquet hash malformed")
        if _digest(physical_parq)!=mid["parquet_sha256"]:
            raise ProspectiveGateError("minute source was changed after verification")
        capture_hashes.append(tc_hash);minute_hashes.append(mi_hash);raw_hashes.append(sha)
    # Reopen and fully independently re-oracle raw data for every day via V57.
    verified=scan_only_fully_oracled_receipts(
        symbol,minute_receipt_paths,decision_close_utc=decision,
        fixture_mode=fixture_mode,observed_utc=observed_utc)
    if verified.physical_independently_verified_days!=days:
        raise ProspectiveGateError("unexpected source day count from re-oracle")
    return CaptureChainResult(symbol,decision.isoformat(),days,tuple(capture_hashes),
         tuple(minute_hashes),tuple(raw_hashes),verified,True)
