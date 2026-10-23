"""Preregistered ONE combination ablation for historical, non-executable MR40.

The ONLY novel candidate is Vol40 entry fraction + fixed 4% initial stop +
closed-bar +2% gross-entry stop arm. Other paths are fixed controls. No
new signal search, no parameter sweep, no exchange orders or actual fills.

Uses frozen previous baseline episode indices; those are not blind/out-of-
sample signals. Runs only when the baseline exactly replays prior ledger.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import math
import statistics
from collections import defaultdict
from datetime import datetime,timezone
from decimal import Decimal as D, ROUND_DOWN
from pathlib import Path

Q=D("0.00000001")
LOT=D("0.00001")
STEP=14_400_000
OHLC_SHA="a458d9f83df633df8ee5cab5f2a19de41c4c79c61185b5abd258fdefa80d575a"
LEDGER_SHA="2c7115bac4ae81cc5c21b9bfc96319d5bee79baa746074c92c998125a834331e"


def must(x,msg):
    if not x: raise ValueError(msg)


def canon(x):
    return json.dumps(x,sort_keys=True,separators=(",",":"),ensure_ascii=False,allow_nan=False).encode()


def sha256_file(path):
    h=hashlib.sha256()
    with open(path,"rb") as f:
        for part in iter(lambda:f.read(1<<20),b""):h.update(part)
    return h.hexdigest()


def date_ms(s):
    return int(datetime.fromisoformat(s).replace(tzinfo=timezone.utc).timestamp()*1000)


def inputs(folder,ledger_path,policy_path):
    p=json.loads(policy_path.read_bytes())
    must(p["schema"]=="nexus.mr40.one-combination-ablation.v1", "wrong_prereg_protocol")
    must([x["id"] for x in p["cases"]]==[
        "baseline","vol40_only","stop4_arm2_only","vol40_stop4_arm2"],"case_drift")
    must(p["inputs"]["ohlc_digest"]==OHLC_SHA and
         p["inputs"]["existing_ledger_sha256"]==LEDGER_SHA,"input_policy_drift")
    must(p["safety"]["live"] is False and p["safety"]["real_orders"] is False and
         p["safety"]["private_api"] is False and p["safety"]["auto_promote"] is False,
         "prohibited_mode")
    rows=(json.loads((folder/"bybit_prepared_inputs.json").read_bytes())["rows"]+
          json.loads((folder/"bybit_october_input_extension.json").read_bytes())["rows"])
    must(hashlib.sha256(canon(rows)).hexdigest()==OHLC_SHA,"OHLC_digest_mismatch")
    must(sha256_file(ledger_path)==LEDGER_SHA,"ledger_SHA_mismatch")
    refs={}
    with gzip.open(ledger_path,"rt",encoding="utf-8") as f:
        for line in f:
            item=json.loads(line);k=item["key"]
            if k["venue"]=="Bybit" and k["case"]=="baseline" and k["window"] in ("train","evaluation") and k["profile"] in ("normal","stress"):
                key=(k["window"],k["capital"],k["profile"])
                must(key not in refs,"duplicate_reference")
                refs[key]=item
    must(len(refs)==8,"missing_control_ledgers")
    return p,rows,refs


def scenario(rows,ref,cfg,case,capital,fee_bp,slip_bp,start,end):
    fee=D(fee_bp)/10000
    slip=D(slip_bp)/10000
    vol_target=None if case["vol_target"] is None else D(case["vol_target"])
    initial_stop=None if case["initial_stop"] is None else D(case["initial_stop"])
    arm2=case["arm2"]
    # Prior episode signals from frozen baseline; not generated with future outcomes.
    signals=set();epmap={}
    for d in ref["decisions"]:
        must(d["allowed"] is True, "baseline_has_veto")
        first=d["signal_index"];last=d["episode_last_index"]
        must(first<=last,"bad_episode")
        for j in range(first,last+1):
            must(j not in signals, "overlapping_episode")
            signals.add(j);epmap[j]=first
    must(len(ref["decisions"])==len(ref["positions"]),"episode_position_count_mismatch")

    cash=D(capital);held=D(0);stop=None;entry=None;blocked=None
    fills=[];positions=[];equity=[];low_marks=[];arms=0;stops=0;gaps=0
    peak=float(capital);max_low_dd=0.;skips=0
    vol_cache={}
    def volatility(j):
        if j not in vol_cache:
            must(j>=180,"insufficient_vol_history")
            xs=[float(rows[k][4]) for k in range(j-180,j+1)]
            must(min(xs)>0,"bad_vol_close")
            vol_cache[j]=statistics.pstdev(math.log(b/a) for a,b in zip(xs,xs[1:]))*math.sqrt(365.25*6)
        return vol_cache[j]

    def fill(side,i,j,reference,reason,stop_reference=None):
        nonlocal cash,held,stop,entry,skips
        reference=D(str(reference));buy=(side=="buy")
        px=(reference*(1+slip if buy else 1-slip)).quantize(Q)
        before=cash
        allocation=None
        if buy:
            allocation=D(1)
            if vol_target is not None:
                vol=volatility(j)
                if vol>0:allocation=min(D(1),vol_target/D(str(vol)))
            must(D(0)<allocation<=D(1),"bad_allocation")
            budget=cash*allocation
            qty=(budget/(px*(1+fee))/LOT).to_integral_value(rounding=ROUND_DOWN)*LOT
            while qty>=LOT:
                nt=(qty*px).quantize(Q);fc=(nt*fee).quantize(Q)
                if nt+fc<=budget:break
                qty-=LOT
            if qty<LOT or qty*reference<1:
                skips+=1
                return False
        else:
            qty=held
            must(qty>=LOT and qty*reference>=1,"dust_exit")
        nt=(qty*px).quantize(Q);fc=(nt*fee).quantize(Q)
        after=before-nt-fc if buy else before+nt-fc
        must(after>=0,"negative_cash")
        stamp=rows[i][0]+(STEP if reason=="terminal_close" else 0)
        if j is not None:
            must(j==i-1 and rows[j][0]+STEP<=stamp,"future_signal")
        event={
            "side":side,"bar_index":i,"fill_ms":stamp,"signal_index":j,
            "reason":reason,"quantity":str(qty),"reference":str(reference),
            "price":str(px),"notional":str(nt),"fee":str(fc),
            "cash_before":str(before),"cash_after":str(after)
        }
        if stop_reference is not None: event["stop_level"]=str(stop_reference)
        fills.append(event);cash=after
        if buy:
            must(not held,"duplicate_buy")
            held=qty;entry=event
            stop=px*(D(1)-initial_stop) if initial_stop is not None else None
        else:
            must(held==qty and entry is not None,"bad_sell")
            held=D(0)
            positions.append({
                "entry":entry,"exit":event,
                "net_pnl_usdt":float(cash-D(entry["cash_before"])),
                "entry_episode":entry["signal_index"],
            })
            entry=None;stop=None
        return True

    for i in range(start,end):
        j=i-1
        desired=j in signals
        episode=epmap.get(j)
        if blocked is not None and episode!=blocked:blocked=None
        locked=(episode is not None and episode==blocked)
        close=D(str(rows[i][4]));low=D(str(rows[i][3]));op=D(str(rows[i][1]))
        must(op>0 and close>0 and low>0 and low<=min(op,close) and D(str(rows[i][2]))>=max(op,close),"invalid_4h")
        exit_now=False

        if held and not desired:
            fill("sell",i,j,op,"natural_exit")
            exit_now=True
        elif desired and not held and not locked:
            if not fill("buy",i,j,op,"episode_entry"):
                blocked=episode
        elif held and desired:
            if arm2 and entry is not None and j>=entry["bar_index"]:
                prior_close=D(str(rows[j][4]))
                entry_price=D(entry["price"])
                if prior_close>=entry_price*D("1.02") and (stop is None or entry_price>stop):
                    stop=entry_price
                    arms+=1
            if stop is not None:
                if op<=stop:
                    oldstop=stop
                    fill("sell",i,j,op,"stop_gap",oldstop)
                    blocked=episode;exit_now=True;stops+=1;gaps+=1
                elif low<=stop:
                    oldstop=stop
                    fill("sell",i,j,oldstop,"stop_hit",oldstop)
                    blocked=episode;exit_now=True;stops+=1
        if held and entry is not None and entry["bar_index"]==i and stop is not None:
            if low<=stop:
                oldstop=stop
                fill("sell",i,None,oldstop,"stop_hit",oldstop)
                blocked=episode;exit_now=True;stops+=1

        equity_now=float(cash+held*close)
        low_now=float(cash+held*low)
        if exit_now and fills and fills[-1]["bar_index"]==i and fills[-1]["reason"]=="stop_hit":
            sell=fills[-1]
            low_now=min(low_now,float(D(sell["cash_before"])+D(sell["quantity"])*D(sell["stop_level"])))
        max_low_dd=max(max_low_dd,max(0.,100*(1-low_now/peak)))
        peak=max(peak,equity_now)
        equity.append(equity_now);low_marks.append(low_now)

    if held:
        # Final mandatory liquidation; does not use future price.
        fill("sell",end-1,None,rows[end-1][4],"terminal_close")
        equity[-1]=float(cash)

    # Separate chronological and fee consistency oracle for our NEW run.
    oracle_cash=D(capital);oracle_qty=D(0)
    for e in fills:
        qty=D(e["quantity"]);px=D(e["price"]);reference=D(e["reference"])
        expected_px=(reference*(1+slip if e["side"]=="buy" else 1-slip)).quantize(Q)
        nt=(qty*expected_px).quantize(Q);commission=(nt*fee).quantize(Q)
        must(px==expected_px and nt==D(e["notional"]) and commission==D(e["fee"]),
             "independent_fill_cost_drift")
        must(D(e["cash_before"])==oracle_cash,"oracle_prior_cash_mismatch")
        if e["side"]=="buy":
            must(oracle_qty==0,"oracle_double_buy")
            oracle_cash-=nt+commission;oracle_qty+=qty
        else:
            must(oracle_qty==qty,"oracle_sell_quantity_mismatch")
            oracle_cash+=nt-commission;oracle_qty=D(0)
        must(oracle_cash==D(e["cash_after"]),"oracle_after_cash_mismatch")
    must(oracle_cash==cash and oracle_qty==0,"oracle_terminal_mismatch")
    must(abs(sum(p["net_pnl_usdt"] for p in positions)-(float(cash)-capital))<1e-6,"position_PNL_sum_drift")
    close_peak=float(capital);max_dd=0.;longest=under=0
    for mark in equity:
        close_peak=max(close_peak,mark)
        max_dd=max(max_dd,100*(1-mark/close_peak))
        under=under+1 if mark<close_peak-1e-8 else 0
        longest=max(longest,under)
    result={
        "net_pnl_usdt":float(cash)-capital,
        "max_close_drawdown_pct":max_dd,
        "max_intrabar_low_bound_pct":max_low_dd,
        "longest_underwater_days":longest/6,
        "fees_usdt":float(sum(D(e["fee"]) for e in fills)),
        "closed_positions":len(positions),
        "stops":stops,"stop_gaps":gaps,"ratchets":arms,"skips":skips,
        "fills":len(fills),
        "equity_digest":hashlib.sha256(canon([format(v,".6f") for v in equity])).hexdigest()
    }
    if case["id"]=="baseline":
        prior_fills=ref["fills"]
        must(len(prior_fills)==len(fills),"frozen_control_fill_count")
        # Compare all ledger fields, including buy-side sizing, fees, stamps and cash.
        for expected,got in zip(prior_fills,fills):
            must(expected==got,"frozen_baseline_trade_ledger_mismatch")
        must(result["equity_digest"]==ref["equity_digest"],"frozen_baseline_curve_mismatch")
    return result,positions


def main():
    ap=argparse.ArgumentParser()
    for name in ("inputs","ledger","protocol","output"):
        ap.add_argument("--"+name,type=Path,required=True)
    a=ap.parse_args()
    must(not a.output.exists(),"refuse_overwrite")
    p,rows,refs=inputs(a.inputs,a.ledger,a.protocol)
    out=[]
    for window,rng in p["windows"].items():
        s=next((i for i,x in enumerate(rows) if x[0]==date_ms(rng[0])),-1)
        en=next((i for i,x in enumerate(rows) if x[0]==date_ms(rng[1])),len(rows))
        must(s>=181 and en>s and rows[en-1][0]+STEP==date_ms(rng[1]),"window_mismatch")
        for capital in p["capital_usdt"]:
            for prof_name,pr in p["profiles"].items():
                reference=refs[(window,capital,prof_name)]
                case_runs={}
                for case in p["cases"]:
                    stats,positions=scenario(rows,reference,p,case,capital,pr["fee_bp"],pr["slip_bp"],s,en)
                    case_runs[case["id"]]={"metrics":stats,"positions":positions}
                baseline=case_runs["baseline"]
                bs=[x for x in baseline["positions"] if x["net_pnl_usdt"]>0]
                original_winning_pnl=sum(x["net_pnl_usdt"] for x in bs)
                for case in p["cases"]:
                    name=case["id"]
                    item=case_runs[name];matched={x["entry_episode"]:x for x in item["positions"]}
                    retained=[matched[x["entry_episode"]] for x in bs if x["entry_episode"] in matched and matched[x["entry_episode"]]["net_pnl_usdt"]>0]
                    retained_count=len(retained)/len(bs) if bs else 1.0
                    retained_pnl=sum(x["net_pnl_usdt"] for x in retained)/original_winning_pnl if original_winning_pnl>0 else 1.0
                    vals=item["metrics"]
                    out.append({
                        "window":window,"capital":capital,"profile":prof_name,"case":name,
                        **{k:vals[k] for k in ("net_pnl_usdt","max_close_drawdown_pct",
                            "max_intrabar_low_bound_pct","longest_underwater_days",
                            "fees_usdt","closed_positions","stops","stop_gaps","ratchets","skips")},
                        "baseline_winner_count_retained_fraction":retained_count,
                        "baseline_winning_pnl_retained_fraction":retained_pnl,
                        "largest_absolute_trade_pnl_share":(
                            max((abs(x["net_pnl_usdt"]) for x in item["positions"]),default=0)/
                            max(sum(abs(x["net_pnl_usdt"]) for x in item["positions"]),1e-12)),
                        "baseline_control_ledger_matched": True,
                    })
    # Qualification gates fixed in the preregistration, never optimize rank.
    combo="vol40_stop4_arm2"; qualification={}
    for capital in p["capital_usdt"]:
        vals=[]
        for window in ("train","evaluation"):
            for profile in ("normal","stress"):
                group={r["case"]:r for r in out if (r["capital"],r["window"],r["profile"])==(capital,window,profile)}
                c=group[combo];b=group["baseline"];v=group["vol40_only"];stop=group["stop4_arm2_only"]
                pass_now=(
                    c["net_pnl_usdt"]>=max(b["net_pnl_usdt"],v["net_pnl_usdt"],stop["net_pnl_usdt"])
                    and c["max_close_drawdown_pct"]<=min(v["max_close_drawdown_pct"],stop["max_close_drawdown_pct"],0.9*b["max_close_drawdown_pct"])
                    and c["baseline_winner_count_retained_fraction"]>=.7
                    and c["baseline_winning_pnl_retained_fraction"]>=.7
                )
                vals.append({"window":window,"profile":profile,"pass":pass_now})
        qualification[str(capital)]={"all_pass":all(x["pass"] for x in vals),"checks":vals}
    report={
        "schema":"nexus.mr40.one-combination-ablation.results.v1",
        "source_ohlc_hash":OHLC_SHA,
        "source_baseline_ledger_hash":LEDGER_SHA,
        "historically_seen":True,"genuine_forward_oos":False,
        "simulated_OHLC_stop_fill_is_not_verified":True,
        "paper_changed":False,"orders_placed":0,"promote":False,"merge":False,
        "cases":out,"novel_combination_qualification":qualification
    }
    report["digest"]=hashlib.sha256(canon(report)).hexdigest()
    a.output.parent.mkdir(parents=True,exist_ok=True)
    a.output.write_text(json.dumps(report,ensure_ascii=False,sort_keys=True,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"rows":len(out),"digest":report["digest"],"qualification":qualification,
                      "evaluation_10000_normal":[{k:x[k] for k in ("case","net_pnl_usdt","max_close_drawdown_pct","stops","ratchets","baseline_winning_pnl_retained_fraction")} for x in out if x["window"]=="evaluation" and x["capital"]==10000 and x["profile"]=="normal"],
                      "evaluation_10000_stress":[{k:x[k] for k in ("case","net_pnl_usdt","max_close_drawdown_pct")} for x in out if x["window"]=="evaluation" and x["capital"]==10000 and x["profile"]=="stress"]
                      },ensure_ascii=False))


if __name__=="__main__":
    main()
