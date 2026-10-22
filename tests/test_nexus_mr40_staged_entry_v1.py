"""Targeted QA for the new MR40 staged-entry simulator; research only."""
import argparse, hashlib, importlib.util, json
from decimal import Decimal
from pathlib import Path

def load(p):
    spec=importlib.util.spec_from_file_location("mr40_stage",p)
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
    return m

def synthetic(stage):
    N=25
    closes=[99.]*N
    closes[2]=98.;closes[3]=99.;closes[4]=101.;closes[5]=101.5
    rows=[[i*stage.STEP,100.,110.,90.,closes[i],1] for i in range(N)]
    data={"close":closes,"episode":[0]*N,"z":[-2.]*N}
    signal=[0]*N
    for j in range(1,15):
        signal[j]=1;data["episode"][j]=1
    return rows,data,signal

def variant(first="0.5",limit=6,condition="rebound"):
    return {"id":"synthetic","first":first,"max_decision_bars":limit,"condition":condition}

def run_checks(stage):
    profile={"id":"normal","fee_bps":10,"slippage_bps":5,"lag_bars":1}
    rows,data,signal=synthetic(stage)
    result=stage.simulate(rows,data,signal,variant(),1,20,profile,10000)
    buys=[x for x in result["fills"] if x["side"]=="buy"]
    assert len(buys)==2 and buys[0]["reason"]=="first" and buys[1]["reason"]=="recovery_add"
    assert buys[1]["signal_index"]==4 and buys[1]["bar_index"]==5
    assert result["metrics"]["adds"]==1 and len(result["positions"])==1
    assert Decimal(buys[0]["quantity"])+Decimal(buys[1]["quantity"])>Decimal(0)
    # A better close may be followed by an adverse execution-open gap: no lookahead or promised fill price.
    rows[5][1]=105.
    gap=stage.simulate(rows,data,signal,variant(),1,20,profile,10000)
    gapadd=[x for x in gap["fills"] if x["reason"]=="recovery_add"]
    assert len(gapadd)==1 and Decimal(gapadd[0]["reference"])==Decimal(105)
    # Recovery only beyond the three-bar deadline must not permit an add.
    rows,data,signal=synthetic(stage)
    data["close"][:]=[98.]*len(rows)
    for k in range(1,len(rows)):rows[k][4]=98.
    data["close"][9]=102.;rows[9][4]=102.
    late=stage.simulate(rows,data,signal,variant(limit=3),1,20,profile,10000)
    assert late["metrics"]["adds"]==0
    # Never add into a decision-close below the initial executed reference.
    rows,data,signal=synthetic(stage)
    for k in range(3,14):
        data["close"][k]=99. if k%2 else 98.
        rows[k][4]=data["close"][k]
    lower=stage.simulate(rows,data,signal,variant(),1,20,profile,10000)
    assert lower["metrics"]["adds"]==0
    # Increased latency must place the add strictly after its closed decision candle.
    rows,data,signal=synthetic(stage)
    lag={"id":"extra_4h_delay","fee_bps":10,"slippage_bps":5,"lag_bars":2}
    deferred=stage.simulate(rows,data,signal,variant(),1,20,lag,10000)
    assert deferred["metrics"]["adds"]==1
    for f in deferred["fills"]:
        if f["signal_index"] is not None:
            assert f["signal_index"]==f["bar_index"]-2
            assert rows[f["signal_index"]][0]+stage.STEP<=f["fill_ms"]
    return 5

def prefix(stage,source,inputs,policy):
    v3=stage.load_v3(source);v2,base,code=v3.load_engines(source)
    b=json.loads((inputs/"bybit_prepared_inputs.json").read_bytes())
    e=json.loads((inputs/"bybit_october_input_extension.json").read_bytes())
    rows=b["rows"]+e["rows"]
    assert stage.hashobj(rows)==stage.B_HASH
    cfg=json.loads(policy.read_bytes())
    start,end=stage.indices(rows,base,cfg["evaluation"])
    checks=0
    for cut in (start+350,end-60):
        trunc=rows[:cut]
        short=v2.prepare(trunc,base,code)
        full=v2.prepare(rows,base,code)
        sfull=base.targets(rows,full,"baseline",start,end)
        ssh=base.targets(trunc,short,"baseline",start,cut)
        for case in cfg["cases"]:
            for profile in cfg["profiles"]:
                a=stage.simulate(rows,full,sfull,case,start,end,profile,500,liquidate=False)
                z=stage.simulate(trunc,short,ssh,case,start,cut,profile,500,liquidate=False)
                if z["fills"]!=[f for f in a["fills"] if f["bar_index"]<cut]:
                    raise ValueError("prefix_fill_disagreement")
                if z["equity"]!=a["equity"][:cut-start]:
                    raise ValueError("prefix_equity_disagreement")
                checks+=1
    return checks

if __name__=="__main__":
    p=argparse.ArgumentParser()
    for name in ("engine","source","inputs","policy"):p.add_argument("--"+name,required=True,type=Path)
    a=p.parse_args();stage=load(a.engine)
    unit=run_checks(stage);checks=prefix(stage,a.source,a.inputs,a.policy)
    print(json.dumps({"synthetic_checks":unit,"prefix_checks":checks,"status":"PASS","offline":True}))
