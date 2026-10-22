"""Offline future-leak checks for MR40 early failed-recovery fuse."""
from __future__ import annotations
import argparse
import importlib.util
import json
from pathlib import Path
def run(engine,source,inputs,policy):
    spec=importlib.util.spec_from_file_location("ratchet_no_future",engine)
    e=importlib.util.module_from_spec(spec);spec.loader.exec_module(e)
    c=json.loads(policy.read_bytes())
    v3=e.load_v3(source);v2,base,code=v3.load_engines(source)
    a=json.loads((inputs/"bybit_prepared_inputs.json").read_bytes())
    b=json.loads((inputs/"bybit_october_input_extension.json").read_bytes())
    rows=a["rows"]+b["rows"]
    assert e.digest(rows)==e.B_HASH
    data=v2.prepare(rows,base,code)
    s,end=e.indices(rows,base,c["windows"]["evaluation"])
    allsignals=base.targets(rows,data,"baseline",s,end)
    checked=0
    for cut in (s+400,end-80):
        pre=rows[:cut]
        p_data=v2.prepare(pre,base,code)
        p_signal=base.targets(pre,p_data,"baseline",s,cut)
        for case in c["cases"]:
            for name,vals in c["profiles"].items():
                profile={"id":name,"fee_bps":vals[0],"slippage_bps":vals[1],"lag_bars":vals[2]}
                before=e.simulate(pre,p_data,p_signal,case,s,cut,profile,500,False)
                after=e.simulate(rows,data,allsignals,case,s,end,profile,500,False)
                expected=[f for f in after["fills"] if f["bar_index"]<cut]
                expected_moves=[m for m in after["assessments"] if m["bar_index"]<cut]
                if before["fills"]!=expected:raise ValueError("future_dependent_fills")
                if before["assessments"]!=expected_moves:raise ValueError("future_dependent_assessment")
                if before["equity"]!=after["equity"][:cut-s]:raise ValueError("future_dependent_curve")
                checked+=1
    print(json.dumps({"prefix_checks":checked,"success":True,"new_market_downloads":0,"paper_unchanged":True}))
if __name__=="__main__":
    p=argparse.ArgumentParser()
    for name in ("engine","source","inputs","policy"):p.add_argument("--"+name,required=True,type=Path)
    run(**vars(p.parse_args()))
