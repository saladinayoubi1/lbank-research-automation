"""Verify the cached Decimal oracle against frozen unrounded scalar outputs."""
from pathlib import Path
import argparse, ast, hashlib, importlib.util, json, os, socket, time
from decimal import Decimal
import pandas as pd
from unittest.mock import patch

def blob(raw):
    raw = raw.replace(b"\r\n", b"\n")
    return hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()

def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

def normalize(value):
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return {k:normalize(v) for k,v in value.items()}
    if isinstance(value, list):
        return [normalize(v) for v in value]
    return value

def frame(kind):
    def row(op, hi, lo, cl, atr=2):
        return dict(open=op, high=hi, low=lo, close=cl, atr=atr)
    if kind == "same_bar_stop":
        rows = [row(100,101,99,100), row(100,120,80,100), row(100,101,99,100)]
        signals = [True,False,False]
    elif kind == "gap_stop":
        rows = [row(100,101,99,100), row(100,101,99,100), row(90,91,89,90), row(100,101,99,100)]
        signals = [True,False,False,False]
    elif kind == "terminal":
        rows = [row(100,101,99,100,20), row(100,101,99,100.5,20)]
        signals = [True,False]
    elif kind == "time_exit":
        rows = [row(100,101,99,100,10) for _ in range(67)]
        signals = [True]+[False]*66
    else:
        rows = [row(100,100.001,99.999,100,.01),row(100,100.001,99.999,100,.01),
                row(.01,.02,.005,.01,.01),row(100,100.001,99.999,100,.01),
                row(100,100.001,99.999,100,.01),row(.01,.02,.005,.01,.01),
                row(100,100.001,99.999,100,.01),row(100,100.001,99.999,100,.01)]
        signals = [True,False,False,True,False,False,True,False]
    times = pd.date_range("2026-01-01 23:45",periods=len(rows),freq="15min",tz="UTC")
    if kind == "daily_and_drawdown":
        times = pd.to_datetime(["2026-01-01T00:00Z","2026-01-01T00:15Z",
                 "2026-01-01T00:30Z","2026-01-02T00:00Z","2026-01-02T00:15Z",
                 "2026-01-02T00:30Z","2026-01-03T00:00Z","2026-01-03T00:15Z"])
    result = pd.DataFrame(rows)
    result["decision_at"] = times
    return result, signals

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--oracle",required=True)
    parser.add_argument("--baseline",required=True)
    parser.add_argument("--goldens",required=True)
    parser.add_argument("--receipt",required=True)
    args = parser.parse_args()
    started = time.monotonic()
    oracle_path, baseline_path = Path(args.oracle), Path(args.baseline)
    golden = json.loads(Path(args.goldens).read_text(encoding="utf-8-sig"))
    assert golden["baseline_oracle_blob_sha"] == blob(baseline_path.read_bytes()) == "d583ed655efe64b5c0c5eb73960eb217bc7ded83"
    original = baseline_path.read_text(encoding="utf-8")
    cached = oracle_path.read_text(encoding="utf-8")
    old_anchor = '        previous = None\n\n        for idx, row in enumerate(frame.itertuples(index=False)):'
    new_anchor = '        previous = None\n        try:\n            day_keys = frame["decision_at"].dt.floor("D").array\n        except (AttributeError, KeyError, TypeError):\n            day_keys = None\n\n        for idx, row in enumerate(frame.itertuples(index=False)):'
    assert cached.count(new_anchor) == 1
    restored = cached.replace(new_anchor, old_anchor, 1).replace(
        '            d = day_keys[idx] if day_keys is not None else timestamp.floor("D")',
        '            d = timestamp.floor("D")', 1)
    assert ast.dump(ast.parse(restored),include_attributes=False) == ast.dump(ast.parse(original),include_attributes=False)
    oracle, baseline = load("cached_oracle_regression",oracle_path),load("baseline_oracle_regression",baseline_path)
    assert len(golden["cases"]) == 20 and golden["precision"] == 36
    for case in golden["cases"]:
        data, signals = frame(case["kind"])
        observed = oracle.recompute(data, signals, fee_bps=case["fee_bps"],
                                   slip_bps=case["slip_bps"], risk_variant=case["risk_variant"])
        assert normalize(observed) == case["expected"], case
    forms = [
        pd.Series(pd.date_range("2026-01-01 23:45",periods=4,freq="15min",tz="UTC")),
        pd.Series(pd.date_range("2026-01-01 23:45",periods=4,freq="15min",tz="Asia/Tehran")),
        pd.Series(pd.date_range("2026-03-08 01:45",periods=4,freq="15min",tz="America/New_York")),
        pd.Series(pd.date_range("2026-11-01 00:45",periods=12,freq="15min",tz="America/New_York")),
        pd.Series(pd.date_range("2026-01-01 23:45",periods=4,freq="15min",tz="Europe/London")),
        pd.Series(pd.date_range("2026-01-01 23:45",periods=4,freq="15min")),
    ]
    for values in forms:
        assert list(values.dt.floor("D").array) == [value.floor("D") for value in values]
    data, signals = frame("terminal")
    data["decision_at"] = pd.Series(list(data["decision_at"]),dtype=object)
    assert normalize(oracle.recompute(data,signals,fee_bps=10,slip_bps=5,risk_variant=0)) == normalize(
        baseline.recompute(data,signals,fee_bps=10,slip_bps=5,risk_variant=0))
    data, signals = frame("time_exit")
    with patch.object(pd.Timestamp,"floor",side_effect=AssertionError("canonical scalar floor called")):
        oracle.recompute(data,signals,fee_bps=10,slip_bps=5,risk_variant=0)
    receipt = {"schema":"nexus.decimal-day-cache-regression.v1","exit_code":0,
       "golden_unrounded_decimal_and_fill_path_cases":20,"timezone_and_dst_key_cases":6,
       "object_fallback_matches_baseline":True,"canonical_scalar_floor_calls":0,
       "only_day_cache_ast_changes":True,"baseline_oracle_blob_sha":blob(baseline_path.read_bytes()),
       "cached_oracle_blob_sha":blob(oracle_path.read_bytes()),
       "cached_oracle_sha256":hashlib.sha256(oracle_path.read_bytes()).hexdigest(),
       "pandas":pd.__version__,"native_windows":os.name=="nt","host":socket.gethostname(),
       "elapsed_seconds":round(time.monotonic()-started,6),"research_only":True,"live_enabled":False}
    Path(args.receipt).write_text(json.dumps(receipt,sort_keys=True,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(receipt,sort_keys=True),flush=True)

if __name__ == "__main__":
    main()
