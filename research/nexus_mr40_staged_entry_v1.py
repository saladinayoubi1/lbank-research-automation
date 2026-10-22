"""MR40 staged-entry follow-up; offline, frozen inputs, research only."""
from __future__ import annotations
import argparse, gzip, hashlib, importlib.util, json, math
from decimal import Decimal, ROUND_DOWN
from pathlib import Path

D=Decimal
Q=D("0.00000001")
LOT=D("0.00001")
STEP=14_400_000
PARENT_SHA="571a75624abe070c4ea7adc3b2dea78da86ea03a"
B_HASH="a458d9f83df633df8ee5cab5f2a19de41c4c79c61185b5abd258fdefa80d575a"
L_HASH="7274373a6ff9e1a060da4c18dffe9da69436345657505cd52f768f11d04ab278"

def canon(x):
    return json.dumps(x,sort_keys=True,separators=(",",":"),ensure_ascii=False,allow_nan=False).encode()
def hashobj(x):
    return hashlib.sha256(canon(x)).hexdigest()
def load_v3(source):
    p=source/"research/nexus_mr40_adaptive_sizing_v3.py"
    spec=importlib.util.spec_from_file_location("frozen_mr40_v3",p)
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
    return m
def indices(rows,base,dates):
    a=base.ms(dates[0]);b=base.ms(dates[1])
    s=next((i for i,r in enumerate(rows) if r[0]==a),len(rows))
    e=next((i for i,r in enumerate(rows) if r[0]==b),len(rows))
    if s<181 or s>=e or [r[0] for r in rows[s:e]]!=list(range(a,b,STEP)):
        raise ValueError("incomplete_window")
    return s,e

def simulate(rows,data,signal,case,start,end,profile,capital,liquidate=True):
    fee=D(profile["fee_bps"])/10000;slip=D(profile["slippage_bps"])/10000
    lag=profile["lag_bars"]
    cash=D(capital);held=D(0);first=None;start_cash=None;first_j=None
    first_episode=None;added=False;blocked=None;entry_count=0;add_count=0
    fills=[];positions=[];equity=[];exposure=0;skips=0

    def fill(side,i,j,reference,reason,budget_fraction=None):
        nonlocal cash,held,first,start_cash,first_j,first_episode,added,blocked,skips,entry_count,add_count
        before=cash;reference=D(str(reference))
        price=(reference*(1+slip if side=="buy" else 1-slip)).quantize(Q)
        if side=="buy":
            budget=cash*D(str(budget_fraction))
            units=(budget/(price*(1+fee))/LOT).to_integral_value(rounding=ROUND_DOWN)*LOT
            while units>=LOT:
                notional=(units*price).quantize(Q);commission=(notional*fee).quantize(Q)
                if notional+commission<=budget:break
                units-=LOT
            if units<LOT or units*reference<1:
                skips+=1
                if reason=="first":blocked=data["episode"][j]
                return False
        else:
            units=held
            if units<LOT or units*reference<1:raise ValueError("exit_below_minimum")
            notional=(units*price).quantize(Q);commission=(notional*fee).quantize(Q)
        after=before-notional-commission if side=="buy" else before+notional-commission
        if after<0:raise ValueError("negative_cash")
        stamp=rows[i][0]+(STEP if reason=="terminal_close" else 0)
        if j is not None and (j!=i-lag or rows[j][0]+STEP>stamp):
            raise ValueError("future_information")
        f={"side":side,"bar_index":i,"signal_index":j,"fill_ms":stamp,"reason":reason,
           "quantity":str(units),"reference":str(reference),"price":str(price),
           "notional":str(notional),"fee":str(commission),
           "cash_before":str(before),"cash_after":str(after)}
        fills.append(f);cash=after
        if side=="buy":
            held+=units
            if reason=="first":
                first=f;start_cash=before;first_j=j;first_episode=data["episode"][j]
                added=False;entry_count+=1
            else:
                added=True;add_count+=1
        else:
            pnl=float(cash-start_cash)
            positions.append({"first_fill":first,"exit":f,"pnl":pnl,
                              "hours":(stamp-first["fill_ms"])/3_600_000})
            held=D(0);first=None;start_cash=None;first_j=None
            first_episode=None;added=False
        return True

    for i in range(start,end):
        j=i-lag;desired=signal[j] if j>=0 else 0
        ep=data["episode"][j] if j>=0 else 0
        if desired and ep==blocked:desired=0
        if held and not desired:
            fill("sell",i,j,rows[i][1],"natural_exit")
        elif desired and not held:
            fill("buy",i,j,rows[i][1],"first",case["first"])
        elif held and desired and not added and case["condition"]!="none":
            elapsed=j-first_j
            if ep==first_episode and 1<=elapsed<=case["max_decision_bars"]:
                rebound=(data["close"][j]>data["close"][j-1]
                         and D(str(data["close"][j]))>=D(first["reference"]))
                confirm=(rebound and (case["condition"]=="rebound" or
                                     (data["z"][j] is not None and data["z"][j]>=-1.5)))
                if confirm:fill("buy",i,j,rows[i][1],"recovery_add","1")
        equity.append(float(cash+held*D(str(rows[i][4]))))
        exposure+=int(bool(held))
    if held and liquidate:
        fill("sell",end-1,None,rows[end-1][4],"terminal_close")
        equity[-1]=float(cash)
    verify(rows,profile,capital,start,end,fills,equity)
    peak=float(capital);dd=0.;under=0;maxunder=0
    for x in equity:
        peak=max(peak,x);dd=max(dd,1-x/peak)
        under=under+1 if x<peak-1e-8 else 0
        maxunder=max(maxunder,under)
    net=equity[-1]-capital
    if liquidate and abs(net-sum(p["pnl"] for p in positions))>1e-6:
        raise ValueError("position_reconciliation")
    return {"metrics":{"net_pnl_usdt":net,"cagr_pct":100*((equity[-1]/capital)**(365.25*6/(end-start))-1),
           "max_close_drawdown_pct":100*dd,"longest_underwater_days":maxunder/6,
           "closed_positions":len(positions),"first_entries":entry_count,"adds":add_count,
           "total_fills":len(fills),"fees_usdt":float(sum((D(f["fee"]) for f in fills),D(0))),
           "exposure_bar_pct":100*exposure/(end-start),"entry_skips":skips},
           "fills":fills,"positions":positions,"equity":equity}

def verify(rows,profile,capital,start,end,fills,equity):
    """Independent Decimal replay of cash, holdings, fill price/fees, and close equity."""
    fee=D(profile["fee_bps"])/10000;slip=D(profile["slippage_bps"])/10000
    d={};cash=D(capital);held=D(0)
    for f in fills:d.setdefault(f["bar_index"],[]).append(f)
    for i in range(start,end):
        for f in d.get(i,[]):
            side=f["side"];reference=D(str(rows[i][4] if f["reason"]=="terminal_close" else rows[i][1]))
            price=(reference*(1+slip if side=="buy" else 1-slip)).quantize(Q)
            units=D(f["quantity"]);notional=(units*price).quantize(Q)
            commission=(notional*fee).quantize(Q)
            if units<LOT or units%LOT!=0 or units*reference<1:raise ValueError("bad_lot")
            if (reference,price,notional,commission,cash)!=tuple(D(f[k]) for k in ("reference","price","notional","fee","cash_before")):
                raise ValueError("ledger_quote_drift")
            stamp=rows[i][0]+(STEP if f["reason"]=="terminal_close" else 0)
            if f["fill_ms"]!=stamp:raise ValueError("fill_time_drift")
            j=f["signal_index"]
            if j is not None and (j!=i-profile["lag_bars"] or rows[j][0]+STEP>stamp):
                raise ValueError("future_signal")
            if side=="buy":
                cash-=notional+commission;held+=units
            else:
                if units!=held:raise ValueError("wrong_exit_amount")
                cash+=notional-commission;held=D(0)
            if cash<0 or cash!=D(f["cash_after"]):raise ValueError("ledger_cash_drift")
        marked=float(cash+held*D(str(rows[i][4])))
        if abs(marked-equity[i-start])>1e-7:raise ValueError("equity_drift")

def main(source,inputs,policy,output):
    if output.exists():raise ValueError("refuse_overwrite")
    cfg=json.loads(policy.read_bytes())
    if cfg["parent_commit"]!=PARENT_SHA or len(cfg["cases"])!=7:
        raise ValueError("protocol_drift")
    v3=load_v3(source);v2,base,code=v3.load_engines(source)
    b=json.loads((inputs/"bybit_prepared_inputs.json").read_bytes())
    e=json.loads((inputs/"bybit_october_input_extension.json").read_bytes())
    for obj,key,expected in ((b,"input_digest","fba66860376d9ad24af7a2388e878db0dfdbae16468de9381ef6a95f95563ffe"),
                             (e,"digest","17f3101579ebd301cda074174ed4154e772d15d6b2ef2e17513d73b1dc31798c")):
        if obj[key]!=expected or hashobj({k:v for k,v in obj.items() if k!=key})!=expected:
            raise ValueError("input_drift")
    bybit=b["rows"]+e["rows"]
    raw_path=source/"docs/evidence/lbank-mr40-exact30-20261021/lbank_kline_response.json"
    receipt=json.loads((raw_path.parent/"source_receipt.json").read_bytes())
    raw=raw_path.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=receipt["body_sha256"]:raise ValueError("lbank_input_drift")
    native=code["validator"](json.loads(raw,parse_float=str)["data"])
    lbank=sorted(([r[0]*1000,*r[1:]] for r in native if r[0]*1000<base.ms(cfg["lbank30"][1])),key=lambda r:r[0])
    if hashobj(bybit)!=B_HASH or hashobj(lbank)!=L_HASH:raise ValueError("frame_hash_mismatch")
    frames={"Bybit":(bybit,v2.prepare(bybit,base,code)),
            "LBank":(lbank,v2.prepare(lbank,base,code))}
    output.mkdir(parents=True)
    allrows=[];checks=[];records=0
    basename={"id":"baseline_a100","entry":"baseline","amount":"1","vol_target":None,"dd_threshold":None,"dd_scale":None}
    controlname={**basename,"id":"baseline_a50","amount":"0.5"}
    with gzip.open(output/"ledger.jsonl.gz","wt",encoding="utf-8") as stream:
        for venue,(rows,data) in frames.items():
            for label in (("training","evaluation","full") if venue=="Bybit" else ("lbank30",)):
                st,en=indices(rows,base,cfg[label])
                signal=base.targets(rows,data,"baseline",st,en)
                caps=(10000,) if venue=="Bybit" else (10000,500)
                for capital in caps:
                    for profile in cfg["profiles"]:
                        for case in cfg["cases"]:
                            out=simulate(rows,data,signal,case,st,en,profile,capital)
                            k={"venue":venue,"window":label,"capital":capital,"profile":profile["id"],"case":case["id"]}
                            allrows.append({**k,**out["metrics"]});records+=1
                            stream.write(json.dumps({"key":k,"fills":out["fills"],"positions":out["positions"],
                                                    "equity_digest":hashobj([format(x,".6f") for x in out["equity"]])},separators=(",",":"))+"\n")
                            if case["id"] in ("baseline_a100","control_a50"):
                                reference=v3.simulate(rows,data,signal,basename if case["id"]=="baseline_a100" else controlname,
                                                      st,en,profile,capital)
                                maximum=max(abs(x-y) for x,y in zip(out["equity"],reference["equity"]))
                                a=[(f["side"],f["bar_index"],f["quantity"],f["price"],f["fee"]) for f in out["fills"]]
                                z=[(f["side"],f["bar_index"],f["quantity"],f["price"],f["fee"]) for f in reference["fills"]]
                                if maximum>1e-7 or a!=z:raise ValueError("frozen_baseline_parity_failure")
                                checks.append({"key":k,"maximum_error":maximum})
                        print(json.dumps({"completed":f"{venue}/{label}/{capital}/{profile['id']}"}),flush=True)
    def get(where,name,prof):
        return next(x for x in allrows if x["venue"]=="Bybit" and x["window"]==where and x["capital"]==10000 and x["case"]==name and x["profile"]==prof)
    def worst(window,name):
        return max(get(window,name,p)["max_close_drawdown_pct"] for p in ("normal","stress"))
    def score(window,name):
        normal=get(window,name,"normal");stress=get(window,name,"stress");den=worst(window,name)
        return min(normal["cagr_pct"],stress["cagr_pct"])/den if den else -math.inf
    bN=get("training","baseline_a100","normal");bS=get("training","baseline_a100","stress")
    profit=[];efficient=[]
    for c in cfg["cases"][2:]:
        name=c["id"];n=get("training",name,"normal");s=get("training",name,"stress")
        if (n["net_pnl_usdt"]>=bN["net_pnl_usdt"] and
            s["net_pnl_usdt"]>=1.05*bS["net_pnl_usdt"] and worst("training",name)<=1.10*worst("training","baseline_a100")):
            profit.append(name)
        if (s["cagr_pct"]>0 and n["cagr_pct"]>=0.75*bN["cagr_pct"] and
            worst("training",name)<=worst("training","baseline_a100") and
            score("training",name)>=1.10*score("training","baseline_a100")):
            efficient.append(name)
    selected_profit=max(profit,key=lambda x:get("training",x,"stress")["net_pnl_usdt"]) if profit else "baseline_a100"
    selected_eff=max(efficient,key=lambda x:score("training",x)) if efficient else "baseline_a100"
    eN=get("evaluation","baseline_a100","normal");eS=get("evaluation","baseline_a100","stress")
    pok=selected_profit!="baseline_a100" and get("evaluation",selected_profit,"normal")["net_pnl_usdt"]>eN["net_pnl_usdt"] and get("evaluation",selected_profit,"stress")["net_pnl_usdt"]>=eS["net_pnl_usdt"] and worst("evaluation",selected_profit)<=1.10*worst("evaluation","baseline_a100")
    eok=selected_eff!="baseline_a100" and get("evaluation",selected_eff,"normal")["net_pnl_usdt"]>=0.75*eN["net_pnl_usdt"] and get("evaluation",selected_eff,"normal")["max_close_drawdown_pct"]<=0.8*eN["max_close_drawdown_pct"] and score("evaluation",selected_eff)>=1.10*score("evaluation","baseline_a100")
    result={"protocol_sha256":hashlib.sha256(policy.read_bytes()).hexdigest(),
            "code_sha256":hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "source_parent_sha":PARENT_SHA,"source_frames":{"bybit":B_HASH,"lbank":L_HASH},
            "selection":{"profit":selected_profit,"efficiency":selected_eff,"profit_eligible":profit,"efficiency_eligible":efficient},
            "evaluation_success":{"profit":bool(pok),"efficiency":bool(eok)},
            "run_count":records,"frozen_control_checks":checks,
            "results":allrows,"research_only":True,"paper_mutation":False,"live":False}
    result["sha256"]=hashobj(result)
    (output/"results.json").write_bytes(canon(result)+b"\n")
    print(json.dumps({"done":True,"sha256":result["sha256"],"runs":records,"control_parity":len(checks),
                     "selection":result["selection"],"evaluation_success":result["evaluation_success"]}),flush=True)

if __name__=="__main__":
    p=argparse.ArgumentParser()
    for n in ("source","inputs","policy","output"):p.add_argument("--"+n,type=Path,required=True)
    main(**vars(p.parse_args()))
