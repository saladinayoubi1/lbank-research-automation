"""V53 offline prospective Elliott research scanner, no orders or P/L.

Only accepts sequential V52-independent-oracle proven complete Bybit Spot UTC
days from Oct16. Scores at complete UTC day boundaries from Oct18 onward.
"""
from __future__ import annotations
from dataclasses import dataclass
from decimal import Decimal
import hashlib
from pathlib import Path
import re
from typing import Sequence
import numpy as np
import pandas as pd

from nexus_causal_elliott_five_swing_features import _confirmed_pivot
from nested_elliott_v40 import ConfirmedPivot, _price_geometry_5
from propose_nested_v49 import _strict_minute_pivots
from propose_degree_v50 import propose_three_minute_child_degree
from prospective_v52 import (
    VerifiedDay, ProspectiveGateError, read_frozen_protocol,
    validate_scoring_event_time, SOURCE_START, SCORE_START,
    BARS_PER_DAY, VALID_SYMBOLS,
)
RESEARCH_ONLY=True
ENTRY_SIGNAL=False
LIVE_ENABLED=False
PAPER_ELIGIBLE=False
AUTO_DEMO=False
PARENT_MINUTES=15

@dataclass(frozen=True)
class ScanCandidate:
    fingerprint:str
    last_parent_confirmation_close_utc:str
    parent_source_bound:bool
    child_degree_accepted:bool
    reason:str
    entry_signal:bool=False
    paper_eligible:bool=False

@dataclass(frozen=True)
class ProspectiveScan:
    symbol:str
    decision_close_utc:str
    verified_days:int
    physical_source_trades:int
    fifteen_minute_pivots:int
    nine_parent_group_count:int
    parent_geometry_candidates:int
    source_bound_parent_candidates:int
    bounded_child_candidates:int
    candidates:tuple[ScanCandidate,...]
    status:str="RESEARCH_ONLY_NO_PNL_NO_ORDERS"
    entry_signal:bool=False
    paper_eligible:bool=False
    live_enabled:bool=False

def _file_sha(p:Path):
    h=hashlib.sha256()
    with p.open("rb") as stream:
        for chunk in iter(lambda:stream.read(1048576),b""):h.update(chunk)
    return h.hexdigest()

def scan_verified_complete_days(symbol:str,
                                sources:Sequence[tuple[VerifiedDay,Path]],
                                *,decision_close_utc)->ProspectiveScan:
    """Rehash every independently source-oracled physical day before analysis.

    Source-day receipts must be emitted by V52 raw-gzip verifier. A pure
    proposal is never an executable signal. Current incomplete days cannot be
    used; finished archives are analyzed only at daily UTC decision closes.
    """
    read_frozen_protocol()
    if symbol not in VALID_SYMBOLS:raise ProspectiveGateError("unsupported Bybit symbol")
    decision=validate_scoring_event_time(
        decision_close_utc,first_parent_confirmed_close_utc=SCORE_START)
    if decision.hour!=0 or decision.minute!=0 or decision.second!=0:
        raise ProspectiveGateError("scoring only on complete UTC day boundary")
    days=int((decision-SOURCE_START)/pd.Timedelta(days=1))
    if days<2 or len(sources)!=days:
        raise ProspectiveGateError("missing duplicated or future physical source days")
    frames=[];trade_sum=0
    for offset,(proof,path) in enumerate(sources):
        day=SOURCE_START+pd.Timedelta(days=offset)
        if (not isinstance(proof,VerifiedDay) or proof.symbol!=symbol or
            proof.day_utc!=day.date().isoformat()):
            raise ProspectiveGateError("missing verified ordered source day")
        if (not proof.complete_source or proof.exact_candles!=BARS_PER_DAY or
            proof.ohlcv_checks!=7200 or proof.count_checks!=BARS_PER_DAY or
            proof.source_trades<BARS_PER_DAY):
            raise ProspectiveGateError("incomplete independent raw-to-minute proof")
        if not isinstance(proof.official_gzip_sha256,str) or not re.fullmatch("[0-9a-f]{64}",proof.official_gzip_sha256):
            raise ProspectiveGateError("original trade archive SHA provenance missing")
        p=Path(path)
        if not p.is_file() or _file_sha(p)!=proof.minute_parquet_sha256:
            raise ProspectiveGateError("source minute parquet absent or modified")
        df=pd.read_parquet(p)
        if len(df)!=BARS_PER_DAY or not {"timestamp","open","high","low","close","volume","trade_count"}.issubset(df.columns):
            raise ProspectiveGateError("source day schema incomplete")
        stamps=df["timestamp"].tolist()
        if any(pd.Timestamp(x).tzinfo is None or pd.Timestamp(x).utcoffset() is None for x in stamps):
            raise ProspectiveGateError("minute source timestamps must be timezone-aware")
        times=pd.DatetimeIndex(pd.to_datetime(stamps,utc=True)).as_unit("ns")
        expected=pd.date_range(day,periods=BARS_PER_DAY,freq="min",tz="UTC").as_unit("ns")
        if not times.equals(expected):
            raise ProspectiveGateError("minute source wrong UTC day grid")
        frames.append(df);trade_sum+=proof.source_trades
    minutes=pd.concat(frames,ignore_index=True)
    ts=pd.DatetimeIndex(pd.to_datetime(minutes["timestamp"],utc=True)).as_unit("ns")
    if len(minutes)!=days*BARS_PER_DAY or ts[-1]+pd.Timedelta(minutes=1)!=decision:
        raise ProspectiveGateError("future forming or missing minute at decision")
    candles=minutes.set_index(ts).resample("15min",label="left",closed="left",origin="start_day").agg(
        open=("open","first"),high=("high","max"),low=("low","min"),
        close=("close","last"),volume=("volume","sum"))
    if len(candles)!=days*96:
        raise ProspectiveGateError("15m source not complete")
    hi=candles["high"].to_numpy(float);lo=candles["low"].to_numpy(float)
    accepted=[]
    for index in range(len(candles)):
        pivot=_confirmed_pivot(hi,lo,index)
        if pivot is None:continue
        if accepted and pivot.kind==accepted[-1].kind:
            prev=accepted[-1]
            if pivot.price>prev.price if pivot.kind=="high" else pivot.price<prev.price:
                accepted[-1]=pivot
        else:accepted.append(pivot)
    seenminute={(p.index,p.kind):p for p in _strict_minute_pivots(minutes)}
    groups=0;geometry=0;bound=0;child=0;events=[]
    mh=minutes["high"].to_numpy(float);ml=minutes["low"].to_numpy(float)
    for start in range(max(0,len(accepted)-8)):
        parents=accepted[start:start+9]
        if tuple(p.kind for p in parents)!=("low","high","low","high","low","high","low","high","low"):
            continue
        groups+=1
        prices=[Decimal(str(p.price)) for p in parents]
        if not (_price_geometry_5(prices[:6],1) and
                prices[6]<prices[7]<prices[5] and prices[8]<prices[6]):
            continue
        geometry+=1
        confirmed=candles.index[parents[-1].confirmed_at]+pd.Timedelta(minutes=15)
        if confirmed>decision:
            raise ProspectiveGateError("future parent pivot confirmation")
        endpoints=[];sourcebound=True
        for pivot in parents:
            first=pivot.index*PARENT_MINUTES
            field=mh if pivot.kind=="high" else ml
            match=np.flatnonzero(np.isclose(field[first:first+PARENT_MINUTES],
                              float(pivot.price),rtol=1e-12,atol=1e-8))
            if len(match)!=1:
                sourcebound=False;break
            center=first+int(match[0])
            witness=seenminute.get((center,pivot.kind))
            if witness is None or witness.price!=float(pivot.price):
                sourcebound=False;break
            endpoints.append(ConfirmedPivot(witness.kind,int(witness.index),
                                             int(witness.confirmed_at),witness.price))
        digest=hashlib.sha256((symbol+"|"+"|".join(str(x.index)+":"+str(x.price)
                                       for x in parents)).encode("utf8")).hexdigest()[:24]
        if sourcebound:
            bound+=1
            degree=propose_three_minute_child_degree(minutes,tuple(endpoints),
                                                        decision_close_utc=decision)
            ok=bool(degree.source_bound_one_degree)
            reason=degree.reason
            if ok:child+=1
        else:ok=False;reason="PARENT_1M_ORIGIN_AMBIGUOUS_OR_UNVERIFIED"
        events.append(ScanCandidate(digest,confirmed.isoformat(),sourcebound,ok,reason))
    return ProspectiveScan(symbol,decision.isoformat(),days,trade_sum,len(accepted),
                           groups,geometry,bound,child,tuple(events))
