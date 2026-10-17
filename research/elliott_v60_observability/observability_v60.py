"""V60 retrospective archive-arrival audit for source-bound research results.

Checks when physical TLS-captured daily data and independently constructed
minute evidence actually became observable. Closed-bar geometry alone cannot
prove access to an unpublished source archive at an earlier decision time.
This is a read-only timing/audit layer, not a strategy or order module.
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import pandas as pd
from prospective_v52 import ProspectiveGateError
from trace_capture_v59 import CaptureChainResult

@dataclass(frozen=True)
class SourceObservability:
    state:str
    claimed_decision_close_utc:str
    last_archive_captured_utc:str
    last_minute_receipt_created_utc:str
    physical_data_available_utc:str
    availability_lag_seconds:int
    physical_source_timing_consistent:bool
    physically_available_by_decision:bool
    structural_only:bool=True
    executable_quote_proof:bool=False
    publication_time_known:bool=False

def _utc(value):
    try:t=pd.Timestamp(value)
    except Exception as exc:raise ProspectiveGateError("malformed physical evidence UTC timestamp") from exc
    if t.tzinfo is None or t.utcoffset() is None:
        raise ProspectiveGateError("timezone-unaware evidence timestamp")
    return t.tz_convert("UTC")

def _read_exact(path,expected_sha,filename):
    p=Path(path)
    if p.name!=filename or not p.is_file() or p.is_symlink():
        raise ProspectiveGateError("physical receipt missing or substituted")
    content=p.read_bytes()
    if hashlib.sha256(content).hexdigest()!=expected_sha:
        raise ProspectiveGateError("physical evidence receipt changed after V59 verification")
    try:value=json.loads(content.decode("utf8"))
    except Exception as exc:raise ProspectiveGateError("physical receipt JSON unreadable") from exc
    if not isinstance(value,dict):
        raise ProspectiveGateError("physical receipt JSON structure invalid")
    return value

def audit_source_observability(
    verified_chain:CaptureChainResult,
    tls_receipt_paths,minute_receipt_paths,
)->SourceObservability:
    """Read verified V59 receipt fingerprints, require stage-time coherence.

    No clock override and no search for a retrospectively profitable period.
    This computes lower bound on availability; official archive publication
    time is unknown and cannot be inferred from capture time alone.
    """
    if not isinstance(verified_chain,CaptureChainResult) or not verified_chain.source_tls_capture_claim_consistent:
        raise ProspectiveGateError("physical V59 chain verification required")
    count=verified_chain.complete_verified_source_days
    if (not count or len(tls_receipt_paths)!=count or
        len(minute_receipt_paths)!=count or
        len(verified_chain.physical_tls_capture_receipt_hashes)!=count or
        len(verified_chain.physical_minute_receipt_hashes)!=count):
        raise ProspectiveGateError("physical source receipt day count mismatch")
    decision=_utc(verified_chain.decision_close_utc)
    latest_capture=None
    latest_minute=None
    consistent=True
    for i in range(count):
        cap=_read_exact(tls_receipt_paths[i],
                        verified_chain.physical_tls_capture_receipt_hashes[i],
                        "SOURCE_TLS_RECEIPT.json")
        minute=_read_exact(minute_receipt_paths[i],
                           verified_chain.physical_minute_receipt_hashes[i],
                           "SOURCE_INTAKE_RECEIPT.json")
        captured=_utc(cap.get("captured_utc"))
        created=_utc(minute.get("created_utc"))
        day=_utc(cap.get("day_utc")+"T00:00:00Z")
        if captured<day+pd.Timedelta(days=1):
            raise ProspectiveGateError("archive capture precedes end of physical source day")
        if created<captured:
            consistent=False
        if latest_capture is None or captured>latest_capture:latest_capture=captured
        if latest_minute is None or created>latest_minute:latest_minute=created
    ready=max(latest_capture,latest_minute)
    lag_seconds=int((ready-decision).total_seconds())
    if not consistent:
        state="INVALID_EVIDENCE_STAGE_CHRONOLOGY"
    elif ready>decision:
        state="RETROSPECTIVE_ARCHIVE_AVAILABLE_AFTER_DECISION"
    else:
        state="PHYSICAL_SOURCE_AVAILABLE_BY_DECISION_ONLY"
    return SourceObservability(
        state,decision.isoformat(),latest_capture.isoformat(),
        latest_minute.isoformat(),ready.isoformat(),lag_seconds,consistent,
        consistent and ready<=decision)
