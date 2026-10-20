"""Execute the preregistered MR40 study on already-verified immutable local inputs."""
from __future__ import annotations
import argparse,csv,hashlib,importlib.util,json,platform,sys
from datetime import datetime,timezone
from pathlib import Path
import numpy as np
import pandas as pd
import nexus_mean_reversion_40_m2_retest_v1 as m
def load_verified(root):
    contract=json.loads((root/"study_contract.json").read_text(encoding="utf-8"))
    if contract["params"]!=m.PARAMS or contract["params_sha256"]!=m.digest(m.PARAMS) or contract["capital_usdt"]!=m.CAPITAL: raise ValueError("frozen strategy contract mismatch")
    if contract["authority"]!={"research_only":True,"auto_demo":False,"live_enabled":False,"orders_placed":0}: raise ValueError("authority boundary")
    inputs=json.loads((root/"prepared_inputs.json").read_text(encoding="utf-8"))
    unsigned={k:v for k,v in inputs.items() if k!="input_digest"}
    if m.digest(unsigned)!=inputs["input_digest"] or m.digest(inputs["rows"])!=inputs["all_bars_sha256"]: raise ValueError("input digest mismatch")
    if inputs.get("symbol")!="BTCUSDT" or inputs.get("timeframe")!="hour4": raise ValueError("input identity")
    if [s["sha256"] for s in inputs["sources"]]!=[s["sha256"] for s in contract["source_inputs"]]: raise ValueError("source substitution")
    if not all(s.get("raw_trade_semantics_validated") is True for s in inputs["sources"][1:]): raise ValueError("raw semantic evidence missing")
    m.validate_frame(inputs["rows"])
    legacy=root/"frozen_legacy.py"
    if hashlib.sha256(legacy.read_bytes()).hexdigest()!=contract["legacy_engine_sha256"]: raise ValueError("historical engine bytes mismatch")
    spec=importlib.util.spec_from_file_location("frozen_mr40_legacy",legacy);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return contract,inputs,module
def csv_write(path,rows):
    if not rows:return
    with path.open("w",encoding="utf-8",newline="") as target:
        writer=csv.DictWriter(target,fieldnames=list(rows[0]),lineterminator="\n")
        writer.writeheader();writer.writerows(rows)
def run(root,code_sha,prereg_sha):
    for value in (code_sha,prereg_sha):
        if len(value)!=40 or any(c not in "0123456789abcdef" for c in value): raise ValueError("exact commit required")
    contract,inputs,legacy=load_verified(root);all_rows=inputs["rows"];signal=m.targets(all_rows);independent=m.decimal_targets(all_rows)
    if signal!=independent: raise AssertionError("independent complete-history target mismatch")
    legacy_frame=pd.DataFrame(all_rows,columns=["timestamp","open","high","low","close","volume"])
    for col in ["open","high","low","close","volume"]: legacy_frame[col]=legacy_frame[col].astype(float)
    legacy_signal=legacy.generate_targets(legacy_frame,"mean_reversion",m.PARAMS).astype(int).tolist()
    if signal!=legacy_signal: raise AssertionError("frozen historical pandas target mismatch")
    cutpoints=[40,130,1000,4000,8034,8220,8399]
    for cut in cutpoints:
        if m.targets(all_rows[:cut])!=signal[:cut]: raise AssertionError("causality prefix mismatch")
    results=[];summary=[];fills=[];positions=[];curves=[];monthly=[];checks=[]
    profiles=[("normal",10,5,1),("stress",25,15,1),("zero_cost_diagnostic",0,0,1),("additional_4h_latency",10,5,2)]
    for cohort in contract["cohorts"]:
        cold=cohort["id"]=="july_legacy_control"
        if cold:
            rows=[r for r in all_rows if m.ms(cohort["start"])<=r[0]<m.ms(cohort["end_exclusive"])]
            target=m.targets(rows);decimal_signal=m.decimal_targets(rows);start=0;end=len(rows)
        else:
            rows=all_rows;target=signal;decimal_signal=independent
            start=next(i for i,r in enumerate(rows) if r[0]==m.ms(cohort["start"]))
            end=next((i for i,r in enumerate(rows) if r[0]==m.ms(cohort["end_exclusive"])),len(rows))
        if target!=decimal_signal: raise AssertionError("cohort independent target mismatch")
        if rows[end-1][0]+m.STEP!=m.ms(cohort["end_exclusive"]): raise ValueError("incomplete cohort window")
        for name,fee,slip,lag in profiles:
            out=m.simulate(rows,target,start,end,fee,slip,lag=lag,skip_first=cold)
            ref=m.independent_accounting(rows,decimal_signal,start,end,fee,slip,lag=lag,skip_first=cold)
            maximum=max(abs(a["equity"]-b) for a,b in zip(out["equity_curve"],ref["equity"]))
            if maximum>1e-7 or ref["fill_count"]!=out["metrics"]["fills"]: raise AssertionError("independent Decimal equity/fill mismatch")
            check={"cohort":cohort["id"],"profile":name,"max_absolute_equity_difference_usdt":maximum,"decimal_accounting_pass":True}
            if cold and lag==1:
                frame=pd.DataFrame(rows,columns=["timestamp","open","high","low","close","volume"])
                for col in ["open","high","low","close","volume"]:frame[col]=frame[col].astype(float)
                old=legacy._simulate(frame,pd.Series(target),0,len(frame),{"fee_bps":fee,"slippage_bps":slip},bars_per_year=legacy.TIMEFRAME_BARS_PER_YEAR["hour4"])
                if abs(old["total_return"]-out["metrics"]["net_return_pct"]/100)>1e-12 or abs(old["max_drawdown"]-out["metrics"]["max_close_drawdown_pct"]/100)>1e-12 or old["fill_count"]!=out["metrics"]["fills"]:raise AssertionError("legacy compatibility mismatch")
                check["legacy_metric_match"]=True
                if name=="normal":
                    expected={"net_pnl_usdt":195.4101,"net_return_pct":1.9541,"max_close_drawdown_pct":1.5075,"fills":4}
                    if any(round(out["metrics"][k],4)!=v for k,v in expected.items()):raise AssertionError("known July row not reproduced")
                    check["known_workbook_row_match"]=True
            checks.append(check)
            bench=m.benchmark(rows,start,end,fee,slip)
            label={"cohort":cohort["id"],"profile":name}
            record={**label,"role":cohort["role"],"fee_bps":fee,"slippage_bps":slip,"execution_lag_bars":lag,
                    **out["metrics"],"buy_and_hold":bench,"monthly_attribution":out["monthly_attribution"],
                    "fills":out["fills"],"positions":out["positions"]}
            results.append(record)
            summary.append({**label,**out["metrics"],"buy_hold_net_pnl_usdt":bench["net_pnl_usdt"],"buy_hold_max_close_drawdown_pct":bench["max_close_drawdown_pct"]})
            fills.extend({**label,**f} for f in out["fills"]);positions.extend({**label,**t} for t in out["positions"])
            curves.extend({**label,**c} for c in out["equity_curve"]);monthly.extend({**label,**a} for a in out["monthly_attribution"])
            print(json.dumps({**label,"net_pnl_usdt":out["metrics"]["net_pnl_usdt"],"positions":out["metrics"]["closed_positions"],"max_close_dd_pct":out["metrics"]["max_close_drawdown_pct"]}),flush=True)
    july=[r for r in all_rows if m.ms("2026-07-01")<=r[0]<m.ms("2026-08-01")]
    source_files={}
    for rel in ["research/mean_reversion_40_m2_retest_v1.json","research/nexus_mean_reversion_40_m2_retest_v1.py",
                "research/prepare_mean_reversion_40_m2_retest_v1.py","research/run_mean_reversion_40_m2_retest_v1.py","tests/test_nexus_mean_reversion_40_m2_retest_v1.py"]:
        b=(root/rel).read_bytes();source_files[rel]={"bytes":len(b),"sha256":hashlib.sha256(b).hexdigest(),"git_blob":hashlib.sha1(f"blob {len(b)}\0".encode()+b).hexdigest()}
    report={"schema":"nexus.mr40-professional-fixed-retest-results.v1","study_id":contract["study_id"],"study_user_date":"2026-10-21",
        "executed_utc":datetime.now(timezone.utc).isoformat(),"code_commit":code_sha,"preregistered_contract_commit":prereg_sha,
        "python":platform.python_version(),"pandas":pd.__version__,"numpy":np.__version__,"physical_worker":"DESKTOP-F4SA4VL",
        "strategy_id":contract["strategy_id"],"params":m.PARAMS,"params_sha256":m.digest(m.PARAMS),
        "input_digest":inputs["input_digest"],"input_sources":inputs["sources"],"source_files":source_files,
        "independent_signal_bars":len(signal),"historical_pandas_target_match":True,"prefix_causality_checks":len(cutpoints),
        "independent_accounting_checks":checks,"july_input_frame_sha256":m.digest(july),
        "original_july_workbook_frame_sha256":"c75ca7e7a74c0ff3a4d51f5a12a9ac27232563a03a1a87b61b5d65851fe47cc9",
        "original_july_full_input_identity":False,"results":results,
        "qualification":"RESEARCH_ONLY_NO_AUTO_PROMOTION","parameter_search_performed":False,"minimum_trade_count_gate_applied":False,
        "post_july_period_is_prospective":False,"orders_placed":0,"live_enabled":False}
    report["result_digest"]=m.digest(report)
    dest=root/"results"
    if dest.exists():raise ValueError("refuse overwrite completed study outputs")
    dest.mkdir()
    (dest/"results.json").write_text(json.dumps(report,ensure_ascii=False,separators=(",",":"),allow_nan=False)+"\n",encoding="utf-8")
    csv_write(dest/"summary.csv",summary);csv_write(dest/"fills.csv",fills);csv_write(dest/"closed_positions.csv",positions)
    csv_write(dest/"equity_curve.csv",curves);csv_write(dest/"monthly_attribution.csv",monthly)
    artifact=[]
    for p in sorted(dest.iterdir()):
        b=p.read_bytes();artifact.append({"name":p.name,"bytes":len(b),"sha256":hashlib.sha256(b).hexdigest(),"git_blob":hashlib.sha1(f"blob {len(b)}\0".encode()+b).hexdigest()})
    (dest/"output_manifest.json").write_text(json.dumps({"result_digest":report["result_digest"],"artifacts":artifact},indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"result_digest":report["result_digest"],"scored_rows":len(results),"all_numeric_checks":"PASS","output":str(dest)}),flush=True)
    return report
def main():
    p=argparse.ArgumentParser();p.add_argument("--root",type=Path,required=True);p.add_argument("--source-sha",required=True);p.add_argument("--prereg-sha",required=True)
    a=p.parse_args();run(a.root,a.source_sha,a.prereg_sha)
if __name__=="__main__":main()
