"""One preregistered exposure-expiry diagnostic on the already-seen MR40 corpus."""
from __future__ import annotations
import argparse,csv,hashlib,importlib.util,json,math,platform,statistics
from datetime import datetime,timezone
from pathlib import Path
BASE_ENGINE_SHA="e9b898040d4680f128da330177df84e2f70f467cf5455d685247b27"
INPUT_DIGEST="fba66860376d9ad24af7a2388e878db0dfdbae16468de9381ef6a95f95563ffe"
BASE_RESULT_DIGEST="44ea00e4528ccbe3e420bd999152a36b58450565f8a45bb9489a3c79fe4b4514"
def canonical(v):return json.dumps(v,sort_keys=True,separators=(",",":"),ensure_ascii=False,allow_nan=False).encode()
def digest(v):return hashlib.sha256(canonical(v)).hexdigest()
def cap40(raw):
    """Forty active target bars per original long episode; reset only on raw flat."""
    if any(v not in (0,1) for v in raw):raise ValueError("binary original targets required")
    active=False;armed=True;entered=None;out=[];expiry=[]
    for i,value in enumerate(raw):
        expired=False
        if value==0:active=False;armed=True;entered=None
        elif active and i-entered>=40:active=False;armed=False;expired=True
        elif not active and armed:active=True;entered=i
        out.append(int(active));expiry.append(expired)
    return out,expiry
def annotate_exits(result,expired,lag):
    kinds={}
    for fill in result["fills"]:
        if fill["side"]=="sell" and fill["reason"]!="terminal_close":
            kind="time_cap_closed_bar_signal" if expired[fill["signal_index"]] else "mean_reversion_closed_bar_signal"
            fill["reason"]=kind;kinds[fill["bar_index"]]=kind
    for trade in result["positions"]:
        if trade["exit_reason"]!="terminal_close":trade["exit_reason"]=kinds[trade["exit_index"]]
    result["metrics"]["nonterminal_exits"]=result["metrics"].pop("natural_exits")
    result["metrics"]["time_cap_exits"]=sum(t["exit_reason"]=="time_cap_closed_bar_signal" for t in result["positions"])
    result["metrics"]["mean_reversion_exits"]=sum(t["exit_reason"]=="mean_reversion_closed_bar_signal" for t in result["positions"])
    if result["positions"] and max(t["holding_hours"] for t in result["positions"])>160+1e-9:raise AssertionError("time cap exceeded")
    return result
def load_base(base_root):
    path=base_root/"research"/"nexus_mean_reversion_40_m2_retest_v1.py"
    if hashlib.sha256(path.read_bytes()).hexdigest()!=BASE_ENGINE_SHA:raise ValueError("base engine substitution")
    spec=importlib.util.spec_from_file_location("mr40_frozen_base_engine",path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
    inputs=json.loads((base_root/"prepared_inputs.json").read_text(encoding="utf-8"))
    if inputs["input_digest"]!=INPUT_DIGEST or digest({k:v for k,v in inputs.items() if k!="input_digest"})!=INPUT_DIGEST:raise ValueError("input substitution")
    path=base_root/"verified_results"/"results.json"
    if not path.is_file():path=base_root/"recorded_results"/"results.json"
    report=json.loads(path.read_text(encoding="utf-8"))
    if report["result_digest"]!=BASE_RESULT_DIGEST or digest({k:v for k,v in report.items() if k!="result_digest"})!=BASE_RESULT_DIGEST:raise ValueError("baseline result substitution")
    contract=json.loads((base_root/"study_contract.json").read_text(encoding="utf-8"))
    m.validate_frame(inputs["rows"])
    return m,inputs,report,contract,path.parent
def summarize_losses(m,rows,report,result_root):
    study=next(r for r in report["results"] if r["cohort"]=="retrospective_42_months" and r["profile"]=="normal")
    trades=study["positions"];wins=[t for t in trades if t["net_pnl_usdt"]>0];losses=[t for t in trades if t["net_pnl_usdt"]<0]
    groups=[]
    for name,group in [("held_at_most_160h",[t for t in trades if t["holding_hours"]<=160]),("held_over_160h",[t for t in trades if t["holding_hours"]>160])]:
        groups.append({"group":name,"positions":len(group),"sum_position_net_pnl_usdt":sum(t["net_pnl_usdt"] for t in group),
                       "classification":"descriptive partition of realized trades, not a tradable exclusion rule"})
    details=[]
    buys={f["bar_index"]:f for f in study["fills"] if f["side"]=="buy"}
    for t in sorted(trades,key=lambda x:x["net_pnl_usdt"])[:10]:
        fill=buys[t["entry_index"]];last=t["exit_index"]+(t["exit_reason"]=="terminal_close")
        held=rows[t["entry_index"]:last];units=fill["quantity"]
        min_liquidatable=min(t["exit_cash"],min(units*float(r[3])*(1-.0005)*(1-.001) for r in held))
        max_liquidatable=max(t["exit_cash"],max(units*float(r[2])*(1-.0005)*(1-.001) for r in held))
        details.append({**t,"entry_utc":m.iso(t["entry_ms"]),"exit_utc":m.iso(t["exit_ms"]),
            "low_mark_max_adverse_pct_of_entry_cash":100*(min_liquidatable/t["entry_cash"]-1),
            "high_mark_max_favorable_pct_of_entry_cash":100*(max_liquidatable/t["entry_cash"]-1),
            "intrabar_high_low_order_known":False})
    values=[];peak=10000.0;peak_stamp=m.ms("2023-01-01");worst=0;episode=None;monthly={}
    with (result_root/"equity_curve.csv").open(encoding="utf-8",newline="") as source:
        for row in csv.DictReader(source):
            if row["cohort"]!="retrospective_42_months" or row["profile"]!="normal":continue
            value=float(row["equity"]);stamp=int(row["bar_open_ms"])+m.STEP
            values.append((stamp,value))
            if value>peak:peak=value;peak_stamp=stamp
            dd=1-value/peak
            if dd>worst:worst=dd;episode={"peak_utc":m.iso(peak_stamp),"peak_equity":peak,"trough_utc":m.iso(stamp),"trough_equity":value,"drawdown_pct":100*dd}
    episode["recovery_utc"]=next((m.iso(t) for t,v in values if t>m.ms(episode["trough_utc"]) and v>=episode["peak_equity"]),None)
    signal=m.targets(rows);start=next(i for i,r in enumerate(rows) if r[0]==m.ms("2023-01-01"));end=next(i for i,r in enumerate(rows) if r[0]==m.ms("2026-07-01"))
    cost=[]
    for label,fee,slip in [("no_cost",0,0),("fee_only",10,0),("slippage_only",0,5),("both_normal",10,5)]:
        out=m.simulate(rows,signal,start,end,fee,slip)
        cost.append({"profile":label,"fee_bps":fee,"slippage_bps":slip,"net_pnl_usdt":out["metrics"]["net_pnl_usdt"]})
    return {"baseline_result_digest":BASE_RESULT_DIGEST,"mean_winning_position_usdt":statistics.mean(t["net_pnl_usdt"] for t in wins),
            "mean_losing_position_usdt":statistics.mean(t["net_pnl_usdt"] for t in losses),
            "median_winner_holding_hours":statistics.median(t["holding_hours"] for t in wins),
            "median_loser_holding_hours":statistics.median(t["holding_hours"] for t in losses),
            "holding_groups":groups,"worst_positions":details,"worst_drawdown_episode":episode,"cost_diagnostic":cost}
def write_csv(path,records):
    with path.open("w",encoding="utf-8",newline="") as out:
        w=csv.DictWriter(out,fieldnames=list(records[0]),lineterminator="\n");w.writeheader();w.writerows(records)
def run(root,base_root,source_sha,prereg_sha):
    for sha in (source_sha,prereg_sha):
        if len(sha)!=40 or any(c not in "0123456789abcdef" for c in sha):raise ValueError("exact Git commit required")
    policy=json.loads((root/"study_contract.json").read_text(encoding="utf-8"))
    if policy["policy"]["maximum_signal_episode_bars"]!=40 or policy["authority"]!={"research_only":True,"auto_demo":False,"live_enabled":False,"orders":0}:raise ValueError("fixed policy boundary")
    m,inputs,baseline,base_contract,old_outputs=load_base(base_root);rows=inputs["rows"]
    diagnosis=summarize_losses(m,rows,baseline,old_outputs)
    raw=m.targets(rows);independent_raw=m.decimal_targets(rows)
    if raw!=independent_raw:raise AssertionError("base signal mismatch")
    candidate,expired=cap40(raw);independent_candidate,_=cap40(independent_raw)
    for cut in [40,130,1000,4000,8034,8220,8399]:
        if cap40(raw[:cut])[0]!=candidate[:cut]:raise AssertionError("future dependency")
    records=[];checks=[];summary=[];fills=[];trades=[];equity=[];monthly=[]
    profiles=[("normal",10,5,1),("stress",25,15,1),("zero_cost_diagnostic",0,0,1),("additional_4h_latency",10,5,2)]
    for cohort in base_contract["cohorts"]:
        cold=cohort["id"]=="july_legacy_control"
        if cold:
            prices=[r for r in rows if m.ms(cohort["start"])<=r[0]<m.ms(cohort["end_exclusive"])]
            target,expiry=cap40(m.targets(prices));independent_target,_=cap40(m.decimal_targets(prices));start=0;end=len(prices)
        else:
            prices=rows;target=candidate;expiry=expired;independent_target=independent_candidate
            start=next(i for i,r in enumerate(prices) if r[0]==m.ms(cohort["start"]))
            end=next((i for i,r in enumerate(prices) if r[0]==m.ms(cohort["end_exclusive"])),len(prices))
        for name,fee,slip,lag in profiles:
            out=annotate_exits(m.simulate(prices,target,start,end,fee,slip,lag=lag,skip_first=cold),expiry,lag)
            ref=m.independent_accounting(prices,independent_target,start,end,fee,slip,lag=lag,skip_first=cold)
            error=max(abs(a["equity"]-b) for a,b in zip(out["equity_curve"],ref["equity"]))
            if error>1e-7 or ref["fill_count"]!=out["metrics"]["fills"]:raise AssertionError("independent ledger mismatch")
            old=next(r for r in baseline["results"] if r["cohort"]==cohort["id"] and r["profile"]==name)
            labels={"cohort":cohort["id"],"profile":name}
            result={**labels,**out["metrics"],"base_net_pnl_usdt":old["net_pnl_usdt"],"base_max_close_drawdown_pct":old["max_close_drawdown_pct"],
                    "difference_net_pnl_usdt":out["metrics"]["net_pnl_usdt"]-old["net_pnl_usdt"],"monthly_attribution":out["monthly_attribution"],
                    "positions":out["positions"],"fills":out["fills"]}
            records.append(result);summary.append({k:v for k,v in result.items() if k not in ("positions","fills","monthly_attribution")})
            fills.extend({**labels,**v} for v in out["fills"]);trades.extend({**labels,**v} for v in out["positions"])
            equity.extend({**labels,**v} for v in out["equity_curve"]);monthly.extend({**labels,**v} for v in out["monthly_attribution"])
            checks.append({**labels,"decimal_accounting_pass":True,"maximum_absolute_equity_error_usdt":error})
            print(json.dumps({**labels,"net_pnl_usdt":result["net_pnl_usdt"],"base_net_pnl_usdt":old["net_pnl_usdt"],"drawdown_pct":result["max_close_drawdown_pct"],"time_cap_exits":result["time_cap_exits"],"positions":result["closed_positions"]}),flush=True)
    report={"schema":"nexus.mr40-cap40-diagnostic-results.v1","code_commit":source_sha,"preregistered_contract_commit":prereg_sha,
            "executed_utc":datetime.now(timezone.utc).isoformat(),"physical_worker":platform.node(),"baseline_result_digest":BASE_RESULT_DIGEST,
            "input_digest":INPUT_DIGEST,"diagnosis":diagnosis,"results":records,"independent_accounting_checks":checks,
            "classification":"EXPLORATORY_SEEN_DATA_NOT_INDEPENDENT_QUALIFICATION","parameter_search":False,"prospective":False,
            "research_only":True,"auto_demo":False,"live_enabled":False,"orders":0}
    report["source_files"]={}
    for rel,path in [("research/nexus_mean_reversion_40_m2_time_cap_v1.py",Path(__file__)),("research/mean_reversion_40_m2_time_cap_v1.json",root/"study_contract.json"),("tests/test_nexus_mean_reversion_40_m2_time_cap_v1.py",root/"tests"/"test_nexus_mean_reversion_40_m2_time_cap_v1.py")]:
        b=path.read_bytes();report["source_files"][rel]={"bytes":len(b),"sha256":hashlib.sha256(b).hexdigest(),"git_blob":hashlib.sha1(f"blob {len(b)}\0".encode()+b).hexdigest()}
    report["result_digest"]=digest(report)
    output=root/"results"
    if output.exists():raise ValueError("refuse overwrite")
    output.mkdir()
    (output/"results.json").write_text(json.dumps(report,separators=(",",":"),ensure_ascii=False,allow_nan=False)+"\n",encoding="utf-8",newline="\n")
    for name,records_ in [("summary.csv",summary),("fills.csv",fills),("closed_positions.csv",trades),("equity_curve.csv",equity),("monthly_attribution.csv",monthly)]:write_csv(output/name,records_)
    print(json.dumps({"result_digest":report["result_digest"],"all_24_accounting_checks":"PASS","output":str(output)}),flush=True)
    return report
def main():
    p=argparse.ArgumentParser();p.add_argument("--root",type=Path,required=True);p.add_argument("--base-root",type=Path,required=True)
    p.add_argument("--source-sha",required=True);p.add_argument("--prereg-sha",required=True);a=p.parse_args()
    run(a.root,a.base_root,a.source_sha,a.prereg_sha)
if __name__=="__main__":main()
