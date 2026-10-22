"""Preregistered MR40 entry quality vetoes. Offline and historical-only."""
from __future__ import annotations
import argparse
from collections import defaultdict
from decimal import Decimal
import gzip
import hashlib
import importlib.util
import json
import math
from pathlib import Path

SOURCE_PARENT="22786d64081749d88183bc1c4c43536d443b60ba"
BYBIT_SHA="a458d9f83df633df8ee5cab5f2a19de41c4c79c61185b5abd258fdefa80d575a"
LBANK_SHA="7274373a6ff9e1a060da4c18dffe9da69436345657505cd52f768f11d04ab278"
BASECASE={"id":"baseline","initial_stop":None,"arm2":False}

def canon(x):return json.dumps(x,sort_keys=True,ensure_ascii=False,separators=(",",":"),allow_nan=False).encode()
def digest(x):return hashlib.sha256(canon(x)).hexdigest()
def load_entry_stop(source):
    file=source/"research/nexus_mr40_entry_protection_v1.py"
    spec=importlib.util.spec_from_file_location("mr40_entry_stop_reference",file)
    mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
    return mod

def get_ohlc(rows,j):
    return tuple(Decimal(str(v)) for v in rows[j][1:5])

def accept(rows,j,case):
    rule=case["id"]
    if rule=="baseline":return True
    if j<181:raise ValueError("insufficient_history")
    op,hi,lo,cl=get_ohlc(rows,j)
    cl_prev=Decimal(str(rows[j-1][4]))
    def green():return cl>op and cl>cl_prev
    def quiet():
        tr=max(hi-lo,abs(hi-cl_prev),abs(lo-cl_prev))
        prev=[]
        for k in range(j-14,j):
            o,h,l,c=get_ohlc(rows,k)
            cp=Decimal(str(rows[k-1][4]))
            prev.append(max(h-l,abs(h-cp),abs(l-cp)))
        return tr*Decimal(14)<=Decimal("1.75")*sum(prev)
    if rule=="green_reversal":return green()
    if rule=="short_drift_6":return cl>=Decimal(str(rows[j-6][4]))
    if rule=="range_quiet_14":return quiet()
    if rule=="trend_10d_60":return cl>=Decimal(str(rows[j-60][4]))
    if rule=="reversal_and_quiet":return green() and quiet()
    raise ValueError("unregistered_filter")

def filtered_signals(rows,signals,s,en,case):
    """One first fully closed signal per episode. Veto whole episode, not later rescue."""
    out=list(signals);decisions=[]
    j=s
    while j<en:
        if not signals[j]:
            j+=1;continue
        if j>0 and signals[j-1]:
            raise ValueError("window_begins_mid_positive_episode")
        first=j
        while j<en and signals[j]:j+=1
        allowed=accept(rows,first,case)
        if not allowed:
            for z in range(first,j):out[z]=0
        decisions.append({"signal_index":first,"signal_ms":rows[first][0],"allowed":allowed,
                          "episode_last_index":j-1})
    return out,decisions

def assess_retained(ref_positions,decisions):
    lookup={x["signal_index"]:x for x in decisions}
    losses_removed=wins_removed=0;losses_total=wins_total=0
    kept_win_sum=total_win_sum=removed_loss_sum=0.
    for p in ref_positions:
        sig=p["entry"]["signal_index"]
        if sig not in lookup:raise ValueError("missing_entry_decision")
        pnl=p["net_pnl_usdt"]
        if pnl>0:
            wins_total+=1;total_win_sum+=pnl
            if lookup[sig]["allowed"]:kept_win_sum+=pnl
            else:wins_removed+=1
        elif pnl<0:
            losses_total+=1
            if not lookup[sig]["allowed"]:
                losses_removed+=1;removed_loss_sum+=pnl
    return {"baseline_winners":wins_total,"baseline_losers":losses_total,
       "winners_removed":wins_removed,"losers_removed":losses_removed,
       "baseline_winner_pnl_sum":total_win_sum,"winner_pnl_kept_from_baseline":kept_win_sum,
       "removed_loser_pnl_sum":removed_loss_sum,
       "winner_count_retained_fraction":(wins_total-wins_removed)/wins_total if wins_total else 1.,
       "winner_pnl_retained_fraction":kept_win_sum/total_win_sum if total_win_sum else 1.,
       "entries_total":len(decisions),"entries_accepted":sum(x["allowed"] for x in decisions)}

def execute(source,inputs,policy,output):
    if output.exists():raise ValueError("refuse_overwrite")
    cfg=json.loads(policy.read_bytes())
    if cfg["based_on"]!=SOURCE_PARENT or len(cfg["candidate_filters"])!=6:raise ValueError("protocol_drift")
    if [x["id"] for x in cfg["candidate_filters"]]!=["baseline","green_reversal","short_drift_6","range_quiet_14","trend_10d_60","reversal_and_quiet"]:raise ValueError("filter_drift")
    original=load_entry_stop(source)
    v3=original.load_v3(source);v2,base,code=v3.load_engines(source)
    b=json.loads((inputs/"bybit_prepared_inputs.json").read_bytes())
    e=json.loads((inputs/"bybit_october_input_extension.json").read_bytes())
    for obj,k,sha in ((b,"input_digest","fba66860376d9ad24af7a2388e878db0dfdbae16468de9381ef6a95f95563ffe"),
                      (e,"digest","17f3101579ebd301cda074174ed4154e772d15d6b2ef2e17513d73b1dc31798c")):
        if obj[k]!=sha or digest({key:val for key,val in obj.items() if key!=k})!=sha:raise ValueError("immutable_input_changed")
    bybit=b["rows"]+e["rows"]
    raw_path=source/"docs/evidence/lbank-mr40-exact30-20261021/lbank_kline_response.json"
    raw=raw_path.read_bytes()
    receipt=json.loads((raw_path.parent/"source_receipt.json").read_bytes())
    if hashlib.sha256(raw).hexdigest()!=receipt["body_sha256"]:raise ValueError("lbank_archive_drift")
    native=code["validator"](json.loads(raw,parse_float=str)["data"])
    lbank=sorted(([r[0]*1000,*r[1:]] for r in native if r[0]*1000<base.ms(cfg["validation"]["windows"]["lbank"][1])),key=lambda r:r[0])
    if digest(bybit)!=BYBIT_SHA or digest(lbank)!=LBANK_SHA:raise ValueError("market_digest_drift")
    frames={"Bybit":(bybit,v2.prepare(bybit,base,code)),
            "LBank":(lbank,v2.prepare(lbank,base,code))}
    cases=cfg["candidate_filters"]
    results=[];parity=[];observations=[];count=0
    output.mkdir(parents=True)
    with gzip.open(output/"ledger.jsonl.gz","wt",encoding="utf-8") as fh:
        for venue,(rows,data) in frames.items():
            windows=("train","evaluation","full") if venue=="Bybit" else ("lbank",)
            for window in windows:
                s,en=original.indices(rows,base,cfg["validation"]["windows"][window])
                full_signals=base.targets(rows,data,"baseline",s,en)
                selections={case["id"]:filtered_signals(rows,full_signals,s,en,case) for case in cases}
                for capital in cfg["validation"]["capitals"]:
                    for pname,values in cfg["validation"]["profiles"].items():
                        prof={"id":pname,"fee_bps":values[0],"slippage_bps":values[1],"lag_bars":values[2]}
                        baseout=original.simulate(rows,data,full_signals,BASECASE,s,en,prof,capital)
                        # Same pinned old engine, no strategy copy. Also independently compare legacy baseline.
                        if pname in ("normal","stress","lag"):
                            frozen={"id":"baseline_a100","entry":"baseline","amount":"1","vol_target":None,"dd_threshold":None,"dd_scale":None}
                            prev=v3.simulate(rows,data,full_signals,frozen,s,en,prof,capital)
                            lhs=[(f["side"],f["bar_index"],f["quantity"],f["price"],f["fee"]) for f in prev["fills"]]
                            rhs=[(f["side"],f["bar_index"],f["quantity"],f["price"],f["fee"]) for f in baseout["fills"]]
                            if lhs!=rhs or max(abs(a-b) for a,b in zip(prev["equity"],baseout["equity"]))>1e-7:
                                raise ValueError("legacy_baseline_parity")
                            parity.append({"venue":venue,"window":window,"capital":capital,"profile":pname})
                        for case in cases:
                            signals,decisions=selections[case["id"]]
                            sim=baseout if case["id"]=="baseline" else original.simulate(rows,data,signals,BASECASE,s,en,prof,capital)
                            keep=assess_retained(baseout["positions"],decisions)
                            key={"venue":venue,"window":window,"capital":capital,"profile":pname,"case":case["id"]}
                            results.append({**key,**sim["metrics"],**keep});count+=1
                            fh.write(json.dumps({"key":key,"positions":sim["positions"],"fills":sim["fills"],
                              "decisions":decisions,"equity_digest":digest([format(v,".6f") for v in sim["equity"]])},
                              separators=(",",":"),ensure_ascii=False)+"\n")
                        print(json.dumps({"done":venue+"/"+window+"/"+str(capital)+"/"+pname}),flush=True)
    def row(window,case,profile):
        return next(x for x in results if x["venue"]=="Bybit" and x["window"]==window and x["capital"]==10000 and x["case"]==case and x["profile"]==profile)
    def qualified(case):
        n=row("train",case,"normal");st=row("train",case,"stress")
        bn=row("train","baseline","normal");bs=row("train","baseline","stress")
        return n["net_pnl_usdt"]>=bn["net_pnl_usdt"] and st["net_pnl_usdt"]>=1.05*bs["net_pnl_usdt"] and n["max_close_drawdown_pct"]<=.9*bn["max_close_drawdown_pct"] and n["winner_count_retained_fraction"]>=.6 and n["winner_pnl_retained_fraction"]>=.7 and n["closed_positions"]>=.4*bn["closed_positions"]
    possible=[c["id"] for c in cases[1:] if qualified(c["id"])]
    chosen=max(possible,key=lambda name:row("train",name,"stress")["net_pnl_usdt"]) if possible else "baseline"
    def eval_gate(case):
        if case=="baseline":return False
        n=row("evaluation",case,"normal");st=row("evaluation",case,"stress")
        bn=row("evaluation","baseline","normal");bs=row("evaluation","baseline","stress")
        return (n["net_pnl_usdt"]>=bn["net_pnl_usdt"] and st["net_pnl_usdt"]>=bs["net_pnl_usdt"] and n["max_close_drawdown_pct"]<=.9*bn["max_close_drawdown_pct"] and n["winner_count_retained_fraction"]>=.6 and n["winner_pnl_retained_fraction"]>=.7)
    report={"schema":"mr40.entry-quality.results.v1","protocol_sha256":hashlib.sha256(policy.read_bytes()).hexdigest(),
      "historically_seen":True,"future_blind":False,"paper_changed":False,
      "rows":results,"runs":count,"base_parity":parity,
      "selection":{"qualified_train":possible,"chosen":chosen,"evaluation_pass":eval_gate(chosen)},
      "candidate_evaluation_gates":{c["id"]:eval_gate(c["id"]) for c in cases[1:]}}
    report["digest"]=digest(report)
    (output/"results.json").write_bytes(canon(report)+b"\n")
    print(json.dumps({"done":True,"runs":count,"baseline_parity":len(parity),
        "selection":report["selection"],"digest":report["digest"]}),flush=True)
    return report

if __name__=="__main__":
    p=argparse.ArgumentParser()
    for name in ("source","inputs","policy","output"):
        p.add_argument("--"+name,required=True,type=Path)
    execute(**vars(p.parse_args()))
