"""Offline synthetic tests for the one-time partial-trim research module."""
import argparse
import importlib.util
import json

def main(engine):
    spec=importlib.util.spec_from_file_location("partial",engine)
    m=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    rows=[[i*m.STEP,100.,110.,90.,94. if i>=2 else 100.,1] for i in range(30)]
    signal=[int(1<=i<20) for i in range(30)]
    data={"close":[r[4] for r in rows],"episode":[1 if x else 0 for x in signal]}
    profile={"id":"normal","fee_bps":10,"slippage_bps":5,"lag_bars":1}
    case=["trim50at5",0.05,0.50]
    a=m.simulate(rows,data,signal,case,1,25,profile,10000)
    assert a["metrics"]["trims"]==1
    f=next(x for x in a["fills"] if x["reason"]=="partial_loss_trim")
    assert f["bar_index"]==3 and f["signal_index"]==2
    rows[3][1]=80.
    b=m.simulate(rows,data,signal,case,1,25,profile,10000)
    assert float(next(x for x in b["fills"] if x["reason"]=="partial_loss_trim")["price"])<94
    signal[2:]=[0]*(len(signal)-2)
    c=m.simulate(rows,data,signal,case,1,25,profile,10000)
    assert c["metrics"]["trims"]==0
    print(json.dumps({"synthetic_checks":3,"success":True}))

if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--engine",required=True)
    main(p.parse_args().engine)
