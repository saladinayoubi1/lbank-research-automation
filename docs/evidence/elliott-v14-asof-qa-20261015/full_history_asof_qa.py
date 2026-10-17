"""Complete-archive higher-TF as-of mapping audit for inspected Bybit OHLCV.

Research-only, hash-bound, read-only. Never invoke strategy signal, market
producer/backtest, order executor, owner account or installation.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from independent_higher_timeframe_qa import (
    EXPECTED, GRIDS, digest_file, validate_frame, independently_aggregate,
    numeric_discrepancies,
)

FIELDS = ("h1_vol_ok", "h1_compression", "h4_up", "h4_range")


def independent_full_values(minute: pd.DataFrame, hour: pd.DataFrame,
                            four: pd.DataFrame) -> dict[str, np.ndarray]:
    """Compute four features from 15m-reaggregated OHLC with a separate as-of."""
    # Aggregated pandas nullable Float64 columns propagate <NA> through
    # comparisons, unlike the actual parent which explicitly casts to
    # nonnullable float. Convert ONLY dtype; never fill/replace price data.
    hh=hour["high"].astype(float)
    hl=hour["low"].astype(float)
    hc=hour["close"].astype(float)
    qh=four["high"].astype(float)
    ql=four["low"].astype(float)
    qc=four["close"].astype(float)
    norm = (hh-hl)/hc
    features = {
        "h1_vol_ok": (norm < norm.shift(1).rolling(72, min_periods=72).median()*1.65),
        "h1_compression": (norm.rolling(6,min_periods=6).mean()
                           < norm.shift(1).rolling(48,min_periods=48).median()*.8),
        "h4_up": (qc > qc.shift(1).rolling(12).median()) &
                 (ql > ql.shift(4).rolling(8).min()),
        "h4_range": (qc <= qh.shift(1).rolling(12).max()) &
                    (qc >= ql.shift(1).rolling(12).min()),
    }
    decision_times=(minute.timestamp+pd.Timedelta(minutes=15)).astype("int64").to_numpy()
    out={}
    for tf, names, source, width in (
        ("hour1", ("h1_vol_ok","h1_compression"),hour,pd.Timedelta(hours=1)),
        ("hour4", ("h4_up","h4_range"),four,pd.Timedelta(hours=4)),
    ):
        closed=(source.timestamp+width).astype("int64").to_numpy()
        last=np.searchsorted(closed,decision_times,side="right")-1
        known=last>=0
        if known.any() and np.any(closed[last[known]]>decision_times[known]):
            raise AssertionError("future higher timeframe close reached decision "+tf)
        for name in names:
            result=np.full(len(minute),np.nan)
            values=features[name].astype(float).to_numpy()
            result[known]=values[last[known]]
            out[name]=result
    return out


def original_engine_asof(minute: pd.DataFrame, hour: pd.DataFrame,
                         four: pd.DataFrame, engine) -> dict[str, np.ndarray]:
    """Call original read-only _closed_asof with parent feature expressions."""
    decision=pd.DataFrame({"decision_at":minute.timestamp+pd.Timedelta(minutes=15)})
    q=four
    h=hour
    higher4=engine._closed_asof(q,14_400_000,decision,{
        "up": ((q["close"].astype(float)>q["close"].shift(1).rolling(12).median()) &
               (q["low"].astype(float)>q["low"].shift(4).rolling(8).min())).astype(float),
        "range": ((q["close"].astype(float)<=q["high"].shift(1).rolling(12).max()) &
                  (q["close"].astype(float)>=q["low"].shift(1).rolling(12).min())).astype(float),
    },"h4_")
    hourly_range=(h["high"].astype(float)-h["low"].astype(float))/h["close"].astype(float)
    higher1=engine._closed_asof(h,3_600_000,decision,{
        "compression": (hourly_range.rolling(6,min_periods=6).mean()
                        < hourly_range.shift(1).rolling(48,min_periods=48).median()*.8).astype(float),
        "vol_ok": (hourly_range
                   < hourly_range.shift(1).rolling(72,min_periods=72).median()*1.65).astype(float),
    },"h1_")
    return {name:source[name].to_numpy(dtype=float)
            for source in (higher1,higher4) for name in source.columns}


def discrepancies(actual: dict[str,np.ndarray], independent: dict[str,np.ndarray]) -> dict:
    result={}
    if set(actual)!=set(independent) or set(actual)!=set(FIELDS):
        raise AssertionError("incomplete four-feature comparison")
    for name in FIELDS:
        a=np.asarray(actual[name],dtype=float)
        b=np.asarray(independent[name],dtype=float)
        if a.shape!=b.shape:
            raise AssertionError("feature length mismatch "+name)
        mismatch=~np.isclose(a,b,rtol=0,atol=0,equal_nan=True)
        result[name]={"compared":int(len(a)),
                      "mismatches":int(mismatch.sum()),
                      "first_mismatch":(int(np.flatnonzero(mismatch)[0]) if mismatch.any() else None),
                      "nans":int(np.isnan(a).sum())}
    return result


def audit(archive: Path, engine) -> dict:
    summary={"schema":"nexus.elliott-v14-full-archive-higher-tf-qa.v1",
             "research_only":True,"live_enabled":False,
             "simulator_invoked":False,"backtest_invoked":False,
             "market_evaluations_added":0,"expected_sha256":EXPECTED,
             "signals_invoked":False,"pairs":{}}
    for symbol in ("btc_usdt","eth_usdt"):
        raw={}
        for tf in GRIDS:
            filename=archive/"bybit_market"/symbol/(tf+".parquet")
            sha=digest_file(filename)
            if sha!=EXPECTED[symbol][tf]:
                raise AssertionError(f"{symbol} {tf} byte hash mismatch")
            raw[tf]=validate_frame(pd.read_parquet(filename),tf)
        hour_reaggregated=independently_aggregate(raw["minute15"],"h")
        four_reaggregated=independently_aggregate(raw["minute15"],"4h")
        hour_check=numeric_discrepancies(raw["hour1"],hour_reaggregated)
        four_check=numeric_discrepancies(raw["hour4"],four_reaggregated)
        actual=original_engine_asof(raw["minute15"],raw["hour1"],raw["hour4"],engine)
        independent=independent_full_values(raw["minute15"],hour_reaggregated,four_reaggregated)
        checked=discrepancies(actual,independent)
        summary["pairs"][symbol]={
            "source_rows":{k:len(v) for k,v in raw.items()},
            "hour1_raw_vs_reaggregated":hour_check,
            "hour4_raw_vs_reaggregated":four_check,
            "features_entire_archive":checked,
        }
    mismatches=0
    comparisons=0
    for info in summary["pairs"].values():
        for k in ("hour1_raw_vs_reaggregated","hour4_raw_vs_reaggregated"):
            block=info[k]
            mismatches+=int(bool(block.get("timestamp_mismatch",False)))
            for v in block.values():
                if isinstance(v,dict):
                    mismatches+=v["mismatch_count"]
        for row in info["features_entire_archive"].values():
            mismatches+=row["mismatches"]
            comparisons+=row["compared"]
    summary["feature_comparisons"]=comparisons
    summary["total_mismatches"]=mismatches
    summary["disposition"]="PASS_NARROW_ALL_ARCHIVED_BARS_ASOF_QA" if mismatches==0 else "FAIL"
    return summary


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--archive",type=Path,required=True)
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()
    import nexus_composite_strategy_research as engine
    report=audit(args.archive,engine)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,indent=2,sort_keys=True,allow_nan=False)+"\n",encoding="utf-8")
    print(json.dumps({"disposition":report["disposition"],
                      "feature_comparisons":report["feature_comparisons"],
                      "total_mismatches":report["total_mismatches"],
                      "symbols":list(report["pairs"])},sort_keys=True))
    if report["total_mismatches"]:
        raise SystemExit(2)


if __name__=="__main__":
    main()
