"""Causal CTREND daily features and immutable, independently dated weekly snapshots.

This is a declared Python derivative, not a MATLAB bitwise replication.
No return targets enter feature construction. It contains no exchange client.
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import numbers
import warnings
import numpy as np

DAY_MS = 86_400_000
FEATURE_NAMES = (
    "sma_3d","sma_5d","sma_10d","sma_20d","sma_50d","sma_100d","sma_200d",
    "macd","macd_diff_signal",
    "volsma_3d","volsma_5d","volsma_10d","volsma_20d","volsma_50d","volsma_100d","volsma_200d",
    "volmacd","volmacd_diff_signal","rsi","stochRSI","stochK","stochD",
    "boll_low","boll_mid","boll_high","boll_width","cci","chaikin",
)
EPOCH = datetime(1970,1,1,tzinfo=timezone.utc)

class SnapshotUnavailable(ValueError):
    pass

def _integer(value, name):
    if (isinstance(value,(bool,np.bool_)) or not isinstance(value,numbers.Integral)
            or value < 0 or value > np.iinfo(np.int64).max):
        raise ValueError(name+" must be a nonnegative integer UTC epoch millisecond")
    return int(value)

def _time(dt):
    return int((dt-EPOCH)//timedelta(milliseconds=1))

def _readonly(value, dtype):
    a = np.array(value,dtype=dtype,copy=True)
    a.setflags(write=False)
    return a

@dataclass(frozen=True)
class DailyPanel:
    close_times_ms: np.ndarray
    available_at_ms: np.ndarray
    asset_ids: tuple[str,...]
    open: np.ndarray
    high: np.ndarray
    low: np.ndarray
    close: np.ndarray
    volume: np.ndarray
    market_caps: np.ndarray
    known_eligible: np.ndarray
    source_id: str
    evidence_class: str = "synthetic"

    def __post_init__(self):
        times=np.asarray(self.close_times_ms)
        ids=tuple(self.asset_ids)
        if times.ndim!=1 or len(times)==0 or times.dtype.kind not in "iu" or times.dtype.kind=="b":
            raise ValueError("close_times_ms must be a nonempty integer vector")
        if np.any(times<0) or np.any(times>np.iinfo(np.int64).max) or np.any(times % DAY_MS) or np.any(np.diff(times)!=DAY_MS):
            raise ValueError("daily closes must be a contiguous UTC-midnight grid")
        if not ids or len(ids)!=len(set(ids)) or any(not isinstance(x,str) or not x for x in ids):
            raise ValueError("asset IDs must be unique nonempty strings")
        shape=(len(times),len(ids))
        avail=np.asarray(self.available_at_ms)
        eligible=np.asarray(self.known_eligible)
        if (avail.shape!=shape or avail.dtype.kind not in "iu" or np.any(avail<0)
                or np.any(avail>np.iinfo(np.int64).max)):
            raise ValueError("available_at_ms must be a nonnegative integer T by N matrix")
        if np.any(avail<times[:,None]):
            raise ValueError("a complete bar cannot be available before it closes")
        if eligible.shape!=shape or eligible.dtype.kind!="b":
            raise ValueError("known_eligible must be a boolean T by N matrix")
        if self.evidence_class not in ("synthetic","unverified_real"):
            raise ValueError("unsupported evidence class")
        if not isinstance(self.source_id,str) or not self.source_id:
            raise ValueError("source ID required")
        if self.evidence_class=="synthetic" and not self.source_id.startswith("synthetic:"):
            raise ValueError("synthetic source IDs must be explicit")
        object.__setattr__(self,"asset_ids",ids)
        object.__setattr__(self,"close_times_ms",_readonly(times,np.int64))
        object.__setattr__(self,"available_at_ms",_readonly(avail,np.int64))
        object.__setattr__(self,"known_eligible",_readonly(eligible,bool))
        for name in ("open","high","low","close","volume","market_caps"):
            a=np.asarray(getattr(self,name))
            if a.shape!=shape or a.dtype.kind not in "fiu" or np.isinf(a).any():
                raise ValueError(name+" has invalid dimensions or infinities")
            object.__setattr__(self,name,_readonly(a,float))

@dataclass(frozen=True)
class FeatureSnapshot:
    decision_time_ms: int
    period_start_ms: int
    period_end_ms: int
    period_code: int
    asset_ids: tuple[str,...]
    values: np.ndarray
    caps: np.ndarray
    eligible: np.ndarray
    value_times_ms: np.ndarray
    cap_times_ms: np.ndarray
    source_id: str
    evidence_class: str
    snapshot_sha256: str

def snapshot_digest(snapshot:FeatureSnapshot):
    """Integrity only; a hash does not establish point-in-time data provenance."""
    digest=hashlib.sha256()
    digest.update(str((snapshot.decision_time_ms,snapshot.period_code,
        snapshot.period_start_ms,snapshot.period_end_ms,snapshot.asset_ids,
        snapshot.source_id,snapshot.evidence_class)).encode())
    for a,dtype in ((snapshot.values,"<f8"),(snapshot.caps,"<f8"),
                    (snapshot.eligible,"u1"),(snapshot.value_times_ms,"<i8"),
                    (snapshot.cap_times_ms,"<i8")):
        digest.update(np.ascontiguousarray(a,dtype=dtype).tobytes())
    return digest.hexdigest()

def latest_closed_period(as_of_ms):
    as_of_ms=_integer(as_of_ms,"as_of_ms")
    now=EPOCH+timedelta(milliseconds=as_of_ms)
    choices=[]
    for year in (now.year-1,now.year):
        if year<1970:
            continue
        jan=datetime(year,1,1,tzinfo=timezone.utc)
        nxt=datetime(year+1,1,1,tzinfo=timezone.utc)
        for week in range(1,53):
            start=jan+timedelta(days=7*(week-1))
            end=jan+timedelta(days=7*week) if week<52 else nxt
            if _time(end)<=as_of_ms:
                choices.append((year*100+week,_time(start),_time(end)))
    if not choices:
        raise SnapshotUnavailable("no closed weekly interval")
    return max(choices,key=lambda row:row[2])

def _rolling(a, window, min_count=1, operation="mean"):
    out=np.full_like(a,np.nan,dtype=float)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore",RuntimeWarning)
        for i in range(len(a)):
            block=a[max(0,i-window+1):i+1]
            count=np.isfinite(block).sum(axis=0)
            if operation=="mean":
                val=np.nanmean(block,axis=0)
            elif operation=="min":
                val=np.nanmin(block,axis=0)
            elif operation=="max":
                val=np.nanmax(block,axis=0)
            elif operation=="std":
                val=np.nanstd(block,axis=0,ddof=1)
            else:
                raise ValueError("unknown rolling operation")
            out[i]=np.where(count>=min_count,val,np.nan)
    return out

def _divide(a,b,neutral=None):
    a,b=np.broadcast_arrays(a,b)
    out=np.full(a.shape,np.nan)
    valid=np.isfinite(a)&np.isfinite(b)&(b!=0)
    np.divide(a,b,out=out,where=valid)
    if neutral is not None:
        out[np.isfinite(a)&np.isfinite(b)&(a==0)&(b==0)]=neutral
    return out

def _ema_source(a,window):
    # Source's prior rolling-SMA seed/restart, using only the observed prefix.
    means=_rolling(a,window)
    out=np.full_like(a,np.nan)
    alpha=2.0/(window+1)
    for i in range(1,len(a)):
        prev=np.where(np.isfinite(out[i-1]),out[i-1],means[i-1])
        out[i]=alpha*a[i]+(1-alpha)*prev
    return out

def _wilder_rsi(close,window=14):
    out=np.full_like(close,np.nan)
    for j in range(close.shape[1]):
        changes=[]
        gain=loss=None
        for i in range(1,len(close)):
            if not np.isfinite(close[i-1,j]) or not np.isfinite(close[i,j]):
                changes=[];gain=loss=None
                continue
            delta=close[i,j]-close[i-1,j]
            up,down=max(delta,0.0),max(-delta,0.0)
            if gain is None:
                changes.append((up,down))
                if len(changes)<window:
                    continue
                gain=sum(x[0] for x in changes[-window:])/window
                loss=sum(x[1] for x in changes[-window:])/window
            else:
                gain=(gain*(window-1)+up)/window
                loss=(loss*(window-1)+down)/window
            out[i,j]=50.0 if gain==loss==0 else (100.0 if loss==0 else 100.0-100.0/(1.0+gain/loss))
    return out

def _feature_matrix(close,high,low,volume):
    n=close.shape[0]
    features=[]
    for window in (3,5,10,20,50,100,200):
        features.append(_divide(_rolling(close,window),close))
    ppo=_divide(_ema_source(close,12)-_ema_source(close,26),_ema_source(close,26))
    features.extend([ppo,ppo-_ema_source(ppo,9)])
    for window in (3,5,10,20,50,100,200):
        features.append(_divide(_rolling(volume,window),np.where(volume>0,volume,np.nan)))
    pvo=_divide(_ema_source(volume,12)-_ema_source(volume,26),_ema_source(volume,26))
    features.extend([pvo,pvo-_ema_source(pvo,9)])
    rsi=_wilder_rsi(close)
    stoch_rsi=_divide(rsi-_rolling(rsi,14,5,"min"),
                      _rolling(rsi,14,5,"max")-_rolling(rsi,14,5,"min"),0.5)
    ll,hh=_rolling(low,14,14,"min"),_rolling(high,14,14,"max")
    stoch_k=_divide(close-ll,hh-ll,0.5)
    stoch_d=_rolling(stoch_k,3)
    features.extend([rsi,stoch_rsi,stoch_k,stoch_d])
    mid=_rolling(close,20,20)
    std=_rolling(close,20,20,"std")
    features.extend([_divide(mid-2*std,close),_divide(mid,close),
                     _divide(mid+2*std,close),_divide(4*std,mid)])
    typical=(close+high+low)/3
    typical_mean=_rolling(typical,20)
    cci=np.full_like(close,np.nan)
    for i in range(19,n):
        block=typical[i-19:i+1]
        good=np.isfinite(block).sum(axis=0)>=10
        with warnings.catch_warnings():
            warnings.simplefilter("ignore",RuntimeWarning)
            dev=np.nanmean(np.abs(block-typical_mean[i]),axis=0)
        cci[i]=np.where(good,_divide(typical[i]-typical_mean[i],0.015*dev,0.0),np.nan)
    money_flow=_divide((close-low)-(high-close),high-low,0.0)*volume
    cmf=np.full_like(close,np.nan)
    for i in range(20,n):
        good=np.isfinite(money_flow[i-20:i+1])&np.isfinite(volume[i-20:i+1])
        numerator=np.where(good,money_flow[i-20:i+1],0).sum(axis=0)
        denominator=np.where(good,volume[i-20:i+1],0).sum(axis=0)
        cmf[i]=np.where(good.sum(axis=0)>=10,_divide(numerator,denominator),np.nan)
    features.extend([cci,cmf])
    result=np.stack(features,axis=2)
    assert result.shape[2]==28
    # Fixed full-history requirement, separate from any realized target.
    good=np.isfinite(close)&np.isfinite(high)&np.isfinite(low)&np.isfinite(volume)
    consecutive=np.zeros(close.shape[1],dtype=int)
    for i in range(n):
        consecutive=np.where(good[i],consecutive+1,0)
        result[i,consecutive<200,:]=np.nan
    result[~np.isfinite(result)]=np.nan
    return result

def feature_snapshot(panel:DailyPanel,as_of_ms:int):
    as_of_ms=_integer(as_of_ms,"as_of_ms")
    code,start,end=latest_closed_period(as_of_ms)
    needed=np.arange(start+DAY_MS,end+1,DAY_MS,dtype=np.int64)
    if not np.isin(needed,panel.close_times_ms).all():
        raise SnapshotUnavailable("weekly calendar interval is incomplete")
    take=panel.close_times_ms<=end
    times=panel.close_times_ms[take]
    available=panel.available_at_ms[take]<=as_of_ms
    fields={name:np.array(getattr(panel,name)[take],copy=True)
            for name in ("open","high","low","close","volume","market_caps")}
    # Validation and computation concern the visible prefix only.
    for name,a in fields.items():
        visible=available&np.isfinite(a)
        if name!="volume" and np.any(a[visible]<=0):
            raise ValueError("nonpositive "+name)
        if name=="volume" and np.any(a[visible]<0):
            raise ValueError("negative volume")
        a[~available]=np.nan
    complete=np.logical_and.reduce([np.isfinite(fields[x]) for x in ("open","high","low","close","volume")])
    invalid=complete&((fields["low"]>fields["open"])|(fields["low"]>fields["close"])
                     |(fields["high"]<fields["open"])|(fields["high"]<fields["close"])
                     |(fields["high"]<fields["low"]))
    if invalid.any():
        raise ValueError("invalid visible OHLC range")
    for name in ("open","high","low","close","volume"):
        fields[name][~complete]=np.nan
    daily=_feature_matrix(fields["close"],fields["high"],fields["low"],fields["volume"])
    week=(times>start)&(times<=end)
    rows=np.flatnonzero(week)
    values=np.full((len(panel.asset_ids),28),np.nan)
    origins=np.full(values.shape,-1,dtype=np.int64)
    caps=np.full(len(panel.asset_ids),np.nan)
    cap_times=np.full(len(panel.asset_ids),-1,dtype=np.int64)
    for j in range(len(panel.asset_ids)):
        for k in range(28):
            valid=rows[np.isfinite(daily[rows,j,k])]
            if len(valid):
                idx=valid[-1];values[j,k]=daily[idx,j,k];origins[j,k]=times[idx]
        valid=rows[np.isfinite(fields["market_caps"][rows,j])]
        if len(valid):
            idx=valid[-1];caps[j]=fields["market_caps"][idx,j];cap_times[j]=times[idx]
    end_idx=np.flatnonzero(panel.close_times_ms==end)[0]
    known_current=(panel.known_eligible[end_idx] &
                   (panel.available_at_ms[end_idx]<=as_of_ms))
    eligible=known_current&np.isfinite(values).all(axis=1)&np.isfinite(caps)&(caps>=1e6)
    # Hash only the independently dated result, never future bars/target labels.
    snapshot=FeatureSnapshot(as_of_ms,start,end,code,panel.asset_ids,
                           _readonly(values,float),_readonly(caps,float),
                           _readonly(eligible,bool),_readonly(origins,np.int64),
                           _readonly(cap_times,np.int64),panel.source_id,
                           panel.evidence_class,"")
    object.__setattr__(snapshot,"snapshot_sha256",snapshot_digest(snapshot))
    return snapshot
