"""Independent historical prefix invariance for frozen MR40 partial-trim paths."""
import argparse, importlib.util, json
from pathlib import Path
def main(args):
    spec=importlib.util.spec_from_file_location("trim_engine",args.engine)
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
    c=json.loads(args.policy.read_bytes())
    v3=m.load_v3(args.source);v2,base,code=v3.load_engines(args.source)
    b=json.loads((args.inputs/"bybit_prepared_inputs.json").read_bytes())
    ex=json.loads((args.inputs/"bybit_october_input_extension.json").read_bytes())
    rows=b["rows"]+ex["rows"]
    assert m.digest(rows)==m.B_HASH
    data=v2.prepare(rows,base,code)
    start,end=m.indices(rows,base,c["windows"]["evaluation"])
    complete=base.targets(rows,data,"baseline",start,end)
    checked=0
    for cut in (start+400,end-80):
        short=rows[:cut]
        past=v2.prepare(short,base,code)
        old=base.targets(short,past,"baseline",start,cut)
        for case in c["paths"]:
            for name,profile in c["profiles"].items():
                pr={"id":name,"fee_bps":profile[0],"slippage_bps":profile[1],"lag_bars":profile[2]}
                a=m.simulate(rows,data,complete,case,start,end,pr,500,False)
                b=m.simulate(short,past,old,case,start,cut,pr,500,False)
                if b["fills"]!=[x for x in a["fills"] if x["bar_index"]<cut]:
                    raise AssertionError("future_dependent_fills")
                if b["equity"]!=a["equity"][:cut-start]:
                    raise AssertionError("future_dependent_marks")
                checked+=1
    print(json.dumps({"prefix_checks":checked,"passed":True,"live":False,"new_downloads":0}))
if __name__=="__main__":
    p=argparse.ArgumentParser()
    for n in ("engine","source","inputs","policy"):p.add_argument("--"+n,type=Path,required=True)
    main(p.parse_args())
