"""Bounded adaptive entry sizing with unchanged MR40 natural exits. Offline only."""
from __future__ import annotations
import argparse
from collections import defaultdict
from decimal import Decimal,ROUND_DOWN
import gzip
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import statistics

D=Decimal
Q=D("0.00000001")
LOT=D("0.00001")
STEP=14_400_000
V2_SHA="1fac7df1ecf2a92eae36bd557d2ca48e49b2a105b069b3e26e70bab9f52be2e2"


def canonical(x):return json.dumps(x,sort_keys=True,separators=(",",":"),ensure_ascii=False,allow_nan=False).encode()
def digest(x):return hashlib.sha256(canonical(x)).hexdigest()


def load_engines(source):
    path=source/"research/nexus_mr40_rr_sizing_v2.py"
    if hashlib.sha256(path.read_bytes()).hexdigest()!=V2_SHA:raise ValueError("pinned_v2_changed")
    spec=importlib.util.spec_from_file_location("adaptive_frozen_v2",path)
    v2=importlib.util.module_from_spec(spec);spec.loader.exec_module(v2)
    base=v2.load_base(source)
    return v2,base,base.load_code(source)


def fraction(case,volatility,drawdown):
    value=D(case["amount"])
    if case["vol_target"] is not None and volatility and volatility>0:
        value=min(value,D(case["vol_target"])/D(str(volatility)))
    if case["dd_threshold"] is not None and D(str(drawdown))>=D(case["dd_threshold"]):
        value=min(value,D(case["dd_scale"]))
    if not 0<value<=1:raise ValueError("invalid_fraction")
    return value


def simulate(rows,data,signals,case,start,end,profile,capital=10000,*,liquidate=True):
    if not 181<=start<end<=len(rows):raise ValueError("invalid_window")
    fee=D(str(profile["fee_bps"]))/10000;slip=D(str(profile["slippage_bps"]))/10000;lag=profile["lag_bars"]
    if lag not in (1,2):raise ValueError("invalid_lag")
    cash=D(capital);held=D(0);entry=None;equity=[];fills=[];positions=[];states={}
    peak=float(capital);skips=0;exposure=0;blocked=None

    def fill(side,i,j,reference,reason):
        nonlocal cash,held,entry,skips,blocked
        reference=D(str(reference));buy=side=="buy"
        price=(reference*(1+slip if buy else 1-slip)).quantize(Q)
        before=cash
        if buy:
            drawdown=states[j]["drawdown"] if j in states else 0.
            allocation=fraction(case,data["volatility"][j],drawdown)
            budget=cash*allocation
            units=(budget/(price*(1+fee))/LOT).to_integral_value(rounding=ROUND_DOWN)*LOT
            for _ in range(2):
                notional=(units*price).quantize(Q);commission=(notional*fee).quantize(Q)
                if notional+commission<=budget:break
                units-=LOT
            else:raise ValueError("budget_rounding_failure")
            if units<LOT or units*reference<1:
                skips+=1;blocked=data["episode"][j];return
        else:
            units=held;allocation=None;drawdown=None
            if units<LOT or units*reference<1:raise ValueError("exit_below_minimum")
            notional=(units*price).quantize(Q);commission=(notional*fee).quantize(Q)
        cash+=-notional-commission if buy else notional-commission
        held=units if buy else D(0)
        if cash<0:raise ValueError("negative_cash")
        stamp=rows[i][0]+(STEP if reason=="terminal_close" else 0)
        if j is not None and rows[j][0]+STEP>stamp:raise ValueError("future_information")
        event={"side":side,"bar_index":i,"fill_ms":stamp,"signal_index":j,"reason":reason,"quantity":str(units),
            "reference":str(reference),"price":str(price),"notional":str(notional),"fee":str(commission),"cash_before":str(before),"cash_after":str(cash),
            "allocation":None if allocation is None else str(allocation),"observed_drawdown_pct":None if drawdown is None else 100*drawdown,
            "observed_annual_vol_pct":100*data["volatility"][j] if buy and data["volatility"][j] is not None else None}
        fills.append(event)
        if buy:entry=event
        else:
            pnl=cash-D(entry["cash_before"])
            positions.append({"entry":entry,"exit":event,"net_pnl_usdt":float(pnl),
                "account_return_pct":float(pnl/D(entry["cash_before"])*100),"holding_hours":(stamp-entry["fill_ms"])/3_600_000})
            entry=None

    for i in range(start,end):
        j=i-lag;desired=signals[j]
        if data["episode"][j] and data["episode"][j]==blocked:desired=0
        if held and not desired:fill("sell",i,j,rows[i][1],"natural_exit")
        elif desired and not held:fill("buy",i,j,rows[i][1],"episode_entry")
        mark=float(cash+held*D(str(rows[i][4])));equity.append(mark)
        peak=max(peak,mark);states[i]={"drawdown":max(0.,1-mark/peak)}
        exposure+=int(bool(held))
    if held and liquidate:
        fill("sell",end-1,None,rows[end-1][4],"terminal_close");equity[-1]=float(cash)
    verify_ledger(rows,case,start,end,profile,capital,fills,equity)
    peak=float(capital);dd=0.;longest=under=0
    for value in equity:
        peak=max(peak,value);dd=max(dd,1-value/peak);under=under+1 if value<peak-1e-8 else 0;longest=max(longest,under)
    if liquidate and abs(sum(p["net_pnl_usdt"] for p in positions)-(equity[-1]-capital))>1e-6:raise ValueError("position_reconciliation")
    gains=sum(max(0,p["net_pnl_usdt"]) for p in positions);losses=-sum(min(0,p["net_pnl_usdt"]) for p in positions)
    allocations=[float(f["allocation"])*100 for f in fills if f["side"]=="buy"]
    metrics={"case":case["id"],"entry":case["entry"],"profile":profile["id"],"capital_usdt":capital,
        "start_ms":rows[start][0],"end_exclusive_ms":rows[end-1][0]+STEP,
        "net_pnl_usdt":equity[-1]-capital,"net_return_pct":100*(equity[-1]/capital-1),
        "cagr_pct":100*((equity[-1]/capital)**(365.25*6/(end-start))-1),"max_close_drawdown_pct":100*dd,
        "longest_underwater_days":longest/6,"closed_positions":len(positions),"fills":len(fills),"entry_skips":skips,
        "terminal_exits":sum(p["exit"]["reason"]=="terminal_close" for p in positions),
        "win_rate_pct":100*sum(p["net_pnl_usdt"]>0 for p in positions)/len(positions) if positions else None,
        "profit_factor":gains/losses if losses else None,"max_loss_pct_entry_equity":max([0]+[-p["account_return_pct"] for p in positions]),
        "max_holding_hours":max((p["holding_hours"] for p in positions),default=0),
        "median_entry_allocation_pct":statistics.median(allocations) if allocations else None,"min_entry_allocation_pct":min(allocations,default=None),
        "fees_usdt":float(sum((D(f["fee"]) for f in fills),D(0))),"exposure_bar_pct":100*exposure/(end-start),"open_quantity_btc":str(held),"ledger_replay_verified":True}
    return {"metrics":metrics,"fills":fills,"positions":positions,"equity":equity}


def verify_ledger(rows,case,start,end,profile,capital,fills,curve):
    """Rebuild fees, holdings and marks; independently recompute each sizing budget."""
    fee=D(str(profile["fee_bps"]))/10000;slip=D(str(profile["slippage_bps"]))/10000
    grouped=defaultdict(list)
    for f in fills:
        if not start<=f["bar_index"]<end:raise ValueError("fill_outside_window")
        grouped[f["bar_index"]].append(f)
    cash=D(capital);held=D(0);verified=[]
    for i in range(start,end):
        for f in grouped[i]:
            buy=f["side"]=="buy";units=D(f["quantity"])
            terminal=f["reason"]=="terminal_close"
            reference=D(str(rows[i][4] if terminal else rows[i][1]))
            price=(reference*(1+slip if buy else 1-slip)).quantize(Q)
            notional=(units*price).quantize(Q);commission=(notional*fee).quantize(Q)
            if units<LOT or units%LOT or units*reference<1:raise ValueError("invalid_venue_order")
            if tuple(D(f[k]) for k in ("reference","price","notional","fee","cash_before"))!=(reference,price,notional,commission,cash):raise ValueError("ledger_quote_changed")
            if f["fill_ms"]!=rows[i][0]+(STEP if terminal else 0):raise ValueError("fill_time_changed")
            j=f["signal_index"]
            if j is not None and (j!=i-profile["lag_bars"] or rows[j][0]+STEP>f["fill_ms"]):raise ValueError("future_or_wrong_latency")
            if buy:
                if held:raise ValueError("duplicate_entry")
                closes=[float(r[4]) for r in rows[j-180:j+1]]
                vol=statistics.pstdev(math.log(b/a) for a,b in zip(closes,closes[1:]))*math.sqrt(365.25*6)
                prior=verified[:max(0,j-start+1)];value=prior[-1] if prior else float(capital)
                peak=max([float(capital)]+prior);dd=max(0.,1-value/peak)
                caps=[D(case["amount"])]
                if case["vol_target"] is not None and vol>0:caps.append(D(case["vol_target"])/D(str(vol)))
                if case["dd_threshold"] is not None and D(str(dd))>=D(case["dd_threshold"]):caps.append(D(case["dd_scale"]))
                allocation=min(caps);budget=cash*allocation
                expected=(budget/(price*(1+fee))/LOT).to_integral_value(rounding=ROUND_DOWN)*LOT
                while True:
                    n=(expected*price).quantize(Q);c=(n*fee).quantize(Q)
                    if n+c<=budget:break
                    expected-=LOT
                if units!=expected or D(f["allocation"])!=allocation or notional+commission>budget:raise ValueError("adaptive_sizing_changed")
                if abs(f["observed_drawdown_pct"]-100*dd)>1e-10 or abs(f["observed_annual_vol_pct"]-100*vol)>1e-10:raise ValueError("future_or_changed_sizing_observation")
                held=units
            else:
                if not held or held!=units:raise ValueError("orphan_exit")
                held=D(0)
            cash+=-notional-commission if buy else notional-commission
            if cash<0 or cash!=D(f["cash_after"]):raise ValueError("ledger_cash_changed")
        mark=float(cash+held*D(str(rows[i][4])))
        if abs(mark-curve[i-start])>1e-7:raise ValueError("independent_mark_changed")
        verified.append(mark)


def run(source,inputs,output,protocol_commit,code_commit):
    if output.exists():raise ValueError("refuse_result_overwrite")
    policy_path=source/"research/mr40_adaptive_sizing_v3.json";policy=json.loads(policy_path.read_bytes());cases=policy["cases"]
    if len(cases)!=11 or len({c["id"] for c in cases})!=11 or policy["pinned_v2_sha256"]!=V2_SHA:raise ValueError("family_changed")
    for value in (protocol_commit,code_commit):
        if len(value)!=40 or any(c not in "0123456789abcdef" for c in value):raise ValueError("exact_commit_required")
    v2,base,code=load_engines(source)
    b=json.loads((inputs/"bybit_prepared_inputs.json").read_bytes());e=json.loads((inputs/"bybit_october_input_extension.json").read_bytes())
    for obj,key,expected in ((b,"input_digest","fba66860376d9ad24af7a2388e878db0dfdbae16468de9381ef6a95f95563ffe"),(e,"digest","17f3101579ebd301cda074174ed4154e772d15d6b2ef2e17513d73b1dc31798c")):
        if obj[key]!=expected or digest({k:v for k,v in obj.items() if k!=key})!=expected:raise ValueError("input_changed")
    rows=b["rows"]+e["rows"]
    root=source/"docs/evidence/lbank-mr40-exact30-20261021";raw=(root/"lbank_kline_response.json").read_bytes()
    if hashlib.sha256(raw).hexdigest()!=json.loads((root/"source_receipt.json").read_bytes())["body_sha256"]:raise ValueError("lbank_changed")
    native=code["validator"](json.loads(raw,parse_float=str)["data"])
    lbank=sorted(([r[0]*1000,*r[1:]] for r in native if r[0]*1000<base.ms(policy["lbank30"][1])),key=lambda r:r[0])
    if digest(rows)!="a458d9f83df633df8ee5cab5f2a19de41c4c79c61185b5abd258fdefa80d575a" or digest(lbank)!="7274373a6ff9e1a060da4c18dffe9da69436345657505cd52f768f11d04ab278":raise ValueError("price_frame_changed")
    data=v2.prepare(rows,base,code);ldata=v2.prepare(lbank,base,code)
    output.mkdir(parents=True);results=[];folds=[];curves={};parity=[];count=0
    def indices(frame,dates):
        start=next((i for i,r in enumerate(frame) if r[0]==base.ms(dates[0])),len(frame))
        end=next((i for i,r in enumerate(frame) if r[0]==base.ms(dates[1])),len(frame))
        if start<181 or start>=end or [r[0] for r in frame[start:end]]!=list(range(base.ms(dates[0]),base.ms(dates[1]),STEP)):raise ValueError("incomplete_window")
        return start,end
    with gzip.open(output/"all_runs.jsonl.gz","wb",compresslevel=6) as stream:
        def window(venue,frame,fdata,label,dates,capital,profiles=None):
            nonlocal count
            start,end=indices(frame,dates);signals={k:base.targets(frame,fdata,k,start,end) for k in ("baseline","confirm3")};records=[]
            for case in cases:
                for profile in profiles or policy["profiles"]:
                    out=simulate(frame,fdata,signals[case["entry"]],case,start,end,profile,capital)
                    m={"venue":venue,"window":label,**out["metrics"]};results.append(m);records.append(m);count+=1
                    key=f"{venue}/{label}/{capital}/{case['id']}/{profile['id']}"
                    stream.write(canonical({"key":key,"metrics":m,"fills":out["fills"],"positions":out["positions"],"equity_sha256_6dp":digest([format(x,".6f") for x in out["equity"]])})+b"\n")
                    if venue=="Bybit" and label=="full" and capital==10000 and profile["id"]=="normal":curves[case["id"]]=out["equity"]
                    controls={"baseline_a100":"baseline","baseline_a50":"cash50_control","confirm_natural_a100":"confirm3"}
                    if case["id"] in controls and label in ("full","lbank30"):
                        old=base.simulate(frame,fdata,controls[case["id"]],start,end,profile,capital)
                        error=max(abs(x-y) for x,y in zip(out["equity"],old["equity"]))
                        if error>1e-7 or [(f["fill_ms"],f["side"]) for f in old["fills"]]!=[(f["fill_ms"],f["side"]) for f in out["fills"]]:raise ValueError("control_execution_drift")
                        parity.append({"key":key,"maximum_equity_error":error})
            print(json.dumps({"completed_window":f"{venue}/{label}/{capital}","ledger_replays":count}),flush=True)
            return records
        for cap in policy["capitals_usdt"]:window("Bybit",rows,data,"training",policy["training"],cap)
        selection=v2.select([x for x in results if x["window"]=="training" and x["capital_usdt"]==10000],cases)
        (output/"selection.json").write_bytes(canonical(selection)+b"\n");print(json.dumps({"training_selection_locked":selection}),flush=True)
        for cap in policy["capitals_usdt"]:
            for label in ("evaluation","full","year2026"):window("Bybit",rows,data,label,policy[label],cap)
        for n,(begin,end) in enumerate(zip(policy["walk_forward"],policy["walk_forward"][1:])):
            train=window("Bybit",rows,data,f"fold{n}_train",["2023-01-01",begin],10000,policy["profiles"][:2]);pick=v2.select(train,cases)
            test=window("Bybit",rows,data,f"fold{n}_test",[begin,end],10000,policy["profiles"][:2])
            folds.append({"start":begin,"end_exclusive":end,"selection":pick,"results":[x for x in test if x["case"] in {"baseline_a100",pick["profit"],pick["efficiency"]}]})
        for cap in policy["capitals_usdt"]:window("LBank",lbank,ldata,"lbank30",policy["lbank30"],cap)
    checks=0;start,_=indices(rows,policy["evaluation"])
    for cut in (start+239,len(rows)-71):
        short_data=v2.prepare(rows[:cut],base,code)
        full_signals={k:base.targets(rows,data,k,start,len(rows)) for k in ("baseline","confirm3")};short_signals={k:base.targets(rows[:cut],short_data,k,start,cut) for k in ("baseline","confirm3")}
        for case in cases:
            for profile in policy["profiles"]:
                a=simulate(rows,data,full_signals[case["entry"]],case,start,len(rows),profile,500,liquidate=False)
                b=simulate(rows[:cut],short_data,short_signals[case["entry"]],case,start,cut,profile,500,liquidate=False)
                if b["fills"]!=[f for f in a["fills"] if f["bar_index"]<cut] or b["equity"]!=a["equity"][:cut-start]:raise ValueError("future_dependent_execution")
                checks+=1
    def metric(name,profile):return next(x for x in results if x["case"]==name and x["profile"]==profile and x["window"]=="evaluation" and x["capital_usdt"]==10000)
    def worst(name):return max(metric(name,p)["max_close_drawdown_pct"] for p in ("normal","stress"))
    def score(name):
        values=[metric(name,p)["cagr_pct"] for p in ("normal","stress")];dd=worst(name)
        return min(values)/dd if dd and values[1]>0 else -math.inf
    profit,eff=selection["profit"],selection["efficiency"];bn=metric("baseline_a100","normal");bs=metric("baseline_a100","stress")
    profit_ok=profit!="baseline_a100" and metric(profit,"normal")["net_pnl_usdt"]>=bn["net_pnl_usdt"] and metric(profit,"stress")["net_pnl_usdt"]>=bs["net_pnl_usdt"] and worst(profit)<=1.10*worst("baseline_a100")
    eff_ok=eff!="baseline_a100" and score(eff)>0 and (score("baseline_a100")<=0 or score(eff)>=1.10*score("baseline_a100")) and metric(eff,"normal")["net_pnl_usdt"]>=.75*bn["net_pnl_usdt"] and metric(eff,"normal")["max_close_drawdown_pct"]<=.80*bn["max_close_drawdown_pct"]
    compound={}
    for profile in ("normal","stress"):
        for method in ("baseline","profit","efficiency"):
            value=10000.
            for fold in folds:
                name="baseline_a100" if method=="baseline" else fold["selection"][method]
                value*=1+next(x["net_return_pct"] for x in fold["results"] if x["case"]==name and x["profile"]==profile)/100
            compound[profile+"/"+method]=value-10000
    report={"schema":"nexus.mr40-adaptive-sizing-results.v3","protocol_commit":protocol_commit,"code_commit":code_commit,
        "policy_sha256":hashlib.sha256(policy_path.read_bytes()).hexdigest(),"driver_sha256":hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),"pinned_v2_sha256":V2_SHA,
        "data":{"Bybit":{"bars":len(rows),"rows_sha256":digest(rows)},"LBank":{"bars":len(lbank),"rows_sha256":digest(lbank)}},"case_count":len(cases),"selection":selection,
        "evaluation_profit_success":bool(profit_ok),"evaluation_efficiency_success":bool(eff_ok),"main_ledger_replays":count,"prefix_checks":checks,"control_parity_checks":parity,
        "walk_forward":folds,"walk_forward_compounded_pnl_10000":compound,"results":results,"classification":policy["classification"],"authority":policy["authority"]}
    report["result_digest"]=digest(report);(output/"results.json").write_bytes(canonical(report)+b"\n");(output/"full_normal_curves.json").write_bytes(canonical(curves)+b"\n")
    print(json.dumps({"selection":selection,"profit_success":bool(profit_ok),"efficiency_success":bool(eff_ok),"runs":count,"prefix_checks":checks,"result_digest":report["result_digest"]}),flush=True)
    return report


if __name__=="__main__":
    p=argparse.ArgumentParser()
    for key in ("source","inputs","output"):p.add_argument("--"+key,type=Path,required=True)
    for key in ("protocol_commit","code_commit"):p.add_argument("--"+key.replace("_","-"),required=True)
    run(**vars(p.parse_args()))
