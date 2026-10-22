"""Independent historical-only MR40 one-time partial loss trim simulator."""
from __future__ import annotations
import argparse
from collections import defaultdict
from decimal import Decimal, ROUND_DOWN
import gzip
import hashlib
import importlib.util
import json
import math
from pathlib import Path

D=Decimal
Q=D("0.00000001")
LOT=D("0.00001")
STEP=14_400_000
PARENT="f0a45bd9d2dae77dcb00df6a858660ad570393d3"
B_HASH="a458d9f83df633df8ee5cab5f2a19de41c4c79c61185b5abd258fdefa80d575a"
L_HASH="7274373a6ff9e1a060da4c18dffe9da69436345657505cd52f768f11d04ab278"

def canon(o):
    return json.dumps(o,sort_keys=True,separators=(",",":"),ensure_ascii=False,allow_nan=False).encode()
def digest(o):return hashlib.sha256(canon(o)).hexdigest()
def load_v3(source):
    path=source/"research/nexus_mr40_adaptive_sizing_v3.py"
    spec=importlib.util.spec_from_file_location("mr40_frozen_v3_partial",path)
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
    return m
def indices(rows,base,dates):
    a,b=(base.ms(x) for x in dates)
    s=next((i for i,r in enumerate(rows) if r[0]==a),len(rows))
    e=next((i for i,r in enumerate(rows) if r[0]==b),len(rows))
    if s<181 or s>=e or [r[0] for r in rows[s:e]]!=list(range(a,b,STEP)):
        raise ValueError("missing_window")
    return s,e

def simulate(rows,data,signals,case,start,end,profile,capital=10000,liquidate=True):
    if start<181 or start>=end or end>len(rows):raise ValueError("invalid_window")
    fee=D(profile["fee_bps"])/10000
    slip=D(profile["slippage_bps"])/10000
    lag=profile["lag_bars"]
    if lag not in (1,2):raise ValueError("invalid_delay")
    if case[1] is not None and not(0<float(case[1])<1 and 0<float(case[2])<1):
        raise ValueError("invalid_trim")
    cash=D(capital);held=D(0);first=None;initial_cash=None
    trimmed=False;blocked=None;attempted=False
    fills=[];positions=[];equity=[];skips=0;trim_count=0;exposure=0

    def fill(side,i,j,ref,reason,partial=None):
        nonlocal cash,held,first,initial_cash,trimmed,blocked,attempted,skips,trim_count
        ref=D(str(ref));before=cash
        price=(ref*(1+slip if side=="buy" else 1-slip)).quantize(Q)
        if side=="buy":
            budget=cash
            qty=(budget/(price*(1+fee))/LOT).to_integral_value(rounding=ROUND_DOWN)*LOT
            while qty>=LOT:
                nt=(qty*price).quantize(Q);fc=(nt*fee).quantize(Q)
                if nt+fc<=budget:break
                qty-=LOT
            if qty<LOT or qty*ref<1:
                skips+=1;blocked=data["episode"][j];return False
        elif partial is not None:
            qty=((held*D(str(partial)))/LOT).to_integral_value(rounding=ROUND_DOWN)*LOT
            remainder=held-qty
            if qty<LOT or remainder<LOT or qty*ref<1 or remainder*ref<1:
                skips+=1;return False
            nt=(qty*price).quantize(Q);fc=(nt*fee).quantize(Q)
        else:
            qty=held
            if qty<LOT or qty*ref<1:raise ValueError("dust_exit")
            nt=(qty*price).quantize(Q);fc=(nt*fee).quantize(Q)
        after=before-nt-fc if side=="buy" else before+nt-fc
        if after<0:raise ValueError("negative_cash")
        stamp=rows[i][0]+(STEP if reason=="terminal_close" else 0)
        if j is not None and (j!=i-lag or rows[j][0]+STEP>stamp):
            raise ValueError("lookahead")
        f={"side":side,"bar_index":i,"fill_ms":stamp,"signal_index":j,"reason":reason,
           "quantity":str(qty),"reference":str(ref),"price":str(price),"notional":str(nt),"fee":str(fc),
           "cash_before":str(before),"cash_after":str(after)}
        fills.append(f);cash=after
        if side=="buy":
            if held:raise ValueError("repeat_buy")
            held=qty;first=f;initial_cash=before
        else:
            held-=qty
            if partial is not None:
                trimmed=True;trim_count+=1
            else:
                if held!=0:raise ValueError("final_exit_did_not_flatten")
                positions.append({"entry":first,"exit":f,"net_pnl_usdt":float(cash-initial_cash),
                                  "holding_hours":(stamp-first["fill_ms"])/3_600_000,
                                  "trimmed":trimmed})
                first=None;initial_cash=None;trimmed=False;attempted=False
        return True

    for i in range(start,end):
        j=i-lag;desired=signals[j] if j>=0 else 0
        ep=data["episode"][j] if j>=0 else 0
        if ep and ep==blocked:desired=0
        if held and not desired:
            fill("sell",i,j,rows[i][1],"natural_exit")
        elif desired and not held:
            fill("buy",i,j,rows[i][1],"episode_entry")
        elif held and desired and case[1] is not None and not attempted:
            if j>=first["bar_index"] and D(str(data["close"][j]))<=D(first["price"])*(1-D(str(case[1]))):
                attempted=True
                fill("sell",i,j,rows[i][1],"partial_loss_trim",case[2])
        equity.append(float(cash+held*D(str(rows[i][4]))))
        exposure+=int(bool(held))
    if held and liquidate:
        fill("sell",end-1,None,rows[end-1][4],"terminal_close")
        equity[-1]=float(cash)
    replay(rows,start,end,profile,capital,fills,equity,case)
    peak=float(capital);dd=0.;under=0;longest=0
    for mark in equity:
        peak=max(peak,mark)
        dd=max(dd,1-mark/peak)
        under=under+1 if mark<peak-1e-8 else 0
        longest=max(longest,under)
    pnl=equity[-1]-capital
    if liquidate and abs(pnl-sum(p["net_pnl_usdt"] for p in positions))>1e-6:
        raise ValueError("pnl_mismatch")
    return {"metrics":{"net_pnl_usdt":pnl,"cagr_pct":100*((equity[-1]/capital)**(365.25*6/(end-start))-1),
             "max_close_drawdown_pct":100*dd,"longest_underwater_days":longest/6,
             "closed_positions":len(positions),"trims":trim_count,"fills":len(fills),
             "fees_usdt":float(sum((D(f["fee"]) for f in fills),D(0))),
             "skips":skips,"exposure_pct":100*exposure/(end-start)},
            "fills":fills,"positions":positions,"equity":equity}

def replay(rows,start,end,profile,capital,fills,curve,case):
    """Independent accounting oracle; proves fill and position invariants."""
    fee=D(profile["fee_bps"])/10000;slip=D(profile["slippage_bps"])/10000
    grouped=defaultdict(list)
    for f in fills:
        if not start<=f["bar_index"]<end:raise ValueError("outside_window")
        grouped[f["bar_index"]].append(f)
    cash=D(capital);held=D(0);entry=None;trims=0
    for i in range(start,end):
        for f in grouped[i]:
            reason=f["reason"];buy=f["side"]=="buy"
            ref=D(str(rows[i][4] if reason=="terminal_close" else rows[i][1]))
            price=(ref*(1+slip if buy else 1-slip)).quantize(Q)
            qty=D(f["quantity"]);notional=(qty*price).quantize(Q);comm=(notional*fee).quantize(Q)
            if qty<LOT or qty%LOT or qty*ref<1:raise ValueError("invalid_lot")
            if tuple(D(f[k]) for k in ("reference","price","notional","fee","cash_before"))!=(ref,price,notional,comm,cash):
                raise ValueError("ledger_drift")
            stamp=rows[i][0]+(STEP if reason=="terminal_close" else 0)
            if f["fill_ms"]!=stamp:raise ValueError("timestamp_drift")
            j=f["signal_index"]
            if j is not None and (j!=i-profile["lag_bars"] or rows[j][0]+STEP>stamp):
                raise ValueError("future_signal")
            if buy:
                if held:raise ValueError("duplicate_buy")
                budget=cash
                expected=(budget/(price*(1+fee))/LOT).to_integral_value(rounding=ROUND_DOWN)*LOT
                while expected>=LOT:
                    n=(expected*price).quantize(Q);f0=(n*fee).quantize(Q)
                    if n+f0<=budget:break
                    expected-=LOT
                if qty!=expected:raise ValueError("entry_budget_drift")
                held+=qty;entry=price;cash-=notional+comm;trims=0
            elif reason=="partial_loss_trim":
                if case[1] is None or not held or not entry or trims:raise ValueError("invalid_trim_state")
                expected=((held*D(str(case[2])))/LOT).to_integral_value(rounding=ROUND_DOWN)*LOT
                if qty!=expected or held-qty<LOT or (held-qty)*ref<1:
                    raise ValueError("partial_quantity_drift")
                # Its closed-candle trigger was available before the execution open.
                if D(str(rows[j][4]))>entry*(1-D(str(case[1]))):
                    raise ValueError("trim_rule_drift")
                held-=qty;cash+=notional-comm;trims+=1
            else:
                if qty!=held:raise ValueError("bad_final_exit")
                cash+=notional-comm;held=D(0);entry=None;trims=0
            if cash<0 or cash!=D(f["cash_after"]):raise ValueError("cash_drift")
        mark=float(cash+held*D(str(rows[i][4])))
        if abs(mark-curve[i-start])>1e-7:raise ValueError("mark_drift")

def run(source,inputs,policy,output):
    if output.exists():raise ValueError("refuse_overwrite")
    c=json.loads(policy.read_bytes())
    if c["based_on"]!=PARENT or len(c["paths"])!=6:raise ValueError("protocol_changed")
    v3=load_v3(source);v2,base,code=v3.load_engines(source)
    b=json.loads((inputs/"bybit_prepared_inputs.json").read_bytes())
    e=json.loads((inputs/"bybit_october_input_extension.json").read_bytes())
    for obj,key,expected in ((b,"input_digest","fba66860376d9ad24af7a2388e878db0dfdbae16468de9381ef6a95f95563ffe"),
                             (e,"digest","17f3101579ebd301cda074174ed4154e772d15d6b2ef2e17513d73b1dc31798c")):
        if obj[key]!=expected or digest({k:v for k,v in obj.items() if k!=key})!=expected:raise ValueError("input_drift")
    bybit=b["rows"]+e["rows"]
    raw_file=source/"docs/evidence/lbank-mr40-exact30-20261021/lbank_kline_response.json"
    raw=raw_file.read_bytes();receipt=json.loads((raw_file.parent/"source_receipt.json").read_bytes())
    if hashlib.sha256(raw).hexdigest()!=receipt["body_sha256"]:raise ValueError("lbank_changed")
    native=code["validator"](json.loads(raw,parse_float=str)["data"])
    lbank=sorted(([r[0]*1000,*r[1:]] for r in native if r[0]*1000<base.ms(c["windows"]["lbank"][1])),key=lambda x:x[0])
    if digest(bybit)!=B_HASH or digest(lbank)!=L_HASH:raise ValueError("price_hash_mismatch")
    frames={"Bybit":(bybit,v2.prepare(bybit,base,code)),
            "LBank":(lbank,v2.prepare(lbank,base,code))}
    profiles=[{"id":key,"fee_bps":val[0],"slippage_bps":val[1],"lag_bars":val[2]} for key,val in c["profiles"].items()]
    results=[];parity=[];counts=0
    output.mkdir(parents=True)
    with gzip.open(output/"ledger.jsonl.gz","wt",encoding="utf-8") as f:
        for venue,(rows,data) in frames.items():
            for window in (("train","evaluation","full") if venue=="Bybit" else ("lbank",)):
                s,en=indices(rows,base,c["windows"][window])
                signals=base.targets(rows,data,"baseline",s,en)
                for capital in c["capitals"]:
                    for profile in profiles:
                        for case in c["paths"]:
                            o=simulate(rows,data,signals,case,s,en,profile,capital)
                            key={"venue":venue,"window":window,"capital":capital,"profile":profile["id"],"case":case[0]}
                            results.append({**key,**o["metrics"]});counts+=1
                            f.write(json.dumps({"key":key,"fills":o["fills"],"positions":o["positions"],
                                "curve_sha256":digest([format(x,".6f") for x in o["equity"]])},separators=(",",":"))+"\n")
                            if case[0]=="baseline":
                                frozen={"id":"baseline_a100","entry":"baseline","amount":"1","vol_target":None,
                                        "dd_threshold":None,"dd_scale":None}
                                old=v3.simulate(rows,data,signals,frozen,s,en,profile,capital)
                                err=max(abs(a-b) for a,b in zip(old["equity"],o["equity"]))
                                left=[(x["side"],x["bar_index"],x["quantity"],x["price"],x["fee"]) for x in old["fills"]]
                                right=[(x["side"],x["bar_index"],x["quantity"],x["price"],x["fee"]) for x in o["fills"]]
                                if err>1e-7 or left!=right:raise ValueError("old_engine_baseline_parity")
                                parity.append({"key":key,"max_error":err})
                        print(json.dumps({"finished":f"{venue}/{window}/{capital}/{profile['id']}"}),flush=True)
    def get(window,name,profile):
        return next(x for x in results if x["venue"]=="Bybit" and x["window"]==window and x["capital"]==10000 and x["profile"]==profile and x["case"]==name)
    def worst(window,name):
        return max(get(window,name,p)["max_close_drawdown_pct"] for p in ("normal","stress"))
    def score(window,name):
        d=worst(window,name)
        return min(get(window,name,p)["cagr_pct"] for p in ("normal","stress"))/d if d else -math.inf
    base_n=get("train","baseline","normal");base_s=get("train","baseline","stress")
    profit=[];efficient=[]
    for name,*_ in c["paths"][1:]:
        n=get("train",name,"normal");s=get("train",name,"stress")
        if (n["net_pnl_usdt"]>=base_n["net_pnl_usdt"] and
            s["net_pnl_usdt"]>=1.05*base_s["net_pnl_usdt"] and worst("train",name)<=1.10*worst("train","baseline")):
            profit.append(name)
        if (n["cagr_pct"]>=0.75*base_n["cagr_pct"] and s["cagr_pct"]>0 and
            worst("train",name)<=0.90*worst("train","baseline") and score("train",name)>=1.10*score("train","baseline")):
            efficient.append(name)
    pick_profit=max(profit,key=lambda z:get("train",z,"stress")["net_pnl_usdt"]) if profit else "baseline"
    pick_eff=max(efficient,key=lambda z:score("train",z)) if efficient else "baseline"
    def eval_gate(name):
        if name=="baseline":return False
        return (get("evaluation",name,"normal")["net_pnl_usdt"]>=0.75*get("evaluation","baseline","normal")["net_pnl_usdt"]
                and get("evaluation",name,"stress")["net_pnl_usdt"]>=0.75*get("evaluation","baseline","stress")["net_pnl_usdt"]
                and get("evaluation",name,"normal")["max_close_drawdown_pct"]<=0.80*get("evaluation","baseline","normal")["max_close_drawdown_pct"]
                and score("evaluation",name)>=1.10*score("evaluation","baseline"))
    report={"schema":"mr40.partial-trim-results.v1","protocol_sha256":hashlib.sha256(policy.read_bytes()).hexdigest(),
        "engine_sha256":hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "price_frames":{"Bybit":B_HASH,"LBank":L_HASH},
        "selection":{"profit":pick_profit,"efficiency":pick_eff,"profit_eligible":profit,"efficiency_eligible":efficient},
        "evaluation_success":{"profit":eval_gate(pick_profit),"efficiency":eval_gate(pick_eff)},
        "runs":counts,"control_parity":parity,"rows":results,"research_only":True,"paper_changed":False}
    report["digest"]=digest(report)
    (output/"results.json").write_bytes(canon(report)+b"\n")
    print(json.dumps({"done":True,"runs":counts,"parity":len(parity),
         "selection":report["selection"],"evaluation_success":report["evaluation_success"],"digest":report["digest"]}),flush=True)
    return report
if __name__=="__main__":
    p=argparse.ArgumentParser()
    for n in ("source","inputs","policy","output"):p.add_argument("--"+n,required=True,type=Path)
    run(**vars(p.parse_args()))
