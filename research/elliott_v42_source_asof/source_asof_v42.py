"""V42: read-only cryptographically pinned, causal one-minute Elliott source adapter.
Never downloads, creates signals or mutates source. V41 official Spot proof is
external evidence, not established from a standalone caller-provided SHA string.
"""
from __future__ import annotations
from pathlib import Path
import hashlib
import math
import re
import pandas as pd
import numpy as np

RESEARCH_ONLY=True
LIVE_ENABLED=False
AUTO_DEMO=False
ENTRY_SIGNAL=False
SOURCE_BAR_SPAN=pd.Timedelta(minutes=1)
FIELDS=("open","high","low","close","volume","trade_count")

class SourceGateError(ValueError):
    pass

def completed_1m_prefix(parquet_path, expected_sha256, decision_close_utc, *, expected_start_utc=None):
    """Return exact index-zero UTC OPEN-labelled prefix, closed through decision.

    The SHA must come from separately authenticated/immutable provider receipt.
    A stored future tail is never returned. No missing minutes or artificial
    forward fills accepted; all trades/counts must have physical provenance.
    """
    if not isinstance(expected_sha256,str) or not re.fullmatch(r"[0-9a-f]{64}",expected_sha256):
        raise SourceGateError("valid external source SHA-256 required")
    path=Path(parquet_path)
    if not path.is_file() or not path.name.endswith(".parquet"):
        raise SourceGateError("missing trusted parquet path")
    h=hashlib.sha256()
    with path.open("rb") as inp:
        for chunk in iter(lambda:inp.read(1048576),b""):
            h.update(chunk)
    if h.hexdigest()!=expected_sha256:
        raise SourceGateError("hash mismatch or source altered")
    try:
        decision=pd.Timestamp(decision_close_utc)
    except Exception as exc:
        raise SourceGateError("invalid decision time") from exc
    if decision.tzinfo is None or decision.utcoffset() is None:
        raise SourceGateError("naive decision time")
    decision=decision.tz_convert("UTC")
    if decision.value%SOURCE_BAR_SPAN.value:
        raise SourceGateError("decision not aligned to completed UTC 1m")
    try:
        df=pd.read_parquet(path)
    except Exception as exc:
        raise SourceGateError("cannot decode pinned source") from exc
    required={"timestamp",*FIELDS}
    if not required.issubset(df.columns) or not len(df):
        raise SourceGateError("incomplete source schema or rows")
    raw=df["timestamp"].tolist()
    if any((pd.Timestamp(t).tzinfo is None or pd.Timestamp(t).utcoffset() is None) for t in raw):
        raise SourceGateError("source UTC timestamps must be explicitly timezone-aware")
    stamps=pd.DatetimeIndex(pd.to_datetime(raw,utc=True,errors="raise")).as_unit("ns")
    ns=stamps.asi8
    if stamps.hasnans or not stamps.is_monotonic_increasing or not stamps.is_unique:
        raise SourceGateError("source minute chronology")
    if np.any(ns%SOURCE_BAR_SPAN.value!=0) or np.any(np.diff(ns)!=SOURCE_BAR_SPAN.value):
        raise SourceGateError("missing, duplicated or off-grid source minutes")
    if expected_start_utc is not None:
        want=pd.Timestamp(expected_start_utc)
        if want.tzinfo is None or want.utcoffset() is None or stamps[0]!=want.tz_convert("UTC"):
            raise SourceGateError("source window start mismatch")
    arr=df[list(FIELDS)].to_numpy(dtype=float)
    if not np.isfinite(arr).all() or np.any(arr[:,0:4]<=0) or np.any(arr[:,4]<0):
        raise SourceGateError("invalid finite OHLCV")
    counts=df["trade_count"]
    if (not pd.api.types.is_integer_dtype(counts)
        or (counts<=0).any()):
        raise SourceGateError("source trade counts malformed or empty")
    op,hi,lo,cl=arr[:,:4].T
    if (hi<np.maximum.reduce([op,lo,cl])).any() or (lo>np.minimum.reduce([op,hi,cl])).any():
        raise SourceGateError("source minute OHLC inconsistent")
    # The last row whose CLOSE equals decision; no forming or later row returned.
    cutoff=decision-SOURCE_BAR_SPAN
    if cutoff<stamps[0] or cutoff>stamps[-1]:
        raise SourceGateError("decision is outside complete persisted minute source")
    target=int(np.searchsorted(ns,cutoff.value,side="right"))
    if target<1 or stamps[target-1]!=cutoff:
        raise SourceGateError("decision lacks exact complete 1m candle")
    out=df.iloc[:target].copy().reset_index(drop=True)
    out["timestamp"]=stamps[:target]
    if out["timestamp"].iat[-1]+SOURCE_BAR_SPAN!=decision:
        raise SourceGateError("future/incomplete last candle")
    return out
