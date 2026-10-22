"""Offline synthetic QA for MR40 closed-close arming and progressive stop ratchet."""
from __future__ import annotations
import argparse
import importlib.util
import json

def simulate(m,prices,signals,case,lag=1):
    rows=[[i*m.STEP,*row,1] for i,row in enumerate(prices)]
    data={"episode":[int(bool(x)) for x in signals],"close":[r[4] for r in rows]}
    profile={"id":"normal","fee_bps":10,"slippage_bps":5,"lag_bars":lag}
    return m.simulate(rows,data,signals,case,1,len(rows),profile,10000)

def run(m):
    price=[[100,105,99,100]]*17
    signals=[0]+[1]*14+[0]*2
    base={"id":"baseline","stages":[]}
    staged={"id":"ratchet","stages":[[0.02,-0.01],[0.04,0.01],[0.06,0.03]]}
    p=[v[:] for v in price]
    p[2]=[100,105,99,103]  # first gain 3%, stop active on subsequent open
    p[3]=[103,107,100,105] # first stop (-1%) does not hit
    p[4]=[105,109,103,107] # second gain threshold now crossed
    p[5]=[107,109,102,103] # eligible previous 7% close: stop +3%, stop hit
    a=simulate(m,p,signals,staged)
    moves=a["moves"]
    assert len(moves)>=2 and all(float(y["stop_level"])>float(x["stop_level"]) for x,y in zip(moves,moves[1:]))
    assert a["metrics"]["stops"]==1
    assert a["positions"][0]["stopped"]
    assert a["positions"][0]["exit"]["reason"]=="stop_hit"
    assert not any(f["reason"]=="episode_entry" for f in a["fills"][2:]) # no reentry same signal episode
    checks=4

    g=[v[:] for v in p];g[5][0]=90 # opening below active stop: negative gap
    b=simulate(m,g,signals,staged)
    exit=b["positions"][0]["exit"]
    assert exit["reason"]=="stop_gap" and float(exit["reference"])==90
    assert float(exit["price"])<90
    checks+=2

    # Future candle high, with no corresponding previous close, must not arm.
    h=[v[:] for v in price];h[2]=[100,145,99,100]
    z=simulate(m,h,signals,staged)
    assert z["metrics"]["ratchets"]==0 and z["metrics"]["stops"]==0
    checks+=1

    # Existing strategy's queued natural exit precedes any stop decision or intrabar check.
    n=[v[:] for v in p]
    sig=[0,1,1,1,0]+[0]*12
    q=simulate(m,n,sig,staged)
    assert q["positions"][0]["exit"]["reason"]=="natural_exit"
    checks+=1

    # Delay case cannot use immediately preceding CLOSE and shows later arming.
    lag=simulate(m,p,signals,staged,lag=2)
    for ev in lag["moves"]:
        assert ev["signal_index"]==ev["bar_index"]-2
    checks+=1

    # Baseline: no added stop or trigger events.
    c=simulate(m,p,signals,base)
    assert c["metrics"]["stops"]==0 and c["metrics"]["ratchets"]==0
    checks+=1
    return checks

if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("--engine",required=True)
    a=p.parse_args()
    spec=importlib.util.spec_from_file_location("ratchet_engine",a.engine)
    mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
    print(json.dumps({"synthetic_checks":run(mod),"pass":True,"real_orders":0}))


def test_trigger_ratchet_synthetic_in_pytest():
    """Collect the real stop simulator synthetic assertions on every CI OS."""
    from pathlib import Path
    engine=Path(__file__).resolve().parents[1]/"research"/"nexus_mr40_trigger_ratchet_v1.py"
    spec=importlib.util.spec_from_file_location("ratchet_pytest_engine",engine)
    mod=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert run(mod)==10


def test_frozen_ratchet_evidence_in_pytest():
    """Check 144 results and full ledgers remain authentic and nonpromotable."""
    from pathlib import Path
    import gzip
    import hashlib
    root=Path(__file__).resolve().parents[1]
    bundle=root/"docs"/"evidence"/"mr40-trigger-ratchet-20261022"
    result=bundle/"results.json.gz"
    ledger=bundle/"ledger.jsonl.gz"
    assert hashlib.sha256(result.read_bytes()).hexdigest()=="9ee629491c1d76273a12dc72f736f211f594dd465464af9b3ca98e1f1e415664"
    assert hashlib.sha256(ledger.read_bytes()).hexdigest()=="11d951fb67afbfaf39e6cf83d5f76a6d2c277a8f972f25e4f3266e41a14e63e8"
    with gzip.open(result,"rt",encoding="utf-8") as f:
        report=json.load(f)
    logical_digest=report.pop("digest")
    canonical=json.dumps(report,sort_keys=True,separators=(",",":"),ensure_ascii=False,allow_nan=False).encode()
    assert hashlib.sha256(canonical).hexdigest()==logical_digest=="56623e1509ccc3a88a1fba1bb47d1a87a699cf953d8a661b71e49db4e18cd5b3"
    assert report["runs"]==len(report["rows"])==144
    assert len(report["control_parity"])==24
    assert report["evaluation_success"]=={"profit":False,"efficiency":False}
    assert report["paper_changed"] is False
    with gzip.open(ledger,"rt",encoding="utf-8") as f:
        assert sum(1 for _ in f)==144
