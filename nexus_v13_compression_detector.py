"""Future-only, causal volatility-compression breakout research observations.

No order, backtest, API call, strategy registration, or Demo writes. This
module never scores before 2026-10-16 UTC and never reads an unclosed hour.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

RESEARCH_ONLY=True
LIVE_ENABLED=False
ORDER_EXECUTION_ENABLED=False
AUTO_DEMO=False
FACTORY_REGISTERED=False
MARKET_EVALUATIONS=0

FUTURE_START=pd.Timestamp("2026-10-16T00:00:00Z")
FUTURE_END_EXCLUSIVE=pd.Timestamp("2026-12-16T00:00:00Z")
RECENT_HOURS=6
REFERENCE_HOURS=48
REQUIRED_HOURS=55  # 54 complete TR bars and their preceding close
COMPRESSION_MAX=0.65
REFRACTORY_15M_BARS=24

def _valid_ohlc(frame:pd.DataFrame,minutes:int, label:str)->tuple[pd.DatetimeIndex,np.ndarray]:
    if not isinstance(frame,pd.DataFrame):
        raise ValueError(label+" must be a DataFrame")
    if not {"timestamp","open","high","low","close"}<=set(frame.columns):
        raise ValueError(label+" lacks required raw candle fields")
    if frame.empty:
        raise ValueError(label+" is empty")
    try:
        times=pd.DatetimeIndex(frame["timestamp"])
        if times.tz is None:raise ValueError(label+" timestamp lacks explicit timezone")
        times=times.tz_convert("UTC")
    except (TypeError,ValueError) as e:
        raise ValueError(label+" cannot validate timezone-aware UTC timestamps") from e
    stamp=times.asi8
    step=minutes*60*1_000_000_000
    if (times.hasnans or not times.is_monotonic_increasing
            or times.has_duplicates or
            (len(stamp)>1 and not np.all(np.diff(stamp)==step))
            or np.any(stamp%step!=0)):
        raise ValueError(label+" gaps, duplicates, unaligned or reordered candle OPEN timestamps")
    values=frame[["open","high","low","close"]].to_numpy(dtype=float)
    o,h,l,c=values.T
    if (not np.isfinite(values).all() or np.any(values<=0)
            or np.any(h<np.maximum(o,c)) or np.any(l>np.minimum(o,c))
            or np.any(h<l)):
        raise ValueError(label+" inconsistent or nonfinite raw OHLC")
    return times,values

def build_v13_closed_compression_features(
    minute15:pd.DataFrame, hour1:pd.DataFrame, *,
    last_completed_at:pd.Timestamp, diagnostics:list[dict[str,Any]]|None=None
)->pd.DataFrame:
    """Return strictly forward-eligible causal features on completed 15m bars.

    The hourly reference is always the 48 hours BEFORE the six-hour
    compression band. The latter must have fully CLOSED as of each 15m
    candle CLOSE. Current partial 1h bars may be present in the feed, but
    are never eligible. All windows can be reconstructed from source OHLC.
    """
    last=pd.Timestamp(last_completed_at)
    if last.tzinfo is None:raise ValueError("last_completed_at must include UTC offset")
    last=last.tz_convert("UTC")
    t15,v15=_valid_ohlc(minute15,15,"15m")
    th,vh=_valid_ohlc(hour1,60,"1h")
    if t15[-1]+pd.Timedelta(minutes=15)>last:
        raise ValueError("input contains an unclosed 15m decision candle")
    hour_done=th.asi8 + 60*60*1_000_000_000
    # Each TR uses exactly the preceding CLOSED hour's close.
    tr=np.full(len(th),np.nan,dtype=float)
    _,hi,lo,cl=vh.T
    for h in range(1,len(th)):
        tr[h]=max(hi[h]-lo[h],abs(hi[h]-cl[h-1]),abs(lo[h]-cl[h-1]))
    n=len(t15)
    result=pd.DataFrame(index=minute15.index)
    result["v13_eligible"]=[False]*n
    result["v13_compressed"]=[False]*n
    result["v13_first_close_break_event"]=[False]*n
    result["v13_refractory_denied"]=[False]*n
    for f in ("v13_compression_ratio","v13_upper_band","v13_lower_band","v13_band_span",
              "v13_completed_hour_count"):
        result[f]=np.full(n,np.nan,dtype=float)
    result["v13_band_start_utc"]=pd.Series(pd.NaT,index=minute15.index,dtype="datetime64[ns, UTC]")
    result["v13_band_end_utc"]=pd.Series(pd.NaT,index=minute15.index,dtype="datetime64[ns, UTC]")
    last_event=-REFRACTORY_15M_BARS-1
    used_bands:set[tuple[int,int]]=set()
    for i in range(n):
        decision=t15[i]+pd.Timedelta(minutes=15)
        if (decision<FUTURE_START+pd.Timedelta(minutes=15)
                or decision>=FUTURE_END_EXCLUSIVE):
            continue
        count=int(np.searchsorted(hour_done,decision.value,side="right"))
        if count<REQUIRED_HOURS:
            continue
        recent=tr[count-RECENT_HOURS:count]
        reference=tr[count-RECENT_HOURS-REFERENCE_HOURS:count-RECENT_HOURS]
        if (len(reference)!=REFERENCE_HOURS or not np.isfinite(reference).all()
                or not np.isfinite(recent).all()):
            continue
        denominator=float(np.median(reference))
        if denominator<=0:continue
        compression=float(np.median(recent))/denominator
        top=float(hi[count-RECENT_HOURS:count].max())
        bottom=float(lo[count-RECENT_HOURS:count].min())
        if not (np.isfinite(compression) and top>bottom>0):
            continue
        result.at[minute15.index[i],"v13_eligible"]=True
        result.at[minute15.index[i],"v13_completed_hour_count"]=count
        result.at[minute15.index[i],"v13_compression_ratio"]=compression
        result.at[minute15.index[i],"v13_upper_band"]=top
        result.at[minute15.index[i],"v13_lower_band"]=bottom
        result.at[minute15.index[i],"v13_band_span"]=top-bottom
        first=th[count-RECENT_HOURS]
        last_hour=th[count-1]
        result.at[minute15.index[i],"v13_band_start_utc"]=first
        result.at[minute15.index[i],"v13_band_end_utc"]=last_hour
        if compression>COMPRESSION_MAX:continue
        result.at[minute15.index[i],"v13_compressed"]=True
        if i==0:continue  # no completed previous 15m candle
        close_prev=float(v15[i-1,3])
        close_now=float(v15[i,3])
        if not (close_prev<=top<close_now):
            continue
        band=(first.value,last_hour.value)
        if band in used_bands:
            continue
        if i-last_event<=REFRACTORY_15M_BARS:
            result.at[minute15.index[i],"v13_refractory_denied"]=True
            if diagnostics is not None:
                diagnostics.append({"bar_index":i,"at_utc":decision.isoformat(),
                    "action":"fresh_break_refractory","band_start":first.isoformat()})
            continue
        used_bands.add(band)
        last_event=i
        result.at[minute15.index[i],"v13_first_close_break_event"]=True
        if diagnostics is not None:
            diagnostics.append({"bar_index":i,"at_utc":decision.isoformat(),
                "action":"first_close_break_consumed_even_if_downstream_denied",
                "band_start":first.isoformat(),"band_end":last_hour.isoformat(),
                "compression_ratio":compression,"upper_band":top,"lower_band":bottom})
    return result
