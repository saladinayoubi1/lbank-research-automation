"""Closed synthetic validation pipeline; this module cannot place exchange orders.

The low-level numerical learner is wrapped here by fixed-calendar, immutable
snapshot/label identity checks. Synthetic hashes establish integrity, never actual
historical availability. Real input admission is deliberately disabled in v1.
"""
from __future__ import annotations
from copy import deepcopy
from dataclasses import dataclass
from decimal import Decimal, localcontext
import hashlib
import json
from types import MappingProxyType
from typing import Mapping, Sequence
import numpy as np
from research.nexus_ctrend_causal_features_v1 import (
    FeatureSnapshot, latest_closed_period, snapshot_digest, DAY_MS,
)
from research.nexus_ctrend_causal_model_v1 import fit_predict, Forecast
from research.nexus_ctrend_causal_wallet_v1 import PaperWallet, LotSpec

PROTOCOL_ID="ctrend_causal_h_technical_v1"
COSTS={"conservative":("0.001","0.0005"),
       "stress":("0.0015","0.001"),"severe":("0.0025","0.0015")}

class AdmissionError(ValueError):
    pass

def _time(value):
    if type(value) is not int or not 0<=value<=np.iinfo(np.int64).max:
        raise AdmissionError("Require integer UTC epoch milliseconds")
    return value

def _hash(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(",",":"),
                                    allow_nan=False).encode()).hexdigest()

def _array(value,shape,kind,name):
    a=np.asarray(value)
    if a.shape!=shape or a.dtype.kind not in kind:
        raise AdmissionError("Malformed "+name)
    return a

def _snapshot(s):
    if not isinstance(s,FeatureSnapshot):
        raise AdmissionError("FeatureSnapshot required")
    for value in (s.decision_time_ms,s.period_start_ms,s.period_end_ms,s.period_code):
        _time(value)
    if s.evidence_class!="synthetic" or not s.source_id.startswith("synthetic:"):
        raise AdmissionError("Real data admission is disabled in this technical version")
    if latest_closed_period(s.decision_time_ms)!=(s.period_code,s.period_start_ms,s.period_end_ms):
        raise AdmissionError("Snapshot does not describe the latest fully closed calendar week")
    n=len(s.asset_ids)
    if not n or len(set(s.asset_ids))!=n or any(not isinstance(x,str) or not x for x in s.asset_ids):
        raise AdmissionError("Invalid asset identity")
    values=_array(s.values,(n,28),"fiu","features")
    caps=_array(s.caps,(n,),"fiu","caps")
    eligible=_array(s.eligible,(n,),"b","eligibility")
    vt=_array(s.value_times_ms,(n,28),"iu","feature origins")
    ct=_array(s.cap_times_ms,(n,),"iu","cap origins")
    if np.isinf(values).any() or np.isinf(caps).any():
        raise AdmissionError("Infinite snapshot data")
    for array,origin in ((values,vt),(caps,ct)):
        finite=np.isfinite(array)
        if np.any(origin[finite]<=s.period_start_ms) or np.any(origin[finite]>s.period_end_ms):
            raise AdmissionError("Feature/cap origin is outside its own calendar week")
    if np.any(eligible & (~np.isfinite(values).all(axis=1)|~np.isfinite(caps)|(caps<1e6))):
        raise AdmissionError("Ineligible current data marked eligible")
    if snapshot_digest(s)!=s.snapshot_sha256:
        raise AdmissionError("Snapshot integrity check failed")

@dataclass(frozen=True)
class HistoricalReturns:
    asset_ids: tuple[str,...]
    feature_snapshot_sha256: str
    period_start_ms: int
    period_end_ms: int
    available_at_ms: np.ndarray
    values: np.ndarray
    source_id: str
    evidence_class: str="synthetic"

    def __post_init__(self):
        start,end=_time(self.period_start_ms),_time(self.period_end_ms)
        if end<=start:
            raise AdmissionError("Return interval must be positive")
        ids=tuple(self.asset_ids)
        a=_array(self.available_at_ms,(len(ids),),"iu","label availability")
        v=_array(self.values,(len(ids),),"fiu","historical returns")
        if (np.any(a<end) or np.any(a>np.iinfo(np.int64).max) or np.isinf(v).any()
                or np.any(v[np.isfinite(v)] < -1)):
            raise AdmissionError("Invalid historical decimal returns or availability")
        if self.evidence_class!="synthetic" or not self.source_id.startswith("synthetic:"):
            raise AdmissionError("Real return inputs are not admitted")
        object.__setattr__(self,"asset_ids",ids)
        for name,x,dtype in (("available_at_ms",a,np.int64),("values",v,float)):
            out=np.array(x,dtype=dtype,copy=True);out.setflags(write=False)
            object.__setattr__(self,name,out)

@dataclass(frozen=True)
class PaperDecision:
    decision_time_ms: int
    asset_ids: tuple[str,...]
    target_weights: Mapping[str,Decimal]
    forecast: Forecast
    evidence: dict
    decision_sha256: str

    def record(self):
        return {"protocol_id":PROTOCOL_ID,"decision_time_ms":self.decision_time_ms,
            "asset_ids":list(self.asset_ids),
            "target_weights":{k:str(v) for k,v in self.target_weights.items()},
            "selected_features":list(self.forecast.selected_features),
            "scores":[float(v) if np.isfinite(v) else None for v in self.forecast.scores],
            "evidence":deepcopy(self.evidence),"scope":"synthetic_technical_only",
            "demo_admitted":False,"financial_backtest_allowed":False,
            "live_enabled":False,"orders":0}

def learn_decision(history:Sequence[FeatureSnapshot],labels:Sequence[HistoricalReturns],
                   current:FeatureSnapshot)->PaperDecision:
    """Learn once from 52 consecutive known prior weeks; no future label input."""
    _snapshot(current)
    if len(history)!=52 or len(labels)!=52:
        raise AdmissionError("Require exactly 52 historical snapshot/label pairs")
    expected_start=None
    visible_returns=[]
    label_hashes=[]
    for s,y in zip(history,labels):
        _snapshot(s)
        if (not isinstance(y,HistoricalReturns) or s.asset_ids!=current.asset_ids
                or y.asset_ids!=current.asset_ids or s.source_id!=current.source_id):
            raise AdmissionError("Asset/source identity differs across snapshots or labels")
        if s.decision_time_ms!=s.period_end_ms:
            raise AdmissionError("Historical training snapshots must be frozen at the weekly boundary")
        if expected_start is not None and s.period_end_ms!=expected_start:
            raise AdmissionError("Historical feature/label weeks are not consecutive")
        if (y.feature_snapshot_sha256!=s.snapshot_sha256 or y.period_start_ms!=s.period_end_ms
                or y.period_end_ms>current.period_end_ms
                or latest_closed_period(y.period_end_ms)[1]!=y.period_start_ms
                or latest_closed_period(y.period_end_ms)[2]!=y.period_end_ms):
            raise AdmissionError("Label is not bound to its own next fully observed weekly interval")
        # Availability filters fitting only; it never changes the feature cohort.
        visible=np.where(y.available_at_ms<=current.decision_time_ms,y.values,np.nan)
        visible_returns.append(visible)
        label_hashes.append(_hash({"feature":s.snapshot_sha256,"end":y.period_end_ms,
            "source":y.source_id,"visible_values":[float(v) if np.isfinite(v) else None for v in visible]}))
        expected_start=y.period_end_ms
    if expected_start!=current.period_end_ms:
        raise AdmissionError("Historical training window does not end at the current feature period")
    forecast=fit_predict(np.stack([s.values for s in history]),np.stack(visible_returns),
        np.stack([s.caps for s in history]),current.values,current.caps,
        feature_times=np.array([s.decision_time_ms for s in history],dtype=np.int64),
        label_times=np.array([y.period_end_ms for y in labels],dtype=np.int64),
        decision_time=current.decision_time_ms,current_feature_time=current.period_end_ms,
        history_eligible=np.stack([s.eligible for s in history]),current_eligible=current.eligible)
    with localcontext() as ctx:
        ctx.prec=50
        members=forecast.members
        caps=[Decimal(str(float(current.caps[i]))) for i in members]
        total=sum(caps,Decimal(0))
        weights=[c/total for c in caps[:-1]]
        weights.append(Decimal(1)-sum(weights,Decimal(0)))
        target=MappingProxyType({current.asset_ids[i]:w for i,w in zip(members,weights)})
    evidence={"current_snapshot_sha256":current.snapshot_sha256,
        "historical_snapshot_sha256":[s.snapshot_sha256 for s in history],
        "visible_historical_labels_sha256":label_hashes,
        "model_diagnostics_sha256":_hash(forecast.diagnostics),
        "source_id":current.source_id,"evidence_class":"synthetic"}
    decision=PaperDecision(current.decision_time_ms,current.asset_ids,target,forecast,evidence,"")
    object.__setattr__(decision,"decision_sha256",_hash(decision.record()))
    return decision

@dataclass(frozen=True)
class QuoteBatch:
    source_event_ms:int
    observed_at_ms:int
    prices:Mapping[str,str|Decimal]
    source_id:str
    venue:str="bybit"
    evidence_class:str="synthetic"

    def __post_init__(self):
        event,observed=_time(self.source_event_ms),_time(self.observed_at_ms)
        if event>observed or self.venue!="bybit" or self.evidence_class!="synthetic" or not self.source_id.startswith("synthetic:"):
            raise AdmissionError("Only explicitly observed synthetic Bybit quotes are admitted")
        object.__setattr__(self,"prices",MappingProxyType(dict(self.prices)))

class PaperResearchSession:
    """Isolated synthetic wallet with decision replay prevention; not a writer."""
    def __init__(self):
        self.wallet=PaperWallet("500")
        self._applied=set()
        self._journal=[]
        self._last_quote_event=-1

    @property
    def journal(self):
        return deepcopy(self._journal)

    def execute(self,decision:PaperDecision,quote:QuoteBatch,specs:Mapping[str,LotSpec],*,scenario="conservative"):
        if not isinstance(decision,PaperDecision) or not isinstance(quote,QuoteBatch):
            raise AdmissionError("Validated decision and QuoteBatch required")
        if _hash(decision.record())!=decision.decision_sha256:
            raise AdmissionError("Decision integrity check failed")
        if decision.decision_sha256 in self._applied:
            raise AdmissionError("Decision already applied")
        if quote.source_event_ms<=decision.decision_time_ms:
            raise AdmissionError("Require an execution quote originating strictly after the decision")
        if quote.source_event_ms<self._last_quote_event:
            raise AdmissionError("Quote event time moved backwards")
        if scenario not in COSTS:
            raise AdmissionError("Unknown frozen cost profile")
        fee,slip=COSTS[scenario]
        report=self.wallet.rebalance(decision.target_weights,quote.prices,specs,
            timestamp=quote.observed_at_ms,fee_rate=fee,slippage_rate=slip)
        result={"decision_sha256":decision.decision_sha256,"quote_source":quote.source_id,
            "quote_event_ms":quote.source_event_ms,"scenario":scenario,"account":report,
            "scope":"synthetic_technical_only","demo_admitted":False,
            "financial_backtest_allowed":False,"paper_writer_enabled":False}
        self._applied.add(decision.decision_sha256)
        self._last_quote_event=quote.source_event_ms
        self._journal.append(deepcopy(result))
        return result

    def mark(self,quote:QuoteBatch):
        if not isinstance(quote,QuoteBatch):
            raise AdmissionError("Observed synthetic quote required")
        if quote.source_event_ms<self._last_quote_event:
            raise AdmissionError("Quote event time moved backwards")
        result=self.wallet.mark(quote.prices,timestamp=quote.observed_at_ms)
        self._last_quote_event=quote.source_event_ms
        self._journal.append({"quote_source":quote.source_id,"account":deepcopy(result)})
        return result
