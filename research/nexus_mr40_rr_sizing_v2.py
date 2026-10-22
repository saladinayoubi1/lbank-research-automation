"""Predeclared MR40 reward/risk systems. Offline research, no order API."""
from __future__ import annotations

import argparse
from collections import defaultdict, deque
from datetime import datetime, timezone
from decimal import Decimal, ROUND_DOWN, ROUND_UP
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
BASE_SHA="07a3ba7a0ebf52e9d1e2c6832de1caf480a373db1e5303d5ed600d89345a52af"


def canonical(value):
    return json.dumps(value,sort_keys=True,separators=(",",":"),ensure_ascii=False,allow_nan=False).encode()


def digest(value):return hashlib.sha256(canonical(value)).hexdigest()


def load_base(source):
    path=source/"research/nexus_mr40_isolated_improvement_v1.py"
    if hashlib.sha256(path.read_bytes()).hexdigest()!=BASE_SHA:raise ValueError("base_engine_changed")
    spec=importlib.util.spec_from_file_location("rr_frozen_base",path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def prepare(rows,base,code):
    data=base.features(rows,code)
    window=deque();total=D(0);atr=[]
    for i,row in enumerate(rows):
        high,low=D(str(row[2])),D(str(row[3]))
        previous=D(str(rows[i-1][4])) if i else D(str(row[1]))
        tr=max(high-low,abs(high-previous),abs(low-previous))
        window.append(tr);total+=tr
        if len(window)>20:total-=window.popleft()
        atr.append(total/20 if len(window)==20 else None)
    data["atr"]=atr
    return data


def quote(units,price,fee):
    notional=(units*price).quantize(Q)
    commission=(notional*fee).quantize(Q)
    return notional,commission


def simulate(rows,data,signals,case,start,end,profile,capital=10000,*,liquidate=True,stop_first=True):
    if not 1<=start<end<=len(rows):raise ValueError("invalid_window")
    fee,slip=D(str(profile["fee_bps"]))/10000,D(str(profile["slippage_bps"]))/10000
    lag=profile["lag_bars"]
    if lag not in (1,2):raise ValueError("invalid_latency")
    cash=D(capital);held=D(0);position=None
    fills=[];positions=[];equity=[];ambiguous=set();entry_stats=[];flat_at_close={}
    mode=case["exit"];close_only=profile["protection"]=="close_next_open"
    skips=0;partial_skips=0;exposed=0

    def price(reference,buy=False):return (D(str(reference))*(1+slip if buy else 1-slip)).quantize(Q)

    def target():
        if mode=="partial50" and not position["partial_done"] and not position["partial_disabled"]:
            return position["buy_price"]+position["distance"]
        return position["target"]

    def event(side,i,reference,units,reason,when,j=None,**extra):
        nonlocal cash,held
        reference=D(str(reference));fill_price=price(reference,side=="buy")
        notional,commission=quote(units,fill_price,fee)
        before=cash
        cash+=-notional-commission if side=="buy" else notional-commission
        held+=units if side=="buy" else -units
        if cash<0 or held<0:raise ValueError("negative_cash_or_leverage")
        begin=rows[i][0]+(STEP if when=="close" else 0)
        finish=rows[i][0]+(STEP if when in ("close","intrabar") else 0)
        item={"side":side,"bar_index":i,"fill_ms":finish,"time_kind":when,
            "interval_start_ms":begin,"interval_end_ms":finish,"signal_index":j,
            "reason":reason,"quantity":str(units),"reference":str(reference),"price":str(fill_price),
            "notional":str(notional),"fee":str(commission),"cash_before":str(before),"cash_after":str(cash),**extra}
        fills.append(item)
        return item

    def buy(i,j):
        nonlocal held,position,skips
        reference=D(str(rows[i][1]));fill_price=price(reference,True)
        distance=2*data["atr"][j] if mode!="natural" and data["atr"][j] is not None else None
        if mode!="natural" and (distance is None or distance<=0 or distance>=fill_price):skips+=1;return
        stop=(fill_price-distance).quantize(Q) if distance is not None else None
        take=(fill_price+D(case["rr"])*distance).quantize(Q) if distance is not None else None
        budget=cash*D(case["amount"]) if case["sizing"]=="allocation" else cash
        capacity=budget/(fill_price*(1+fee))
        risk_budget=cash*D(case["amount"]) if case["sizing"]=="risk" else None
        unit_loss=fill_price*(1+fee)-price(min(stop,reference))*(1-fee) if stop is not None else None
        if risk_budget is not None:
            if unit_loss is None or unit_loss<=0:raise ValueError("risk_without_stop")
            capacity=min(capacity,risk_budget/unit_loss)
        units=(capacity/LOT).to_integral_value(rounding=ROUND_DOWN)*LOT
        for _ in range(2):
            cost,commission=quote(units,fill_price,fee)
            exit_value,exit_fee=quote(units,price(min(stop,reference)),fee) if stop is not None else (D(0),D(0))
            planned=cost+commission-exit_value+exit_fee if stop is not None else None
            if cost+commission<=budget and (risk_budget is None or planned<=risk_budget+Q):break
            units-=LOT
        else:raise ValueError("entry_budget_rounding_failure")
        if units<LOT or units*reference<1:skips+=1;return
        before=cash
        tp_value,tp_fee=quote(units,price(take),fee) if take is not None else (D(0),D(0))
        # The planned reward of a scale-out is the sum of its two legs, not
        # the final 3R target applied to the entire initial quantity.
        if mode=="partial50":
            half=(units/2/LOT).to_integral_value(rounding=ROUND_DOWN)*LOT
            first_target=fill_price+distance
            if half>=LOT and half*first_target>=1 and units-half>=LOT:
                first_value,first_fee=quote(half,price(first_target),fee)
                last_value,last_fee=quote(units-half,price(take),fee)
                tp_value,tp_fee=first_value+last_value,first_fee+last_fee
        net_rr=(tp_value-tp_fee-cost-commission)/planned if planned and planned>0 else None
        item=event("buy",i,reference,units,"episode_entry","open",j,
            allocation_budget=str(budget),risk_budget=None if risk_budget is None else str(risk_budget),
            planned_loss=None if planned is None else str(planned),initial_stop=None if stop is None else str(stop),
            initial_target=None if take is None else str(take),atr=str(data["atr"][j]),distance=None if distance is None else str(distance))
        position={"entry":item,"buy_price":fill_price,"initial_units":units,"distance":distance,"stop":stop,"target":take,
            "planned_loss":planned,"net_planned_rr":net_rr,"cost":cost+commission,"initial_cash":before,
            "partial_done":False,"partial_disabled":False,"partial_bar":None,"updated_through":i-1}
        entry_stats.append({"allocation_pct":float((cost+commission)/before*100),
            "risk_pct":float(planned/before*100) if planned is not None else None,
            "net_planned_rr":float(net_rr) if net_rr is not None else None})

    def sell(i,reference,reason,when,j=None,units=None):
        nonlocal position
        units=held if units is None else units
        if units<LOT or units*D(str(reference))<1:raise ValueError("exit_below_venue_minimum")
        snapshot={"active_stop":None if position["stop"] is None else str(position["stop"]),
            "active_target":None if position["target"] is None else str(target()),
            "update_signal_index":position["updated_through"]}
        item=event("sell",i,reference,units,reason,when,j,**snapshot)
        if not held:
            pnl=cash-position["initial_cash"]
            lower=(item["interval_start_ms"]-position["entry"]["fill_ms"])/3_600_000
            upper=(item["interval_end_ms"]-position["entry"]["fill_ms"])/3_600_000
            positions.append({"entry":position["entry"],"exit":item,"net_pnl_usdt":float(pnl),
                "account_return_pct":float(pnl/position["initial_cash"]*100),"notional_return_pct":float(pnl/position["cost"]*100),
                "realized_r":float(pnl/position["planned_loss"]) if position["planned_loss"] else None,
                "holding_hours_lower":lower,"holding_hours_upper":upper})
            position=None

    def partial(i,reference,when,j=None):
        nonlocal partial_skips
        units=(position["initial_units"]/2/LOT).to_integral_value(rounding=ROUND_DOWN)*LOT
        if units<LOT or units*D(str(reference))<1 or held-units<LOT:
            partial_skips+=1;position["partial_disabled"]=True;return
        sell(i,reference,"partial_1r",when,j,units)
        position["partial_done"]=True;position["partial_bar"]=i

    def update(i,j):
        if not position or position["stop"] is None or j<position["entry"]["bar_index"] or j<=position["updated_through"]:return
        previous_close=D(str(rows[j][4]))
        if (mode=="breakeven" and previous_close>=position["buy_price"]+position["distance"]) or (
                mode=="partial50" and position["partial_done"] and j>=position["partial_bar"]):
            be=(position["buy_price"]*(1+fee)/((1-slip)*(1-fee))).quantize(Q,rounding=ROUND_UP)
            position["stop"]=max(position["stop"],be)
        if mode=="trail" and data["atr"][j] is not None:
            position["stop"]=max(position["stop"],(previous_close-2*data["atr"][j]).quantize(Q))
        position["updated_through"]=j

    def protective(i,j,gap):
        if not position or position["stop"] is None:return
        op,high,low=D(str(rows[i][1])),D(str(rows[i][2])),D(str(rows[i][3]))
        for _ in range(2):
            if not position:return
            sl,tp=position["stop"],target()
            if close_only:
                if j<position["entry"]["bar_index"]:return
                observed=D(str(rows[j][4]));hit_sl,hit_tp=observed<=sl,observed>=tp
            elif gap:
                hit_sl,hit_tp=op<=sl,op>=tp
            else:
                hit_sl,hit_tp=low<=sl,high>=tp
                if hit_sl and hit_tp:ambiguous.add(i)
            if hit_sl and (stop_first or not hit_tp):
                reference=op if gap or close_only else sl
                sell(i,reference,"protective_stop","open" if gap or close_only else "intrabar",j if close_only else None)
                return
            if not hit_tp:return
            reference=op if close_only else tp
            when="open" if gap or close_only else "intrabar"
            if mode=="partial50" and not position["partial_done"] and not position["partial_disabled"]:
                partial(i,reference,when,j if close_only else None)
            else:
                sell(i,reference,"take_profit",when,j if close_only else None)
                return

    for i in range(start,end):
        j=i-lag
        before_fills=len(fills)
        was_held=bool(held)
        if was_held:
            if close_only:
                protective(i,j,True)
                update(i,j)
            else:
                update(i,j);protective(i,j,True)
            if held and mode in ("natural","hybrid") and not signals[j]:sell(i,rows[i][1],"natural_exit","open",j)
        edge=j>=start-1 and signals[j] and (j==start-1 or not signals[j-1])
        fresh_for_account=mode=="natural" or flat_at_close.get(j,True)
        if not was_held and not held and edge and fresh_for_account:buy(i,j)
        if held and not close_only and mode!="natural":
            if not was_held:protective(i,j,True)
            if held:protective(i,j,False)
        exposed+=int(was_held or held or any(f["side"]=="buy" for f in fills[before_fills:]))
        equity.append(float(cash+held*D(str(rows[i][4]))))
        flat_at_close[i]=not bool(held)
    if held and liquidate:
        sell(end-1,rows[end-1][4],"terminal_close","close")
        equity[-1]=float(cash)
    verify_ledger(rows,case,start,end,profile,capital,fills,equity)
    peak=float(capital);dd=0.;under=0;longest=0
    for value in equity:
        peak=max(peak,value);dd=max(dd,1-value/peak)
        under=under+1 if value<peak-1e-8 else 0;longest=max(longest,under)
    if liquidate and abs(sum(p["net_pnl_usdt"] for p in positions)-(equity[-1]-capital))>1e-6:raise ValueError("position_cashflow_mismatch")
    wins=[p["notional_return_pct"] for p in positions if p["net_pnl_usdt"]>0]
    losses=[p["notional_return_pct"] for p in positions if p["net_pnl_usdt"]<0]
    gains=sum(max(0,p["net_pnl_usdt"]) for p in positions);lost=-sum(min(0,p["net_pnl_usdt"]) for p in positions)
    median=lambda field:statistics.median(x[field] for x in entry_stats if x[field] is not None) if any(x[field] is not None for x in entry_stats) else None
    metrics={"case":case["id"],"entry":case["entry"],"exit_system":mode,"nominal_rr":case["rr"],"sizing":case["sizing"],"sizing_amount":case["amount"],
        "profile":profile["id"],"capital_usdt":capital,"start_ms":rows[start][0],"end_exclusive_ms":rows[end-1][0]+STEP,
        "net_pnl_usdt":equity[-1]-capital,"net_return_pct":100*(equity[-1]/capital-1),
        "cagr_pct":100*((equity[-1]/capital)**(365.25*6/(end-start))-1),"max_close_drawdown_pct":100*dd,
        "longest_underwater_days":longest/6,"closed_positions":len(positions),"fills":len(fills),
        "terminal_exits":sum(p["exit"]["reason"]=="terminal_close" for p in positions),
        "stop_exits":sum(p["exit"]["reason"]=="protective_stop" for p in positions),
        "target_exits":sum(p["exit"]["reason"]=="take_profit" for p in positions),
        "partial_fills":sum(f["reason"]=="partial_1r" for f in fills),"partial_skips":partial_skips,"entry_skips":skips,
        "ambiguous_bars":len(ambiguous),"median_entry_allocation_pct":median("allocation_pct"),
        "median_nominal_risk_pct":median("risk_pct"),"median_net_planned_rr":median("net_planned_rr"),
        "realized_average_win_loss_ratio":statistics.mean(wins)/abs(statistics.mean(losses)) if wins and losses else None,
        "mean_realized_r":statistics.mean(p["realized_r"] for p in positions if p["realized_r"] is not None) if mode!="natural" and positions else None,
        "win_rate_pct":100*len(wins)/len(positions) if positions else None,"profit_factor":gains/lost if lost else None,
        "mean_position_pnl_usdt":statistics.mean(p["net_pnl_usdt"] for p in positions) if positions else None,
        "max_loss_pct_entry_equity":max([0]+[-p["account_return_pct"] for p in positions]),
        "max_holding_hours_upper":max((p["holding_hours_upper"] for p in positions),default=0),
        "fees_usdt":float(sum((D(f["fee"]) for f in fills),D(0))),"exposure_bar_pct":100*exposed/(end-start),
        "open_quantity_btc":str(held),"ledger_replay_verified":True}
    return {"metrics":metrics,"fills":fills,"positions":positions,"equity":equity}


def verify_ledger(rows,case,start,end,profile,capital,fills,curve):
    """Separate quote arithmetic, holdings replay and causal price-source checks."""
    fee,slip=D(str(profile["fee_bps"]))/10000,D(str(profile["slippage_bps"]))/10000
    grouped=defaultdict(list)
    for item in fills:grouped[item["bar_index"]].append(item)
    cash=D(capital);units=D(0);entry=None
    for i in range(start,end):
        for f in grouped[i]:
            buy=f["side"]=="buy";quantity=D(f["quantity"]);reference=D(f["reference"])
            if quantity<=0 or quantity%LOT or quantity*reference<1:raise ValueError("invalid_venue_order")
            if f["time_kind"]=="open" and reference!=D(str(rows[i][1])) and f["reason"] not in ("take_profit","partial_1r"):raise ValueError("open_price_changed")
            if f["time_kind"]=="intrabar":
                if not D(str(rows[i][3]))<=reference<=D(str(rows[i][2])):raise ValueError("intrabar_fill_outside_range")
                if f["reason"]=="protective_stop" and reference!=D(f["active_stop"]):raise ValueError("stop_price_changed")
                if f["reason"] in ("take_profit","partial_1r") and reference!=D(f["active_target"]):raise ValueError("target_price_changed")
                if f["interval_start_ms"]!=rows[i][0] or f["interval_end_ms"]!=rows[i][0]+STEP:raise ValueError("fabricated_intrabar_time")
            if f["signal_index"] is not None and f["signal_index"]!=i-profile["lag_bars"]:raise ValueError("wrong_latency")
            if not buy and f["update_signal_index"]>=i:raise ValueError("future_stop_update")
            expected_price=(reference*(1+slip if buy else 1-slip)).quantize(Q)
            notional=(quantity*expected_price).quantize(Q);commission=(notional*fee).quantize(Q)
            if (expected_price,notional,commission,cash)!=tuple(D(f[k]) for k in ("price","notional","fee","cash_before")):raise ValueError("ledger_price_fee_or_cash_changed")
            if buy:
                if units:raise ValueError("pyramiding_or_duplicate_entry")
                budget=cash*D(case["amount"]) if case["sizing"]=="allocation" else cash
                if notional+commission>budget:raise ValueError("allocation_budget_exceeded")
                if case["sizing"]=="risk" and D(f["planned_loss"])>cash*D(case["amount"])+Q:raise ValueError("nominal_risk_exceeded")
                if case["exit"]!="natural":
                    j=f["signal_index"]
                    tr=[max(D(str(rows[t][2]))-D(str(rows[t][3])),abs(D(str(rows[t][2]))-D(str(rows[t-1][4]))),abs(D(str(rows[t][3]))-D(str(rows[t-1][4])))) for t in range(j-19,j+1)]
                    distance=sum(tr)/10
                    if D(f["distance"])!=distance or D(f["initial_stop"])!=(expected_price-distance).quantize(Q):raise ValueError("future_or_changed_atr_stop")
                    if D(f["initial_target"])!=(expected_price+D(case["rr"])*distance).quantize(Q):raise ValueError("changed_reward_multiple")
                    stop_reference=min(D(f["initial_stop"]),reference)
                    stop_price=(stop_reference*(1-slip)).quantize(Q)
                    stop_notional=(quantity*stop_price).quantize(Q);stop_fee=(stop_notional*fee).quantize(Q)
                    if D(f["planned_loss"])!=notional+commission-stop_notional+stop_fee:raise ValueError("planned_risk_changed")
                units=quantity;entry=f
            else:
                if not entry or quantity>units:raise ValueError("orphan_exit")
                units-=quantity
                if not units:entry=None
            cash+=-notional-commission if buy else notional-commission
            if cash<0 or cash!=D(f["cash_after"]):raise ValueError("ledger_cash_mismatch")
        if abs(float(cash+units*D(str(rows[i][4])))-curve[i-start])>1e-7:raise ValueError("independent_mark_mismatch")


def select(records,cases):
    grouped={c["id"]:{x["profile"]:x for x in records if x["case"]==c["id"]} for c in cases}
    base=grouped["baseline_a100"]
    def worst(c):return max(grouped[c][p]["max_close_drawdown_pct"] for p in ("normal","stress"))
    def score(c):
        values=grouped[c];risk=worst(c)
        return min(values[p]["cagr_pct"] for p in ("normal","stress"))/risk if risk>0 and values["stress"]["cagr_pct"]>0 else -math.inf
    base_score=score("baseline_a100");profit=[];efficient=[]
    for c in cases:
        name=c["id"]
        if name in ("baseline_a100","baseline_a25","baseline_a50"):continue
        a=grouped[name]
        hurdle=1.05*base["stress"]["net_pnl_usdt"] if base["stress"]["net_pnl_usdt"]>0 else 0
        stress_ok=(a["stress"]["net_pnl_usdt"]>=hurdle if base["stress"]["net_pnl_usdt"]>0 else a["stress"]["net_pnl_usdt"]>0)
        if a["normal"]["net_pnl_usdt"]>=base["normal"]["net_pnl_usdt"] and stress_ok and worst(name)<=1.10*worst("baseline_a100"):profit.append(name)
        if score(name)>0 and (base_score<=0 or score(name)>=1.10*base_score) and a["normal"]["cagr_pct"]>=.75*max(0,base["normal"]["cagr_pct"]) and worst(name)<=worst("baseline_a100"):efficient.append(name)
    return {"profit":max(profit,key=lambda n:grouped[n]["stress"]["net_pnl_usdt"]) if profit else "baseline_a100",
        "efficiency":max(efficient,key=score) if efficient else "baseline_a100","profit_eligible":profit,"efficiency_eligible":efficient,
        "scores":{c["id"]:(score(c["id"]) if math.isfinite(score(c["id"])) else None) for c in cases}}


def run(source,inputs,output,protocol_commit,code_commit):
    if output.exists():raise ValueError("refuse_result_overwrite")
    policy_path=source/"research/mr40_rr_sizing_v2.json"
    policy=json.loads(policy_path.read_bytes());cases=policy["cases"]
    if len(cases)!=27 or len({c["id"] for c in cases})!=27 or policy["base_driver_sha256"]!=BASE_SHA:raise ValueError("registered_family_changed")
    for sha in (protocol_commit,code_commit):
        if len(sha)!=40 or any(c not in "0123456789abcdef" for c in sha):raise ValueError("exact_commits_required")
    base=load_base(source);code=base.load_code(source)
    b=json.loads((inputs/"bybit_prepared_inputs.json").read_bytes());e=json.loads((inputs/"bybit_october_input_extension.json").read_bytes())
    expected=[(b,"input_digest","fba66860376d9ad24af7a2388e878db0dfdbae16468de9381ef6a95f95563ffe"),(e,"digest","17f3101579ebd301cda074174ed4154e772d15d6b2ef2e17513d73b1dc31798c")]
    for value,key,sha in expected:
        if value[key]!=sha or digest({k:v for k,v in value.items() if k!=key})!=sha:raise ValueError("input_substitution")
    rows=b["rows"]+e["rows"]
    lp=source/"docs/evidence/lbank-mr40-exact30-20261021"
    raw=(lp/"lbank_kline_response.json").read_bytes();receipt=json.loads((lp/"source_receipt.json").read_bytes())
    if hashlib.sha256(raw).hexdigest()!=receipt["body_sha256"]:raise ValueError("lbank_source_changed")
    native=code["validator"](json.loads(raw,parse_float=str)["data"])
    lbank=sorted(([r[0]*1000,*r[1:]] for r in native if r[0]*1000<base.ms(policy["lbank30"][1])),key=lambda r:r[0])
    if digest(rows)!="a458d9f83df633df8ee5cab5f2a19de41c4c79c61185b5abd258fdefa80d575a" or digest(lbank)!="7274373a6ff9e1a060da4c18dffe9da69436345657505cd52f768f11d04ab278":
        raise ValueError("frozen_price_frame_changed")
    data=prepare(rows,base,code);ldata=prepare(lbank,base,code)
    output.mkdir(parents=True)
    results=[];counter=0;main_curves={};selection=None;folds=[];baseline_checks=[]

    def indices(frame,dates):
        start=next((i for i,r in enumerate(frame) if r[0]==base.ms(dates[0])),len(frame))
        end=next((i for i,r in enumerate(frame) if r[0]==base.ms(dates[1])),len(frame))
        if start<181 or start>=end or [r[0] for r in frame[start:end]]!=list(range(base.ms(dates[0]),base.ms(dates[1]),STEP)):
            raise ValueError("incomplete_window")
        return start,end

    with gzip.open(output/"all_runs.jsonl.gz","wb",compresslevel=6) as stream:
        def window(venue,frame,fdata,label,dates,capital,profiles=None,only=None,ordering=True):
            nonlocal counter
            start,end=indices(frame,dates)
            signal={entry:base.targets(frame,fdata,entry,start,end) for entry in ("baseline","confirm3")}
            records=[]
            for case in cases:
                if only and case["id"] not in only:continue
                for profile in profiles or policy["profiles"]:
                    result=simulate(frame,fdata,signal[case["entry"]],case,start,end,profile,capital,stop_first=ordering)
                    metric={"venue":venue,"window":label,**result["metrics"]}
                    results.append(metric);records.append(metric);counter+=1
                    key=f"{venue}/{label}/{capital}/{case['id']}/{profile['id']}"
                    if venue=="Bybit" and label=="full" and capital==10000 and profile["id"]=="normal":main_curves[case["id"]]=result["equity"]
                    witness={"key":key,"metrics":metric,"fills":result["fills"],"positions":result["positions"],
                        "equity_sha256_6dp":digest([format(x,".6f") for x in result["equity"]])}
                    stream.write(canonical(witness)+b"\n")
                    if case["id"]=="baseline_a100" and label in ("full","lbank30") and profile["id"]!="close_confirmed":
                        legacy=base.simulate(frame,fdata,"baseline",start,end,profile,capital)
                        error=max(abs(a-b) for a,b in zip(result["equity"],legacy["equity"]))
                        if error>1e-7 or [(f["fill_ms"],f["side"]) for f in result["fills"]]!=[(f["fill_ms"],f["side"]) for f in legacy["fills"]]:raise ValueError("baseline_execution_drift")
                        baseline_checks.append({"key":key,"maximum_equity_error":error})
            print(json.dumps({"completed_window":f"{venue}/{label}/{capital}","ledger_replays":counter}),flush=True)
            return records

        for capital in policy["capitals_usdt"]:window("Bybit",rows,data,"training",policy["training"],capital)
        training=[x for x in results if x["window"]=="training" and x["capital_usdt"]==10000]
        selection=select(training,cases)
        (output/"selection.json").write_bytes(canonical(selection)+b"\n")
        print(json.dumps({"training_selection_locked":selection}),flush=True)
        for capital in policy["capitals_usdt"]:
            for label in ("evaluation","full","year2026"):window("Bybit",rows,data,label,policy[label],capital)
        bounds=policy["walk_forward"]
        for n,(begin,finish) in enumerate(zip(bounds,bounds[1:])):
            train=window("Bybit",rows,data,f"fold{n}_train",["2023-01-01",begin],10000,policy["profiles"][:2])
            pick=select(train,cases)
            test=window("Bybit",rows,data,f"fold{n}_test",[begin,finish],10000,policy["profiles"][:2])
            folds.append({"start":begin,"end_exclusive":finish,"selection":pick,
                "results":[x for x in test if x["case"] in {"baseline_a100",pick["profit"],pick["efficiency"]}]})
        for capital in policy["capitals_usdt"]:window("LBank",lbank,ldata,"lbank30",policy["lbank30"],capital)
        main_count=counter
        picked={"baseline_a100",selection["profit"],selection["efficiency"]}
        for venue,frame,fdata,label,dates in (("Bybit",rows,data,"ambiguous_full",policy["full"]),("Bybit",rows,data,"ambiguous_evaluation",policy["evaluation"]),("LBank",lbank,ldata,"ambiguous_lbank30",policy["lbank30"])):
            window(venue,frame,fdata,label,dates,10000,policy["profiles"][:1],picked,False)
    prefix_checks=0
    start,_=indices(rows,policy["evaluation"])
    for cut in (start+239,len(rows)-71):
        pdata=prepare(rows[:cut],base,code)
        full_signals={k:base.targets(rows,data,k,start,len(rows)) for k in ("baseline","confirm3")}
        short_signals={k:base.targets(rows[:cut],pdata,k,start,cut) for k in ("baseline","confirm3")}
        for case in cases:
            for profile in (policy["profiles"][0],policy["profiles"][3]):
                full=simulate(rows,data,full_signals[case["entry"]],case,start,len(rows),profile,500,liquidate=False)
                short=simulate(rows[:cut],pdata,short_signals[case["entry"]],case,start,cut,profile,500,liquidate=False)
                if short["fills"]!=[f for f in full["fills"] if f["bar_index"]<cut] or short["equity"]!=full["equity"][:cut-start]:raise ValueError("future_dependent_execution")
                prefix_checks+=1
    def metric(name,profile,label="evaluation"):
        return next(x for x in results if x["venue"]=="Bybit" and x["window"]==label and x["capital_usdt"]==10000 and x["case"]==name and x["profile"]==profile)
    def score(name):
        normal,stress=metric(name,"normal"),metric(name,"stress")
        dd=max(normal["max_close_drawdown_pct"],stress["max_close_drawdown_pct"])
        return min(normal["cagr_pct"],stress["cagr_pct"])/dd if dd and stress["cagr_pct"]>0 else -math.inf
    bp,bn=metric("baseline_a100","stress"),metric("baseline_a100","normal")
    profit=selection["profit"];eff=selection["efficiency"]
    worst=lambda name:max(metric(name,p)["max_close_drawdown_pct"] for p in ("normal","stress"))
    profit_success=profit!="baseline_a100" and metric(profit,"normal")["net_pnl_usdt"]>=bn["net_pnl_usdt"] and metric(profit,"stress")["net_pnl_usdt"]>=bp["net_pnl_usdt"] and worst(profit)<=1.10*worst("baseline_a100")
    eff_success=eff!="baseline_a100" and score(eff)>0 and (score("baseline_a100")<=0 or score(eff)>=1.10*score("baseline_a100")) and metric(eff,"normal")["net_pnl_usdt"]>=.75*bn["net_pnl_usdt"] and metric(eff,"normal")["max_close_drawdown_pct"]<=.80*bn["max_close_drawdown_pct"]
    compound={}
    for profile in ("normal","stress"):
        for method in ("baseline","profit","efficiency"):
            value=10000.
            for fold in folds:
                name="baseline_a100" if method=="baseline" else fold["selection"][method]
                value*=1+next(x["net_return_pct"] for x in fold["results"] if x["case"]==name and x["profile"]==profile)/100
            compound[profile+"/"+method]=value-10000
    report={"schema":"nexus.mr40-rr-sizing-results.v2","protocol_commit":protocol_commit,"code_commit":code_commit,
        "policy_sha256":hashlib.sha256(policy_path.read_bytes()).hexdigest(),"driver_sha256":hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "base_driver_sha256":BASE_SHA,"data":{"Bybit":{"bars":len(rows),"rows_sha256":digest(rows)},"LBank":{"bars":len(lbank),"rows_sha256":digest(lbank)}},
        "case_count":len(cases),"selection":selection,"evaluation_profit_success":bool(profit_success),"evaluation_efficiency_success":bool(eff_success),
        "main_ledger_replays":main_count,"diagnostic_ledger_replays":counter-main_count,"prefix_checks":prefix_checks,"baseline_parity_checks":baseline_checks,
        "results":results,"walk_forward":folds,"walk_forward_compounded_pnl_10000":compound,"authority":policy["authority"],"classification":policy["classification"]}
    report["result_digest"]=digest(report)
    (output/"results.json").write_bytes(canonical(report)+b"\n")
    (output/"full_normal_curves.json").write_bytes(canonical(main_curves)+b"\n")
    print(json.dumps({"selection":selection,"evaluation_profit_success":profit_success,"evaluation_efficiency_success":eff_success,"main_ledger_replays":main_count,"prefix_checks":prefix_checks,"digest":report["result_digest"]}),flush=True)
    return report


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    for key in ("source","inputs","output"):parser.add_argument("--"+key,type=Path,required=True)
    for key in ("protocol_commit","code_commit"):parser.add_argument("--"+key.replace("_","-"),required=True)
    run(**vars(parser.parse_args()))
