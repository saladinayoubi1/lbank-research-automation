"""NEXUS research-only shared 500-USDT physical candidate evaluator.

This is a reusable economic acceptance *diagnostic* for the existing
Strategy Finder factory/producer, not a strategy generator or broker adapter.

Original composite screens use TWO independent per-symbol 10,000 USDT books;
this bounded module refuses to treat that accounting as evidence that a
candidate is viable for one shared 500 USDT BTC/ETH cash balance. Physical
OHLC, indicator and boolean signals must be independently authenticated by
the calling research pipeline. Source authentication is NOT claimed here.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from hashlib import sha256
import json
import math
from typing import Any, Mapping

import numpy as np
import pandas as pd

SCHEMA="nexus.strategy-finder-shared-cash-physical-diagnostic.v1"
SYMBOLS=("BTCUSDT","ETHUSDT")
REQUIRED=("decision_at","open","high","low","close","atr")
INITIAL_USDT=500.0
MAX_GROSS_USDT=250.0
MAX_GAPLESS_STOP_LOSS_USDT=2.5
STOP_ATR_MULT=1.5
TARGET_R=2.0
MAX_HOLD_BARS=64
COSTS={"conservative":(10.0,5.0),"stress":(25.0,15.0)}
GRANULARITY_MS=900000
QUALIFIED=False
PAPER_ELIGIBLE=False
LIVE_ENABLED=False
ORDER_ADAPTER=None


class SharedCashDiagnosticError(ValueError):
    pass


def _digest(obj:dict[str,Any])->str:
    return sha256(json.dumps(obj,sort_keys=True,separators=(",",":"),
                             allow_nan=False).encode("utf-8")).hexdigest()


def validate_source(
    frames:Mapping[str,pd.DataFrame],signals:Mapping[str,np.ndarray]
)->tuple[pd.DatetimeIndex,dict[str,dict[str,np.ndarray]]]:
    """Check physical geometry and exact synchronized *closed* decision grid.

    This validates caller data consistency, NOT source exchange authenticity.
    Upstream must verify signed archive receipts and point-in-time features.
    """
    if set(frames)!=set(SYMBOLS) or set(signals)!=set(SYMBOLS):
        raise SharedCashDiagnosticError("exact authenticated BTC/ETH input contract required")
    prepared={}
    reference=None
    for symbol in SYMBOLS:
        f=frames[symbol]
        s=signals[symbol]
        if (type(f) is not pd.DataFrame or
            any(field not in f.columns for field in REQUIRED) or
            not isinstance(s,np.ndarray) or s.dtype!=np.dtype("bool") or
            s.ndim!=1 or len(s)!=len(f) or len(f)<2):
            raise SharedCashDiagnosticError("bad candidate/physical signal shape")
        try:
            ts=pd.DatetimeIndex(pd.to_datetime(f["decision_at"],utc=True,errors="raise"))
        except (ValueError,TypeError,OverflowError) as exc:
            raise SharedCashDiagnosticError("invalid source UTC close time") from exc
        if (ts.hasnans or not ts.is_monotonic_increasing or not ts.is_unique
            or not (ts.asi8 % (GRANULARITY_MS*1000000)==0).all()
            or not (np.diff(ts.asi8)==GRANULARITY_MS*1000000).all()):
            raise SharedCashDiagnosticError("noncontiguous closed 15m source")
        if reference is not None and not reference.equals(ts):
            raise SharedCashDiagnosticError("peer candle timestamp mismatch")
        reference=ts
        values={col:f[col].to_numpy(dtype=float) for col in REQUIRED[1:]}
        if (any(not np.isfinite(x).all() for x in values.values()) or
            any((values[x]<=0).any() for x in ("open","high","low","close")) or
            (values["high"]<np.maximum.reduce((
               values["open"],values["close"],values["low"]))).any() or
            (values["low"]>np.minimum.reduce((
               values["open"],values["close"],values["high"]))).any()):
            raise SharedCashDiagnosticError("nonphysical price or nonfinite ATR")
        # Warmup unknown ATR is allowed, but its candle cannot create an entry.
        prepared[symbol]=values
    assert reference is not None
    return reference,prepared


def replay_shared_cash(
    frames:Mapping[str,pd.DataFrame],
    signals:Mapping[str,np.ndarray],
    start:int,end:int,profile:str,
)->dict[str,Any]:
    """Physical long-only single position, next-open entry, stop-first exit.

    Candidate signals are generated solely from the close of bar j. The
    original signal may fill only at bar j+1 OPEN, never at its historical
    center/current close. If BTC/ETH submit at the same open, alphabetical
    BTC wins, ETH denial is preserved. Cash is reserved until exit.
    Independent partition segments never share future-source information.
    """
    if profile not in COSTS:
        raise SharedCashDiagnosticError("only two predetermined cost profiles")
    times,data=validate_source(frames,signals)
    n=len(times)
    if (type(start) is not int or type(end) is not int
        or not 0<=start<end<=n or end-start<2):
        raise SharedCashDiagnosticError("invalid complete physical research partition")
    fee_bps,slip_bps=COSTS[profile]
    fee=fee_bps/10000.0
    slip=slip_bps/10000.0
    cash=INITIAL_USDT
    peak=INITIAL_USDT
    max_dd=0.0
    active=None
    attempts=Counter()
    denials=Counter()
    closed=[]
    fees_total=0.0
    signals_seen=0
    for i in range(start,end):
        # First physically observable entry is next OPEN after prior close.
        due=[]
        if i>start:
            due=[symbol for symbol in SYMBOLS if bool(signals[symbol][i-1])]
            signals_seen+=len(due)
        if due and active is not None:
            for sym in due:
                denials["SHARED_CASH_POSITION_OCCUPIED"]+=1
        elif due:
            for symbol in due:
                a=data[symbol]
                prior_atr=float(a["atr"][i-1])
                attempts["next_open_intent"]+=1
                if (not np.isfinite(prior_atr) or prior_atr<=0):
                    denials["UNAVAILABLE_PRIOR_ATR"]+=1
                    continue
                midpoint=float(a["open"][i])
                fill=midpoint*(1+slip)
                stop=fill-STOP_ATR_MULT*prior_atr
                target=fill+TARGET_R*(fill-stop)
                if not 0<stop<fill<target:
                    denials["INVALID_ATR_STOP_GEOMETRY"]+=1
                    continue
                stop_liquidation=stop*(1-slip)*(1-fee)
                per_unit_spend=fill*(1+fee)
                gapless_risk=per_unit_spend-stop_liquidation
                if gapless_risk<=0:
                    raise SharedCashDiagnosticError("invalid cost-aware downside")
                qty=math.floor(min(
                    MAX_GROSS_USDT/fill,
                    MAX_GAPLESS_STOP_LOSS_USDT/gapless_risk,
                    cash/per_unit_spend,
                )*1e8)/1e8
                if qty<=0:
                    denials["NO_SHARED_CASH_OR_RISK_CAPACITY"]+=1
                    continue
                spent=qty*per_unit_spend
                if (spent>cash+1e-7 or qty*fill>MAX_GROSS_USDT+1e-7
                    or qty*gapless_risk>MAX_GAPLESS_STOP_LOSS_USDT+1e-7):
                    raise SharedCashDiagnosticError("cash or worst nominal stop overrun")
                entry_fee=qty*fill*fee
                fees_total+=entry_fee
                cash-=spent
                active={
                    "symbol":symbol,"index":i,"entry_open_ms":int(times[i].value//10**6),
                    "entry_fill":fill,"entry_fee":entry_fee,"qty":qty,
                    "entry_cash":spent,"stop":stop,"target":target,
                }
                attempts["admitted"]+=1
                break
            if active is not None and len(due)>1:
                denials["SAME_OPEN_LOWER_PRIORITY_PEER"]+=len(due)-due.index(active["symbol"])-1
                # A declined pre-BTC due candidate may already have a
                # separate causal reason; do not count as peer priority twice.
        if active is not None:
            a=data[active["symbol"]]
            op,high,low,close=(float(a[key][i]) for key in (
               "open","high","low","close"))
            stop=active["stop"]
            target=active["target"]
            label=None
            level=None
            if op<=stop:
                label="STOP_GAP_AT_WORSE_OPEN"
                level=op
            elif i-active["index"]>=MAX_HOLD_BARS:
                label="TIMEOUT_AT_PHYSICAL_NEXT_OPEN"
                level=op
            elif low<=stop:
                label=("STOP_FIRST_INTRABAR_BOTH" if high>=target
                       else "STRUCTURAL_STOP")
                level=stop
            elif high>=target:
                label="PRECOMMITTED_TARGET"
                level=target
            elif i==end-1:
                # At the split's last full candle CLOSE, liquidate,
                # explicitly and conservatively, without borrowing an
                # unseen next-partition OPEN or marking unrealized profit.
                label="PARTITION_LAST_COMPLETED_CLOSE"
                level=close
            if label is not None:
                exit_fill=float(level)*(1-slip)
                qty=active["qty"]
                exit_fee=qty*exit_fill*fee
                proceeds=qty*exit_fill-exit_fee
                pnl=proceeds-active["entry_cash"]
                cash+=proceeds
                fees_total+=exit_fee
                closed.append({
                    "symbol":active["symbol"],
                    "entry_open_ms":active["entry_open_ms"],
                    "exit_event_ms":int(times[i].value//10**6),
                    "exit_reason":label,
                    "qty":round(qty,8),
                    "entry_fill":round(active["entry_fill"],8),
                    "exit_fill":round(exit_fill,8),
                    "stop":round(stop,8),"target":round(target,8),
                    "pnl_usdt":round(pnl,8),
                })
                active=None
        equity=cash if active is None else cash+active["qty"]*float(
            data[active["symbol"]]["close"][i])
        peak=max(peak,equity)
        max_dd=max(max_dd,1-equity/peak)
        if cash<-1e-6:
            raise SharedCashDiagnosticError("negative collateral from physical replay")
    if active is not None:
        raise SharedCashDiagnosticError("unclosed source partition")
    month=defaultdict(lambda:{"round_trips":0,"net_pnl_usdt":0.0})
    for row in closed:
        bucket=pd.Timestamp(row["exit_event_ms"],unit="ms",tz="UTC").strftime("%Y-%m")
        month[bucket]["round_trips"]+=1
        month[bucket]["net_pnl_usdt"]+=row["pnl_usdt"]
    monthly=[{"month":m,"round_trips":v["round_trips"],
              "net_pnl_usdt":round(v["net_pnl_usdt"],8),
              "mean_pnl_usdt":round(v["net_pnl_usdt"]/v["round_trips"],8)}
             for m,v in sorted(month.items())]
    net=cash-INITIAL_USDT
    if (sum(x["round_trips"] for x in monthly)!=len(closed)
        or abs(net-sum(x["pnl_usdt"] for x in closed))>1e-5
        or abs(net-sum(x["net_pnl_usdt"] for x in monthly))>1e-5):
        raise SharedCashDiagnosticError("physical monthly/shared-cash PNL drift")
    return {
        "schema":SCHEMA,"scope":"CALLER_SOURCE_NOT_AUTHENTICATED",
        "cost_profile":profile,"start_closed_at_utc":times[start].isoformat(),
        "end_closed_at_utc":times[end-1].isoformat(),
        "initial_shared_cash_usdt":INITIAL_USDT,
        "ending_shared_cash_usdt":round(cash,8),
        "net_pnl_usdt":round(net,8),
        "max_drawdown_pct":round(100*max_dd,8),
        "trades":len(closed),
        "positive_trades":sum(t["pnl_usdt"]>0 for t in closed),
        "mean_pnl_usdt":round(net/len(closed),8) if closed else None,
        "fees_paid_usdt":round(fees_total,8),
        "signals_due_at_next_open":signals_seen,
        "denial_reasons":dict(sorted(denials.items())),
        "attempt_counts":dict(sorted(attempts.items())),
        "exit_reasons":dict(sorted(Counter(x["exit_reason"] for x in closed).items())),
        "monthly":monthly,"ledger":closed,
        "max_nominal_gapless_risk_usdt":MAX_GAPLESS_STOP_LOSS_USDT,
        "max_gross_usdt":MAX_GROSS_USDT,
        "source_market_authenticity_attested_here":False,
        "not_pristine_out_of_sample":True,
        "qualified":False,"paper_eligible":False,"live_enabled":False,
        "orders":0,
    }


def sidecar_summary(
    frames:Mapping[str,pd.DataFrame],signals:Mapping[str,np.ndarray]
)->dict[str,Any]:
    """60/20/20 split; runs independent, shared-book paired-cost diagnostics.

    Never marks a candidate as qualified even if the historical P/L were
    positive. Demonstrable independent future data and actual Demo safety
    checks are external prerequisites.
    """
    t,_=validate_source(frames,signals)
    n=len(t)
    c1,c2=int(n*.6),int(n*.8)
    if c1<2 or c2-c1<2 or n-c2<2:
        raise SharedCashDiagnosticError("60/20/20 insufficient physical bars")
    out={}
    for key,(lo,hi) in {
        "training":(0,c1),
        "validation_already_inspected":(c1,c2),
        "historical_test_already_inspected":(c2,n),
    }.items():
        out[key]={profile:replay_shared_cash(frames,signals,lo,hi,profile)
                  for profile in COSTS}
    core={
        "schema":SCHEMA,
        "scope":"RESEARCH_SIDECAR_UNVERIFIED_CALLER_SOURCE",
        "account_topology":"one_500_usdt_shared_cash_BTC_ETH_spot_long_only",
        "legacy_account_topology_incompatible":
           "original_10000_usdt_independent_per_symbol_backtest",
        "training_validation_historical_test_not_pristine":True,
        "all_params_fixed_no_tuning":True,
        "source_authentication_and_candidate_semantic_novelty_required":True,
        "not_qualified_for_demo":True,
        "qualified":False,"paper_eligible":False,
        "live_enabled":False,"orders":0,"partitions":out,
    }
    return {**core,"result_digest":_digest(core)}
