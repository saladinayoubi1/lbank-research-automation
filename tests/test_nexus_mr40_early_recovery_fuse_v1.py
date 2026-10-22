"""MR40 recovery-fuse synthetic checks: no lookahead and proper one-time exit."""
from __future__ import annotations
import argparse
import importlib.util
import json
from pathlib import Path

def exercise(m):
    rows=[[i*m.STEP,100,120,80,99,1] for i in range(20)]
    signals=[0]+[1]*14+[0]*5
    data={"close":[x[4] for x in rows],"episode":[1 if z else 0 for z in signals]}
    profile={"id":"normal","fee_bps":10,"slippage_bps":5,"lag_bars":1}
    c={"id":"fuse3_be","observe_bars":3,"minimum_favorable_close":0}
    res=m.simulate(rows,data,signals,c,1,18,profile,10000)
    fail=[x for x in res["fills"] if x["reason"]=="failed_recovery"]
    assert len(fail)==1 and fail[0]["bar_index"]==5 and fail[0]["signal_index"]==4
    assert res["metrics"]["failed_assessments"]==1 and res["metrics"]["approved_assessments"]==0
    assert len([x for x in res["fills"] if x["side"]=="buy"])==1
    checks=3

    # HIGH spike is irrelevant; entry CLOSE confirmation alone decides.
    rows[3][2]=150
    nohigh=m.simulate(rows,data,signals,c,1,18,profile,10000)
    assert nohigh["metrics"]["failed_recovery_exits"]==1
    checks+=1

    # One actually completed rebound CLOSE removes fuse even if future bars fall.
    data["close"][3]=101;rows[3][4]=101
    approved=m.simulate(rows,data,signals,c,1,18,profile,10000)
    assert approved["metrics"]["failed_recovery_exits"]==0
    assert approved["metrics"]["approved_assessments"]==1
    checks+=2

    # Time-based check MUST wait until the nth fully completed post-entry bar.
    data["close"][3]=99;rows[3][4]=99
    late={"id":"fuse6_be","observe_bars":6,"minimum_favorable_close":0}
    wait=m.simulate(rows,data,signals,late,1,18,profile,10000)
    assert wait["metrics"]["failed_recovery_exits"]==1
    assert next(x for x in wait["fills"] if x["reason"]=="failed_recovery")["bar_index"]==8
    checks+=1

    # No guaranteed exit price; adverse Open gap fills at new Open less slippage.
    rows[5][1]=80
    gap=m.simulate(rows,data,signals,c,1,18,profile,10000)
    x=next(x for x in gap["fills"] if x["reason"]=="failed_recovery")
    assert x["reference"]=="80" and float(x["price"])<80
    checks+=1

    # Natural exit scheduled on same OPEN always wins.
    rows[5][1]=100
    exit_signals=[0,1,1,1,0]+[0]*15
    out=m.simulate(rows,data,exit_signals,c,1,18,profile,10000)
    assert out["metrics"]["failed_recovery_exits"]==0
    assert out["positions"][0]["exit"]["reason"]=="natural_exit"
    checks+=2

    # Additional 4h signal delay cannot read more recent bars.
    profile2={**profile,"lag_bars":2}
    delayed=m.simulate(rows,data,signals,c,1,18,profile2,10000)
    fx=next(x for x in delayed["fills"] if x["reason"]=="failed_recovery")
    assert fx["signal_index"]==fx["bar_index"]-2
    assert all(r["signal_index"]==r["bar_index"]-2 for r in delayed["assessments"])
    checks+=2

    # Original baseline does no synthetic fuse, needs exact natural exit.
    base=m.simulate(rows,data,signals,{"id":"baseline","observe_bars":None,"minimum_favorable_close":0},1,18,profile,10000)
    assert base["metrics"]["failed_recovery_exits"]==0 and base["metrics"]["approved_assessments"]==0
    checks+=1
    return checks

def test_fuse_synthetic():
    path=Path(__file__).resolve().parents[1]/"research"/"nexus_mr40_early_recovery_fuse_v1.py"
    spec=importlib.util.spec_from_file_location("mr40_fuse",path)
    eng=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(eng)
    assert exercise(eng)==13

if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("--engine",type=Path,required=True)
    a=p.parse_args()
    spec=importlib.util.spec_from_file_location("fuse_cli",a.engine)
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
    print(json.dumps({"synthetic_checks":exercise(m),"pass":True}))
