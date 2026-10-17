"""Independent READ-ONLY Bybit higher-timeframe OHLC and as-of feature QA.

Does NOT call strategy signal_for/backtest, mutate archives or infer profitability.
Only checks immutable existing inspected OHLC archive. Run on Laptop2.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

EXPECTED = {
    "btc_usdt": {
        "minute15": "c3afe92899dda8fe52937c955323cc8e04bf8f200a68eb8651e55d6020981226",
        "hour1": "f8f2236785c036fe40808809397d47729b3add4c8f0b9e19c77d3b771f8e6847",
        "hour4": "e0d019a76882a02dc463a34d1d9375841f81d412b9a3310d9e21c2d7b2738dc6",
    },
    "eth_usdt": {
        "minute15": "ce603440650d0022b1a17a7922da743a3b6219ba9afd89ad4362b70fbe3bbfa1",
        "hour1": "ba0743588c5089e6a6b250b4ebb029a43fea57d0a020df5ab1316c34efdcd88a",
        "hour4": "292005e091d914fbb9d108c3d8d65e93785cc32b9c73e07ea02e0d44cf7da65b",
    },
}
GRIDS = {"minute15": pd.Timedelta(minutes=15), "hour1": pd.Timedelta(hours=1), "hour4": pd.Timedelta(hours=4)}
OHLCV = ("open","high","low","close","volume")


def digest_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fp:
        for chunk in iter(lambda: fp.read(1<<20), b""):
            h.update(chunk)
    return h.hexdigest()


def validate_frame(frame: pd.DataFrame, timeframe: str) -> pd.DataFrame:
    if not {"timestamp", *OHLCV}.issubset(frame.columns):
        raise AssertionError("missing source columns")
    f = frame.copy()
    f["timestamp"] = pd.to_datetime(f.timestamp, utc=True, errors="raise")
    if not (f.timestamp.notna().all() and f.timestamp.is_monotonic_increasing and
            f.timestamp.is_unique and (f.timestamp.diff().dropna() == GRIDS[timeframe]).all()):
        raise AssertionError("source UTC grid invalid for "+timeframe)
    ns = f.timestamp.astype("int64").to_numpy()
    if ((ns % GRIDS[timeframe].value) != 0).any():
        raise AssertionError("unaligned source timestamps "+timeframe)
    vals=f[list(OHLCV)].astype(float)
    if not (np.isfinite(vals.to_numpy()).all() and (vals[list(OHLCV[:-1])] > 0).all().all() and
            (vals.volume >= 0).all() and
            (vals.high >= vals[["open","close","low"]].max(axis=1)).all() and
            (vals.low <= vals[["open","close","high"]].min(axis=1)).all()):
        raise AssertionError("invalid source OHLCV "+timeframe)
    return f


def independently_aggregate(source: pd.DataFrame, freq: str) -> pd.DataFrame:
    grouped=source.groupby(source.timestamp.dt.floor(freq),sort=True)
    return grouped.agg(open=("open","first"), high=("high","max"), low=("low","min"),
                       close=("close","last"), volume=("volume","sum")).reset_index()


def numeric_discrepancies(actual: pd.DataFrame, expected: pd.DataFrame):
    if not actual.timestamp.equals(expected.timestamp):
        return {"timestamp_mismatch":True,"rows":len(actual),"expected_rows":len(expected)}
    result={}
    for field in OHLCV:
        lhs=actual[field].to_numpy(dtype=float)
        rhs=expected[field].to_numpy(dtype=float)
        tolerance = 1e-8 if field!="volume" else 1e-6
        mismatch=~np.isclose(lhs,rhs,rtol=1e-10,atol=tolerance)
        result[field]={"mismatch_count":int(mismatch.sum()),
                       "max_absolute_difference":float(np.max(np.abs(lhs-rhs))),
                       "first_mismatch_index":(int(np.flatnonzero(mismatch)[0]) if mismatch.any() else None)}
    return result


def independent_features(hour: pd.DataFrame, four: pd.DataFrame, minute: pd.DataFrame):
    # Boolean historical definitions copied from reviewed parent source,
    # computed on independently reconstructed 15m -> 1h/4h frames.
    up = (four.close > four.close.shift(1).rolling(12).median()) & (
        four.low > four.low.shift(4).rolling(8).min())
    hourly_norm = (hour.high-hour.low)/hour.close
    hour_ok = hourly_norm < hourly_norm.shift(1).rolling(72).median()*1.65
    # Each hourly/4h source OPEN timestamp becomes available only at CLOSE.
    decisions=(minute.timestamp+pd.Timedelta(minutes=15)).astype("int64").to_numpy()
    hclose=(hour.timestamp+pd.Timedelta(hours=1)).astype("int64").to_numpy()
    qclose=(four.timestamp+pd.Timedelta(hours=4)).astype("int64").to_numpy()
    hi=np.searchsorted(hclose,decisions,side="right")-1
    qi=np.searchsorted(qclose,decisions,side="right")-1
    expected_h1=np.full(len(minute),np.nan)
    expected_h4=np.full(len(minute),np.nan)
    hourarr=hour_ok.astype(float).to_numpy()
    fourarr=up.astype(float).to_numpy()
    hvalid=hi>=0
    qvalid=qi>=0
    expected_h1[hvalid]=hourarr[hi[hvalid]]
    expected_h4[qvalid]=fourarr[qi[qvalid]]
    assert not np.any(hclose[hi[hvalid]]>decisions[hvalid])
    assert not np.any(qclose[qi[qvalid]]>decisions[qvalid])
    return expected_h1,expected_h4


def engine_comparison(source: dict, engine, independent_full: tuple, indexes: slice):
    # Run *feature builder*, NOT simulator/backtest/signal. Aligned slices
    # have their own historical warmup and are not market re-evaluations.
    f=source["minute15"].iloc[indexes].reset_index(drop=True).copy()
    first=f.timestamp.iloc[0]
    end=f.timestamp.iloc[-1]
    h=source["hour1"][(source["hour1"].timestamp>=first) &
                      (source["hour1"].timestamp<=end)].reset_index(drop=True).copy()
    q=source["hour4"][(source["hour4"].timestamp>=first) &
                      (source["hour4"].timestamp<=end)].reset_index(drop=True).copy()
    output=engine.build_features({"minute15":f,"hour1":h,"hour4":q})
    # Local sliced warmup cannot match full-archive historic rolling values.
    # Exclude first 7 calendar days for conservative 72h/4h lookback warmup.
    warmup=(f.timestamp >= first + pd.Timedelta(days=7)).to_numpy()
    full_h1=independent_full[0][indexes]
    full_h4=independent_full[1][indexes]
    def diff(name, want):
        got=output[name].to_numpy(dtype=float)
        mismatch=~(np.isclose(got,want,rtol=0,atol=0,equal_nan=True))
        return {"compared":int(warmup.sum()),"mismatches":int((mismatch&warmup).sum()),
                "first_mismatch_local_index":int(np.flatnonzero(mismatch&warmup)[0]) if (mismatch&warmup).any() else None}
    return {"window_start_utc":str(first),"window_end_utc":str(end),
            "h1_vol_ok":diff("h1_vol_ok",full_h1),
            "h4_up":diff("h4_up",full_h4),
            "backtest_invoked":False,"signal_invoked":False}


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--archive",type=Path,required=True)
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()
    result={"schema":"nexus.elliott-v14-independent-higher-timeframe-qa.v1",
            "archive":str(args.archive),"research_only":True,"simulator_invoked":False,
            "new_market_evaluations":0,"source_sha256":EXPECTED,"pairs":{}}
    import nexus_composite_strategy_research as engine  # builder only
    for sym in ("btc_usdt","eth_usdt"):
        source={}
        for tf in GRIDS:
            p=args.archive/"bybit_market"/sym/(tf+".parquet")
            sha=digest_file(p)
            if sha!=EXPECTED[sym][tf]:
                raise AssertionError(f"{sym} {tf} SHA256 mismatch: {sha}")
            source[tf]=validate_frame(pd.read_parquet(p),tf)
        hi=independently_aggregate(source["minute15"],"h")
        qi=independently_aggregate(source["minute15"],"4h")
        hour_data=numeric_discrepancies(source["hour1"],hi)
        four_data=numeric_discrepancies(source["hour4"],qi)
        expected=independent_features(hi,qi,source["minute15"])
        # 8192 15m bars per window; both edges are 4h-aligned due dataset size.
        windows=[engine_comparison(source,engine,expected,slice(0,8192)),
                 engine_comparison(source,engine,expected,slice(-8192,None))]
        result["pairs"][sym]={"rows":{tf:len(source[tf]) for tf in GRIDS},
            "h1_aggregated_ohlcv_comparison":hour_data,
            "h4_aggregated_ohlcv_comparison":four_data,
            "engine_closed_asof_feature_comparison":windows}
    mismatch=0
    for p in result["pairs"].values():
        for key in ("h1_aggregated_ohlcv_comparison","h4_aggregated_ohlcv_comparison"):
            m=p[key]
            mismatch+=sum(v["mismatch_count"] for v in m.values() if isinstance(v,dict))
            mismatch+=int(bool(m.get("timestamp_mismatch",False)))
        for window in p["engine_closed_asof_feature_comparison"]:
            mismatch+=window["h1_vol_ok"]["mismatches"]+window["h4_up"]["mismatches"]
    result["total_mismatches"]=mismatch
    result["disposition"]="PASS_NARROW_SOURCE_VALUE_QA" if mismatch==0 else "FAIL_SOURCE_OR_ASOF_MISMATCH"
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,indent=2,sort_keys=True,allow_nan=False)+"\n",encoding="utf-8")
    print(json.dumps({"disposition":result["disposition"],"total_mismatches":mismatch,
                      "pairs":{k:{"rows":v["rows"],"h1_values":v["engine_closed_asof_feature_comparison"]}
                               for k,v in result["pairs"].items()}},indent=2))
    if mismatch:
        raise SystemExit(2)


if __name__=="__main__":
    main()
