"""Bounded, preregistered MR40 model development. Offline research only."""
from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal, ROUND_DOWN
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import statistics

STEP = 14_400_000
DAY = 86_400_000
D = Decimal
QUANTUM = D("0.00000001")
LOT = D("0.00001")
VARIANTS = ("baseline", "confirm3", "trend200", "exit_m05", "stop5", "vol20", "confirm3_stop5", "cash50_control")


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def ms(value):
    return int(datetime.fromisoformat(value).replace(tzinfo=timezone.utc).timestamp()*1000)


def utc(value):
    return datetime.fromtimestamp(value/1000, timezone.utc).isoformat()


def load_code(source):
    path = source/"research/nexus_mr40_lbank_exact30_v1.py"
    spec = importlib.util.spec_from_file_location("improve_frozen_loader", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.load_sources(source)


def features(rows, code):
    code["core"].validate_frame(rows)
    raw = code["core"].targets(rows)
    if raw != code["core"].decimal_targets(rows):
        raise ValueError("independent_raw_signal_mismatch")
    close = [float(r[4]) for r in rows]
    z, trend, volatility, episode = [], [], [], []
    counter = 0
    log_returns = [0.0]+[math.log(b/a) for a,b in zip(close, close[1:])]
    for i, value in enumerate(close):
        past = close[max(0,i-40):i]
        std = statistics.pstdev(past) if len(past)==40 else 0
        z.append((value-math.fsum(past)/40)/std if std else None)
        trend.append(math.fsum(close[i-200:i])/200 if i>=200 else None)
        volatility.append(statistics.pstdev(log_returns[i-179:i+1])*math.sqrt(365.25*6) if i>=180 else None)
        if raw[i] and (i==0 or not raw[i-1]): counter += 1
        episode.append(counter if raw[i] else 0)
    return {"raw":raw, "close":close, "z":z, "trend":trend, "volatility":volatility, "episode":episode}


def targets(rows, data, variant, start, end):
    if variant not in VARIANTS: raise ValueError("unregistered_variant")
    output = [0]*len(rows)
    in_episode, admitted, active, exhausted, first = False, False, False, False, 0
    for i in range(start-1, end):
        if not data["raw"][i]:
            in_episode, admitted, active, exhausted = False, False, False, False
            continue
        if not in_episode:
            in_episode, first = True, i
            admitted = i>=180 and D(str(rows[i][4]))>=D(str(rows[i-180][4]))
            if variant=="trend200":
                admitted = admitted and i>=200 and D(str(rows[i][4]))>=sum(D(str(r[4])) for r in rows[i-200:i])/200
        if admitted and not exhausted:
            if variant in ("confirm3", "confirm3_stop5") and not active:
                if i-first<3 and data["close"][i]>data["close"][i-1]: active = True
                elif i-first>=2: exhausted = True
            else:
                active = True
            if variant=="exit_m05" and data["z"][i] is not None and data["z"][i]>=-0.5:
                active, exhausted = False, True
        output[i] = int(admitted and active and not exhausted)
    return output


def simulate(rows, data, variant, start, end, profile, capital=10000, *, liquidate=True):
    if not 1<=start<end<=len(rows): raise ValueError("invalid_window")
    signal = targets(rows,data,variant,start,end)
    fee, slip = D(str(profile["fee_bps"]))/10000, D(str(profile["slippage_bps"]))/10000
    lag = profile["lag_bars"]
    if lag not in (1,2): raise ValueError("unregistered_delay")
    cash, quantity, opening = D(capital), D(0), None
    fills, positions, curve, lows = [], [], [], []
    blocked, skipped, exposure = None, 0, 0

    def fill(side, i, reference, j, reason, allocation=D(1)):
        nonlocal cash, quantity, opening
        reference = D(str(reference))
        price = (reference*(1+slip if side=="buy" else 1-slip)).quantize(QUANTUM)
        before = cash
        if side=="buy":
            budget = cash*allocation
            units = (budget/((1+fee)*price)/LOT).to_integral_value(rounding=ROUND_DOWN)*LOT
            if units<LOT or units*reference<1: return False
        else:
            units, budget = quantity, None
            if units<LOT or units*reference<1: raise ValueError("exit_below_venue_minimum")
        notional = (units*price).quantize(QUANTUM)
        commission = (notional*fee).quantize(QUANTUM)
        after = before-notional-commission if side=="buy" else before+notional-commission
        if after<0: raise ValueError("cash_budget_exceeded")
        stamp = rows[i][0]+(STEP if reason=="terminal_close" else 0)
        if j is not None and rows[j][0]+STEP>stamp: raise ValueError("future_information_fill")
        item = {"side":side,"bar_index":i,"fill_ms":stamp,"filled_utc":utc(stamp),
                "signal_index":j,"reason":reason,"quantity":str(units),"reference":str(reference),
                "price":str(price),"notional":str(notional),"fee":str(commission),
                "cash_before":str(before),"cash_after":str(after),"allocation":str(allocation),
                "slippage_cost":str(abs(units*(price-reference)))}
        fills.append(item)
        if side=="buy":
            opening = item
            quantity = units
        else:
            pnl = after-D(opening["cash_before"])
            positions.append({"entry":opening,"exit":item,"net_pnl_usdt":float(pnl),
                "account_return_pct":float(pnl/D(opening["cash_before"])*100),
                "holding_hours":(stamp-opening["fill_ms"])/3_600_000})
            quantity, opening = D(0), None
        cash = after
        return True

    for i in range(start,end):
        j = i-lag
        desired = signal[j] if j>=0 else 0
        episode = data["episode"][j] if j>=0 else 0
        reason = "early_mean_exit" if variant=="exit_m05" else "natural_exit"
        if quantity and desired and variant in ("stop5", "confirm3_stop5") and j>=opening["bar_index"]:
            if D(str(rows[j][4]))<=D(opening["reference"])*D("0.95"):
                desired, blocked, reason = 0, episode, "close_stop5"
        if episode and episode==blocked: desired = 0
        if quantity and not desired:
            fill("sell",i,rows[i][1],j,reason)
        elif desired and not quantity:
            allocation = D("0.5") if variant=="cash50_control" else D(1)
            if variant=="vol20":
                vol = data["volatility"][j]
                allocation = D(str(min(1.0,0.20/vol))) if vol and vol>0 else D(1)
            if not fill("buy",i,rows[i][1],j,"episode_entry",allocation):
                skipped += 1
                blocked = episode
        curve.append(float(cash+quantity*D(str(rows[i][4]))))
        lows.append(float(cash+quantity*D(str(rows[i][3]))))
        exposure += int(quantity>0)
    if quantity and liquidate:
        fill("sell",end-1,rows[end-1][4],None,"terminal_close")
        curve[-1] = float(cash)
    verify_ledger(rows,start,end,profile,capital,fills,curve)
    peak, worst, low_worst, longest, underwater = float(capital), 0.0, 0.0, 0, 0
    monthly = defaultdict(float)
    previous = float(capital)
    for i, value in enumerate(curve):
        low_worst = max(low_worst,1-lows[i]/peak)
        peak = max(peak,value)
        worst = max(worst,1-value/peak)
        underwater = underwater+1 if value<peak-1e-8 else 0
        longest = max(longest,underwater)
        monthly[utc(rows[start+i][0])[:7]] += value-previous
        previous = value
    if liquidate and abs(sum(p["net_pnl_usdt"] for p in positions)-(curve[-1]-capital))>1e-6:
        raise ValueError("position_pnl_reconciliation")
    gains = sum(max(0,p["net_pnl_usdt"]) for p in positions)
    losses = -sum(min(0,p["net_pnl_usdt"]) for p in positions)
    days = (end-start)*STEP/DAY
    metrics = {"variant":variant,"profile":profile["id"],"capital_usdt":capital,
        "start_utc":utc(rows[start][0]),"end_exclusive_utc":utc(rows[end-1][0]+STEP),
        "net_pnl_usdt":curve[-1]-capital,"net_return_pct":(curve[-1]/capital-1)*100,
        "cagr_pct":((curve[-1]/capital)**(365.25/days)-1)*100,"max_close_drawdown_pct":worst*100,
        "low_vs_prior_close_peak_drawdown_lower_bound_pct":max(worst,low_worst)*100,
        "longest_underwater_days":longest*STEP/DAY,"closed_positions":len(positions),"fills":len(fills),
        "terminal_exits":sum(p["exit"]["reason"]=="terminal_close" for p in positions),
        "stop_exits":sum(p["exit"]["reason"]=="close_stop5" for p in positions),
        "mean_position_pnl_usdt":statistics.mean(p["net_pnl_usdt"] for p in positions) if positions else None,
        "win_rate_pct":100*sum(p["net_pnl_usdt"]>0 for p in positions)/len(positions) if positions else None,
        "profit_factor":gains/losses if losses else None,"fees_usdt":float(sum((D(f["fee"]) for f in fills),D(0))),
        "slippage_usdt":float(sum((D(f["slippage_cost"]) for f in fills),D(0))),
        "exposure_pct":100*exposure/(end-start),"skipped_minimum_order_entries":skipped,
        "open_quantity_btc":str(quantity),"monthly_pnl_usdt":dict(monthly),"ledger_replay_verified":True}
    return {"metrics":metrics,"fills":fills,"positions":positions,"equity":curve}


def verify_ledger(rows,start,end,profile,capital,fills,curve):
    """Rebuild every mark independently from immutable fills, not simulator state."""
    fee, slip = D(str(profile["fee_bps"]))/10000, D(str(profile["slippage_bps"]))/10000
    cash, held = D(capital), D(0)
    grouped = defaultdict(list)
    for fill in fills: grouped[fill["bar_index"]].append(fill)
    for i in range(start,end):
        terminal = False
        for event in grouped[i]:
            buy = event["side"]=="buy"
            is_terminal = event["reason"]=="terminal_close"
            reference = D(str(rows[i][4] if is_terminal else rows[i][1]))
            price = (reference*(1+slip if buy else 1-slip)).quantize(QUANTUM)
            units = D(event["quantity"])
            if units<=0 or units%LOT: raise ValueError("invalid_venue_lot")
            if buy:
                expected = (cash*D(event["allocation"])/((1+fee)*price)/LOT).to_integral_value(rounding=ROUND_DOWN)*LOT
                if held or units!=expected or reference*units<1: raise ValueError("entry_budget_or_minimum")
            elif not held or units!=held:
                raise ValueError("orphan_or_partial_exit")
            notional = (units*price).quantize(QUANTUM)
            commission = (notional*fee).quantize(QUANTUM)
            if (str(price),str(notional),str(commission),str(cash))!=(event["price"],event["notional"],event["fee"],event["cash_before"]):
                raise ValueError("ledger_price_or_cashflow_changed")
            cash += -notional-commission if buy else notional-commission
            held = units if buy else D(0)
            if str(cash)!=event["cash_after"] or cash<0: raise ValueError("ledger_cash_mismatch")
            if event["signal_index"] is not None:
                if event["signal_index"]!=i-profile["lag_bars"]: raise ValueError("wrong_signal_delay")
                if rows[event["signal_index"]][0]+STEP>event["fill_ms"]: raise ValueError("lookahead")
            terminal |= is_terminal
        mark = cash if terminal else cash+held*D(str(rows[i][4]))
        if abs(float(mark)-curve[i-start])>1e-7: raise ValueError("independent_equity_mismatch")


def choose(records):
    by_variant = {v:{r["profile"]:r for r in records if r["variant"]==v} for v in VARIANTS}
    def score(v):
        a,b = (by_variant[v][p] for p in ("normal","stress"))
        risk = max(a["max_close_drawdown_pct"],b["max_close_drawdown_pct"])
        return min(a["cagr_pct"],b["cagr_pct"])/risk if risk>0 and b["cagr_pct"]>0 else -math.inf
    base_score = score("baseline")
    base = by_variant["baseline"]
    eligible = []
    for v in VARIANTS[1:-1]:
        data = by_variant[v]
        better = (data["stress"]["cagr_pct"]>=base["stress"]["cagr_pct"] and
            max(data[p]["max_close_drawdown_pct"] for p in ("normal","stress"))<=
            max(base[p]["max_close_drawdown_pct"] for p in ("normal","stress")))
        if better and score(v)>0 and (base_score<=0 or score(v)>=1.10*base_score): eligible.append(v)
    winner = max(eligible,key=score) if eligible else "baseline"
    return {"selected":winner,"eligible":eligible,"scores":{v:(score(v) if math.isfinite(score(v)) else None) for v in VARIANTS}}


def run(source,inputs,output,protocol_commit,code_commit):
    if output.exists(): raise ValueError("refuse_result_overwrite")
    policy_path = source/"research/mr40_isolated_improvement_v1.json"
    policy = json.loads(policy_path.read_bytes())
    if tuple(v["id"] for v in policy["variants"])!=VARIANTS: raise ValueError("registered_variants_changed")
    for sha in (protocol_commit,code_commit):
        if len(sha)!=40 or any(c not in "0123456789abcdef" for c in sha): raise ValueError("exact_commits_required")
    code = load_code(source)
    base = json.loads((inputs/"bybit_prepared_inputs.json").read_bytes())
    ext = json.loads((inputs/"bybit_october_input_extension.json").read_bytes())
    for value,key,expected in ((base,"input_digest",policy["data"]["bybit_base_digest"]),(ext,"digest",policy["data"]["bybit_october_digest"])):
        if value[key]!=expected or digest({k:v for k,v in value.items() if k!=key})!=expected: raise ValueError("input_substitution")
    rows = base["rows"]+ext["rows"]
    old = json.loads((source/"docs/evidence/lbank-mr40-exact30-20261021/source_receipt.json").read_bytes())
    lbank_raw = (source/"docs/evidence/lbank-mr40-exact30-20261021/lbank_kline_response.json").read_bytes()
    if hashlib.sha256(lbank_raw).hexdigest()!=old["body_sha256"]: raise ValueError("lbank_source_changed")
    native = code["validator"](json.loads(lbank_raw,parse_float=str)["data"])
    lbank = sorted(([r[0]*1000,*r[1:]] for r in native if r[0]*1000<ms(policy["latest_lbank_window"][1])),key=lambda r:r[0])
    all_results, runs, checks = [], {}, {}

    def window(venue,frame,data,label,dates,capital,profiles=None):
        start,end = (next((i for i,r in enumerate(frame) if r[0]==ms(day)),len(frame)) for day in dates)
        if end==len(frame) and frame[-1][0]+STEP!=ms(dates[1]): raise ValueError("window_endpoint_missing")
        if start<181 or start>=end: raise ValueError("insufficient_warmup_or_window")
        if [r[0] for r in frame[start:end]]!=list(range(ms(dates[0]),ms(dates[1]),STEP)): raise ValueError("window_gap")
        records=[]
        for variant in VARIANTS:
            for profile in profiles or policy["profiles"]:
                result=simulate(frame,data,variant,start,end,profile,capital)
                key=f"{venue}/{label}/{capital}/{variant}/{profile['id']}"
                metric={"venue":venue,"window":label,**result["metrics"]}
                all_results.append(metric);records.append(metric);runs[key]=result
        return records

    data = features(rows,code)
    for capital in policy["capitals_usdt"]:
        window("Bybit",rows,data,"training",policy["training"],capital)
    selected = choose([r for r in all_results if r["venue"]=="Bybit" and r["window"]=="training" and r["capital_usdt"]==10000])
    output.mkdir(parents=True)
    (output/"selection.json").write_bytes(canonical(selected)+b"\n")
    print(json.dumps({"training_selection_locked_before_evaluation":selected}),flush=True)
    for capital in policy["capitals_usdt"]:
        for label,dates in (("locked",policy["locked_evaluation"]),("full",policy["full_window"]),("2026",["2026-01-01",policy["full_window"][1]])):
            window("Bybit",rows,data,label,dates,capital)
    folds=[]
    boundaries=["2024-01-01","2024-07-01","2025-01-01","2025-07-01","2026-01-01","2026-07-01","2026-10-20"]
    for n,(begin,finish) in enumerate(zip(boundaries,boundaries[1:])):
        train=window("Bybit",rows,data,f"fold{n}_train",["2023-01-01",begin],10000,policy["profiles"][:2])
        pick=choose(train)
        test=window("Bybit",rows,data,f"fold{n}_test",[begin,finish],10000,policy["profiles"][:2])
        folds.append({"start":begin,"end_exclusive":finish,"training_selection":pick,
            "selected_results":[r for r in test if r["variant"]==pick["selected"]],
            "baseline_results":[r for r in test if r["variant"]=="baseline"]})
    ldata=features(lbank,code)
    for capital in policy["capitals_usdt"]:
        window("LBank",lbank,ldata,"latest30",policy["latest_lbank_window"],capital)
    # Frozen unrounded engine control distinguishes venue-lot effects from signal drift.
    for venue,frame,fdata,dates in (("Bybit",rows,data,policy["full_window"]),("LBank",lbank,ldata,policy["latest_lbank_window"])):
        start=next(i for i,r in enumerate(frame) if r[0]==ms(dates[0]));end=len(frame)
        pure=targets(frame,fdata,"baseline",start,end)
        trusted,decisions=code["gate"].admit_episodes(frame,fdata["raw"],start-1,end)
        if pure!=trusted or trusted!=code["gate"].independent_admission(frame,fdata["raw"],start-1,end): raise ValueError("frozen_admission_drift")
        original=code["core"].simulate(frame,pure,start,end,10,5)
        independent=code["core"].independent_accounting(frame,pure,start,end,10,5)
        error=max(abs(a["equity"]-b) for a,b in zip(original["equity_curve"],independent["equity"]))
        if error>1e-7:raise ValueError("frozen_baseline_cashflow_drift")
        checks[venue]={"rows":len(frame),"rows_sha256":digest(frame),"frozen_baseline_unrounded_pnl_10000":original["metrics"]["net_pnl_usdt"],"frozen_signal_decimal_verified":True,"legacy_accounting_max_error":error}
    # Changing the future cannot alter past decisions/fills, including stop and volatility sizing.
    start=next(i for i,r in enumerate(rows) if r[0]==ms("2025-01-01"))
    prefix_count=0
    for cut in (start+181,start+701,len(rows)-101):
        prefix_data=features(rows[:cut],code)
        for variant in VARIANTS:
            full=simulate(rows,data,variant,start,len(rows),policy["profiles"][0],500,liquidate=False)
            prefix=simulate(rows[:cut],prefix_data,variant,start,cut,policy["profiles"][0],500,liquidate=False)
            if prefix["fills"]!=[f for f in full["fills"] if f["bar_index"]<cut] or prefix["equity"]!=full["equity"][:cut-start]: raise ValueError("future_dependent_execution")
            prefix_count+=1
    def locked(variant,profile):
        return next(r for r in all_results if r["venue"]=="Bybit" and r["window"]=="locked" and r["capital_usdt"]==10000 and r["variant"]==variant and r["profile"]==profile)
    winner=selected["selected"];candidate,baseline=locked(winner,"normal"),locked("baseline","normal")
    success=(winner!="baseline" and candidate["net_pnl_usdt"]>baseline["net_pnl_usdt"] and
        locked(winner,"stress")["net_pnl_usdt"]>=locked("baseline","stress")["net_pnl_usdt"] and
        candidate["max_close_drawdown_pct"]<=0.8*baseline["max_close_drawdown_pct"])
    stitched={}
    for profile in ("normal","stress"):
        for method in ("selected_results","baseline_results"):
            value=10000.0
            for fold in folds:value*=1+next(r["net_return_pct"] for r in fold[method] if r["profile"]==profile)/100
            stitched[profile+"/"+method]=value-10000
    result={"schema":"nexus.mr40-isolated-improvement-result.v1","protocol_commit":protocol_commit,"code_commit":code_commit,
        "policy_sha256":hashlib.sha256(policy_path.read_bytes()).hexdigest(),
        "driver_sha256":hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),"selection":selected,
        "locked_improvement_success":success,"checks":checks,"prefix_checks":prefix_count,"results":all_results,
        "walk_forward":folds,"walk_forward_compounded_pnl_10000":stitched,
        "research_only":True,"live_enabled":False,"exchange_orders":0,"paper_mutation":False,
        "independent_ledger_replays":len(runs),"classification":policy["classification"]}
    result["result_digest"]=digest(result)
    (output/"results.json").write_bytes(canonical(result)+b"\n")
    (output/"all_runs.json").write_bytes(canonical(runs)+b"\n")
    print(json.dumps({"selection":selected,"locked_improvement_success":success,"checks":checks,"ledger_replays":len(runs),"prefix_checks":prefix_count,"digest":result["result_digest"]}),flush=True)
    return result


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    for name in ("source","inputs","output"):parser.add_argument("--"+name,type=Path,required=True)
    for name in ("protocol_commit","code_commit"):parser.add_argument("--"+name.replace("_","-"),required=True)
    run(**vars(parser.parse_args()))
