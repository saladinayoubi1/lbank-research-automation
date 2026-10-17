"""Forensic economics of FROZEN Elliott fills; NO new execution or backtest.

Check only the existing admitted entries against the immutable Bybit 15m
archive. Compute ex-ante structural-stop distance, next-open gap, and fixed
cost feasibility without touching exit paths or extrapolating profits.
"""
from __future__ import annotations

import argparse
from decimal import Decimal, InvalidOperation, localcontext
import hashlib
import json
from pathlib import Path
from statistics import median

import numpy as np
import pandas as pd

RESEARCH_ONLY = True
LIVE_ENABLED = False
AUTO_DEMO = False
SIMULATOR_INVOKED = False
FROZEN_TRACE_SHA256 = "c734d9abd0dd8a18fe4269a15b8eceddf91643d8943ddb3bc851311772f2373c"
MARKET_SHA256 = {
    "BTCUSDT":"c3afe92899dda8fe52937c955323cc8e04bf8f200a68eb8651e55d6020981226",
    "ETHUSDT":"ce603440650d0022b1a17a7922da743a3b6219ba9afd89ad4362b70fbe3bbfa1",
}
PROFILES = {
    "conservative": (Decimal("10"), Decimal("5")),
    "stress": (Decimal("25"), Decimal("15")),
}
BTC_ETH = {"BTCUSDT":"btc_usdt", "ETHUSDT":"eth_usdt"}
RISK_BUDGET_REFERENCE_USDT = Decimal("10")  # 0.1% of independent 10,000 simulation cell, NOT owner wallet
BACKTEST_CELL_USDT = Decimal("10000")


def sha256(path: Path) -> str:
    digest=hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda:stream.read(1<<20),b""):
            digest.update(block)
    return digest.hexdigest()


def num(v: object, title: str, *, zero_allowed: bool = False) -> Decimal:
    if isinstance(v, bool):
        raise ValueError(title+" is boolean")
    try:
        d=Decimal(str(v))
    except (InvalidOperation, ValueError, TypeError) as e:
        raise ValueError(title+" malformed") from e
    if not d.is_finite() or d<0 or (d==0 and not zero_allowed):
        raise ValueError(title+" must be finite positive")
    return d


def approx(a: Decimal,b: Decimal, name: str) -> None:
    # Stored engine trace is float. Fixed 0.0001% relative tolerance
    # accommodates float representation without erasing price errors.
    if abs(a-b)>max(Decimal("0.0000001"),abs(b)*Decimal("0.000000001")):
        raise AssertionError(name+" does not reconcile to original archive")


def validate_archive_frame(df: pd.DataFrame) -> None:
    required={"timestamp","open","high","low","close"}
    if not required.issubset(df.columns):
        raise ValueError("missing UTC and OHLC in archive")
    ts=pd.to_datetime(df.timestamp,utc=True,errors="raise")
    if ts.hasnans or not ts.is_unique or not ts.is_monotonic_increasing:
        raise ValueError("archive timestamps unordered or duplicate")
    nanos=ts.astype("int64").to_numpy()
    step=900_000_000_000
    if (nanos%step).any() or (np.diff(nanos)!=step).any():
        raise ValueError("archive is not 15m aligned/contiguous")
    ohlc=df[["open","high","low","close"]].to_numpy(dtype=float)
    if (not np.isfinite(ohlc).all() or (ohlc<=0).any()
            or (ohlc[:,1]<ohlc[:,[0,2,3]].max(axis=1)).any()
            or (ohlc[:,2]>ohlc[:,[0,1,3]].min(axis=1)).any()):
        raise ValueError("invalid OHLC source")


def observed_next_open_diagnostic(
    df: pd.DataFrame, attempt: dict, profile: str,
) -> dict:
    if profile not in PROFILES or attempt.get("disposition")!="filled":
        raise ValueError("non-filled or unknown profile")
    decision=attempt["decision"]
    setup=decision["setup"]
    i=decision["bar_index"]
    next_idx=attempt["fill_bar"]["bar_index"]
    wave2_idx=int(setup["lagged_elliott5_wave2_index"])
    if (type(i) is not int or type(next_idx) is not int
            or not (14<i<len(df)-1) or next_idx!=i+1
            or not (0<=wave2_idx<i)):
        raise AssertionError("causal decision/fill/pivot index mismatch")
    timestamp=pd.to_datetime(df.timestamp, utc=True)
    open_at=timestamp.iloc[next_idx]
    if (pd.Timestamp(decision["decision_at"])!=open_at
            or pd.Timestamp(attempt["fill_bar"]["open_at"])!=open_at
            or pd.Timestamp(attempt["fill_bar"]["decision_at"])!=open_at+pd.Timedelta(minutes=15)):
        raise AssertionError("next-open timing mismatched source")
    fee_bps, slip_bps = PROFILES[profile]
    with localcontext() as context:
        context.prec=42
        reference=num(df.iloc[next_idx]["open"],"next 15m open")
        reference_trace=num(attempt["entry_reference"],"trace entry reference")
        approx(reference_trace,reference,"next-open fill price")
        entry=reference*(Decimal(1)+slip_bps/Decimal(10000))
        approx(num(attempt["entry_slipped"],"trace slipped entry"),entry,"slipped fill")
        correction=num(setup["lagged_elliott5_wave2_low"],"confirmed correction low")
        approx(num(df.iloc[wave2_idx]["low"],"source correction low"),correction,
               "raw correction low")
        parent_proxy_atr=num(attempt["atr"],"parent mean high-low")
        lo=df["low"].iloc[i-14:i].to_numpy(dtype=float)
        hi=df["high"].iloc[i-14:i].to_numpy(dtype=float)
        avg_parent=Decimal(str(np.mean(hi-lo)))
        approx(parent_proxy_atr,avg_parent,"parent shifted high-low ATR proxy")
        original_stop=num(attempt["stop"],"original 1.5-bar-range stop")
        approx(original_stop,entry-Decimal("1.5")*parent_proxy_atr,
               "parent 1.5x stop")
        decision_close=num(df.iloc[i]["close"],"decision close")
        struct_dist=entry-correction
        if struct_dist<=0:
            return {
                "profile":profile, "decision_index":i,
                "status":"GAP_BELOW_OR_AT_STRUCTURAL_STOP",
                "entry_usdt":str(entry), "confirmed_low":str(correction),
                "risk_per_unit":str(struct_dist),
                "next_open_gap_pct":str((reference/decision_close-1)*100),
                "assumptions":"historical simulated fill, no future outcome", 
            }
        parent_stop_dist=entry-original_stop
        if parent_stop_dist<=0:
            raise AssertionError("parent stop risk invalid")
        # True Range for exactly the SAME previously completed 14 candles,
        # not including current decision or future fill bar.
        prev_close=df["close"].iloc[i-15:i-1].to_numpy(dtype=float)
        tr=np.maximum(hi-lo,np.maximum(abs(hi-prev_close),abs(lo-prev_close)))
        tr_mean=Decimal(str(np.mean(tr)))
        target=entry+Decimal(2)*struct_dist
        target_exit=target*(Decimal(1)-slip_bps/Decimal(10000))
        stop_exit=correction*(Decimal(1)-slip_bps/Decimal(10000))
        fee_fraction=fee_bps/Decimal(10000)
        target_gain=target_exit-entry-fee_fraction*(entry+target_exit)
        stop_loss=stop_exit-entry-fee_fraction*(entry+stop_exit)
        if target_gain<=0 or stop_loss>=0:
            raise AssertionError("projection does not satisfy positive target/negative stop")
        required_wins=(-stop_loss)/(target_gain-stop_loss)
        if not 0<required_wins<1:
            raise AssertionError("break-even win probability outside (0,1)")
        # Reference-only size is NOT entered and does NOT include execution
        # side constraints, wallet, liquidity, margin or varying fee tiers.
        size_by_stop=RISK_BUDGET_REFERENCE_USDT/struct_dist
        size_by_cash=(BACKTEST_CELL_USDT*Decimal("0.1"))/entry
        quantity_if_approved=min(size_by_stop,size_by_cash)
        return {
            "profile":profile, "decision_index":i,
            "status":"EX_ANTE_STRUCTURAL_RISK_ONLY",
            "decision_at_utc":str(open_at),
            "entry_reference":str(reference), "entry_slipped":str(entry),
            "decision_close":str(decision_close),
            "confirmed_low":str(correction),
            "original_stop":str(original_stop),
            "parent_stop_risk_per_unit":str(parent_stop_dist),
            "structural_risk_per_unit":str(struct_dist),
            "structural_to_parent_stop_multiple":str(struct_dist/parent_stop_dist),
            "structural_risk_to_parent_proxy_atr":str(struct_dist/parent_proxy_atr),
            "structural_risk_to_prior_true_range_mean":str(struct_dist/tr_mean),
            "parent_proxy_atr":str(parent_proxy_atr),
            "prior_completed_true_range_mean":str(tr_mean),
            "next_open_gap_pct":str((reference/decision_close-1)*100),
            "structural_target_2r":str(target),
            "projected_target_net_per_unit":str(target_gain),
            "projected_stop_net_per_unit":str(stop_loss),
            "break_even_target_hit_fraction_if_full_2r":str(required_wins),
            "reference_size_for_10_usdt_stop_budget_and_1000_usdt_cash_cap":
                str(quantity_if_approved),
            "reference_dollar_stop_risk_before_gap_or_fees":
                str(quantity_if_approved*struct_dist),
            "actual_future_target_or_stop_result":"NOT_EVALUATED",
            "simulator_invoked":False,
        }


def audit(archive: Path, trace_path: Path) -> dict:
    if sha256(trace_path)!=FROZEN_TRACE_SHA256:
        raise AssertionError("frozen actual-fill-trace SHA256 mismatch")
    trace=json.loads(trace_path.read_text(encoding="utf-8"))
    if trace.get("schema")!="elliott-five-swing-fill-trace/v1" or trace.get("live_enabled") is not False:
        raise AssertionError("not a frozen research trace")
    frames={}
    for symbol,directory in BTC_ETH.items():
        path=archive/"bybit_market"/directory/"minute15.parquet"
        if sha256(path)!=MARKET_SHA256[symbol]:
            raise AssertionError("frozen source sha mismatch "+symbol)
        frame=pd.read_parquet(path)
        validate_archive_frame(frame)
        frames[symbol]=frame
    rows=[]; seen=set()
    for trace_row in trace["rows"]:
        symbol=trace_row["symbol"];profile=trace_row["profile"]
        if symbol not in BTC_ETH or profile not in PROFILES:
            raise AssertionError("unrecognized historical cell")
        for attempt in trace_row["entry_attempts"]:
            if attempt.get("disposition")!="filled":
                raise AssertionError("only accepted frozen fills are admissible")
            decision=attempt["decision"]["bar_index"]
            key=(symbol,profile,decision)
            if key in seen:
                raise AssertionError("duplicate profile fill")
            seen.add(key)
            x=observed_next_open_diagnostic(frames[symbol],attempt,profile)
            rows.append({"symbol":symbol,"part":trace_row["part"],**x})
    keys_by_profile={p:{(row["symbol"],row["decision_index"]) for row in rows if row["profile"]==p}
                     for p in PROFILES}
    if keys_by_profile["conservative"]!=keys_by_profile["stress"]:
        raise AssertionError("profile fill universe differs; comparison invalid")
    if len(rows)!=20 or len(keys_by_profile["conservative"])!=10:
        raise AssertionError("unexpected frozen entry universe")
    if any(r["status"]!="EX_ANTE_STRUCTURAL_RISK_ONLY" for r in rows):
        raise AssertionError("next open below confirmed low: no modelable structural stop")
    def bounds(profile,field):
        v=[Decimal(r[field]) for r in rows if r["profile"]==profile]
        return {"min":str(min(v)),"median":str(median(v)),"max":str(max(v))}
    return {
        "schema":"nexus.elliott-v16-frozen-entry-risk-geometry.v1",
        "disposition":"PASS_FROZEN_ENTRY_AND_EX_ANTE_RISK_GEOMETRY",
        "source_sha256":{"trace":FROZEN_TRACE_SHA256,"15m":MARKET_SHA256},
        "research_only":True,"live_enabled":False,"demo_enabled":False,
        "orders_placed":0,"producer_invoked":False,"backtest_rerun":False,
        "counterfactual_outcomes_computed":False,
        "old_entry_records":len(rows),
        "independent_entries":len(keys_by_profile["conservative"]),
        "rows":rows,
        "summary":{p:{
            "structural_to_parent_stop_multiple":bounds(p,"structural_to_parent_stop_multiple"),
            "structural_risk_to_prior_true_range_mean":bounds(p,"structural_risk_to_prior_true_range_mean"),
            "next_open_gap_pct":bounds(p,"next_open_gap_pct"),
            "break_even_target_hit_fraction_if_full_2r":
                bounds(p,"break_even_target_hit_fraction_if_full_2r"),
        } for p in PROFILES},
        "interpretation":"Ex-ante projection only: cannot infer hit rate or P/L without a new "
                         "prospectively preregistered outcome simulation",
    }


def main() -> None:
    parser=argparse.ArgumentParser()
    parser.add_argument("--archive",type=Path,required=True)
    parser.add_argument("--trace",type=Path,required=True)
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()
    receipt=audit(args.archive,args.trace)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(receipt,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    print(json.dumps({k:receipt[k] for k in ("disposition","old_entry_records","independent_entries","summary")},indent=2))


if __name__=="__main__":
    main()
