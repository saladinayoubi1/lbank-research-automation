"""One fixed, already-seen MR40 entry-admission experiment; no execution API."""
from __future__ import annotations
import argparse,csv,hashlib,importlib.util,json,math,platform
from datetime import datetime,timezone
from decimal import Decimal
from pathlib import Path

ENGINE_SHA="e9b898040d4680f128da330177df84e2fcc4ba1e2f70f467cf5455d685247b27"
CONTRACT_SHA="153957458cbc5c3256bf0ea7909db6071cac587f7a765477d06d1f242383de50"
INPUT_DIGEST="fba66860376d9ad24af7a2388e878db0dfdbae16468de9381ef6a95f95563ffe"
BASE_DIGEST="44ea00e4528ccbe3e420bd999152a36b58450565f8a45bb9489a3c79fe4b4514"
LOOKBACK=180
STEP=14_400_000

def canonical(value):
    return json.dumps(value,sort_keys=True,separators=(",",":"),ensure_ascii=False,allow_nan=False).encode()

def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()

def admit_episodes(rows,raw,decision_start=0,decision_stop=None):
    """A rejected original-long episode stays flat until the original reset."""
    stop=len(raw) if decision_stop is None else decision_stop
    if len(rows)!=len(raw) or not 0<=decision_start<=stop<=len(raw):
        raise ValueError("invalid decision range")
    if any(s not in (0,1) for s in raw):
        raise ValueError("binary original targets required")
    target=[0]*len(raw);in_episode=False;admitted=False;decisions=[]
    for i in range(decision_start,stop):
        if raw[i]==0:
            in_episode=False;admitted=False
        elif not in_episode:
            in_episode=True
            has_history=i>=LOOKBACK
            admitted=has_history and float(rows[i][4])>=float(rows[i-LOOKBACK][4])
            decisions.append({"decision_index":i,"decision_available_ms":rows[i][0]+STEP,
                              "accepted":admitted,"has_30d_history":has_history,
                              "momentum_30d_return_pct":100*(float(rows[i][4])/float(rows[i-LOOKBACK][4])-1) if has_history else None})
        target[i]=int(admitted)
    return target,decisions

def independent_admission(rows,raw,decision_start=0,decision_stop=None):
    """Independent interval scan and exact-decimal threshold comparison."""
    end=len(raw) if decision_stop is None else decision_stop
    output=[0]*len(raw);cursor=decision_start
    while cursor<end:
        if raw[cursor]==0:
            cursor+=1
            continue
        finish=cursor+1
        while finish<end and raw[finish]==1:
            finish+=1
        if cursor>=LOOKBACK and Decimal(str(rows[cursor][4]))>=Decimal(str(rows[cursor-LOOKBACK][4])):
            output[cursor:finish]=[1]*(finish-cursor)
        cursor=finish
    return output

def load_base(root):
    path=root/"research"/"nexus_mean_reversion_40_m2_retest_v1.py"
    if hashlib.sha256(path.read_bytes()).hexdigest()!=ENGINE_SHA:
        raise ValueError("baseline engine substitution")
    spec=importlib.util.spec_from_file_location("mr40_momentum30_frozen_core",path)
    engine=importlib.util.module_from_spec(spec);spec.loader.exec_module(engine)
    inputs=json.loads((root/"prepared_inputs.json").read_text(encoding="utf-8"))
    if inputs["input_digest"]!=INPUT_DIGEST or digest({k:v for k,v in inputs.items() if k!="input_digest"})!=INPUT_DIGEST:
        raise ValueError("input substitution")
    old=root/"verified_results"
    if not old.is_dir():
        old=root/"recorded_results"
    baseline=json.loads((old/"results.json").read_text(encoding="utf-8"))
    if baseline["result_digest"]!=BASE_DIGEST or digest({k:v for k,v in baseline.items() if k!="result_digest"})!=BASE_DIGEST:
        raise ValueError("baseline result substitution")
    contract_bytes=(root/"study_contract.json").read_bytes()
    if hashlib.sha256(contract_bytes).hexdigest()!=baseline["source_files"]["research/mean_reversion_40_m2_retest_v1.json"]["sha256"]:
        raise ValueError("baseline contract substitution")
    engine.validate_frame(inputs["rows"])
    curves={}
    with (old/"equity_curve.csv").open(encoding="utf-8",newline="") as source:
        for row in csv.DictReader(source):
            curves.setdefault((row["cohort"],row["profile"]),[]).append((int(row["bar_open_ms"]),float(row["equity"])))
    return engine,inputs["rows"],baseline,json.loads(contract_bytes),curves

def write_csv(path,records):
    with path.open("w",encoding="utf-8",newline="") as out:
        writer=csv.DictWriter(out,fieldnames=list(records[0]),lineterminator="\n")
        writer.writeheader();writer.writerows(records)

def run(root,base_root,source_sha,prereg_sha):
    if (root/"results").exists():
        raise ValueError("refuse overwrite")
    for sha in (source_sha,prereg_sha):
        if len(sha)!=40 or any(c not in "0123456789abcdef" for c in sha):
            raise ValueError("exact Git commit required")
    contract=(root/"study_contract.json").read_bytes()
    if hashlib.sha256(contract).hexdigest()!=CONTRACT_SHA:
        raise ValueError("registered policy substitution")
    engine,rows,baseline,old_contract,curves=load_base(base_root)
    raw=engine.targets(rows);decimal_raw=engine.decimal_targets(rows)
    if raw!=decimal_raw:
        raise AssertionError("independent baseline signal mismatch")
    records=[];checks=[];summaries=[];fills=[];positions=[];equity=[];monthly=[];admissions=[]
    profiles=[("normal",10,5,1),("stress",25,15,1),("zero_cost_diagnostic",0,0,1),("additional_4h_latency",10,5,2)]
    for cohort in old_contract["cohorts"]:
        start=next(i for i,r in enumerate(rows) if r[0]==engine.ms(cohort["start"]))
        end=next((i for i,r in enumerate(rows) if r[0]==engine.ms(cohort["end_exclusive"])),len(rows))
        cold=cohort["id"]=="july_legacy_control"
        if cold:
            original=[0]*len(rows);original[start:end]=engine.targets(rows[start:end])
            independent_raw=[0]*len(rows);independent_raw[start:end]=engine.decimal_targets(rows[start:end])
        else:
            original=raw;independent_raw=decimal_raw
        for profile,fee,slip,lag in profiles:
            labels={"cohort":cohort["id"],"profile":profile}
            old=next(r for r in baseline["results"] if r["cohort"]==cohort["id"] and r["profile"]==profile)
            control=engine.simulate(rows,original,start,end,fee,slip,lag=lag,skip_first=cold)
            previous=curves[(cohort["id"],profile)]
            if len(previous)!=len(control["equity_curve"]):
                raise AssertionError("baseline curve length mismatch")
            control_error=max(abs(point["equity"]-expected[1]) for point,expected in zip(control["equity_curve"],previous))
            if control_error>1e-7 or any(point["bar_open_ms"]!=expected[0] for point,expected in zip(control["equity_curve"],previous)):
                raise AssertionError("cohort baseline replay mismatch")
            if abs(control["metrics"]["net_pnl_usdt"]-old["net_pnl_usdt"])>1e-7:
                raise AssertionError("baseline PnL mismatch")
            first=max(0,start-lag);last=end-lag
            target,decisions=admit_episodes(rows,original,first,last)
            oracle_target=independent_admission(rows,independent_raw,first,last)
            if target!=oracle_target:
                raise AssertionError("independent entry-admission mismatch")
            if any(a>b for a,b in zip(target,original)):
                raise AssertionError("admission creates an original-flat exposure")
            cuts=sorted({min(last,first+37),min(last,first+181),min(last,first+400)})
            for cut in cuts:
                if admit_episodes(rows,original,first,cut)[0][:cut]!=target[:cut]:
                    raise AssertionError("future-dependent entry")
            out=engine.simulate(rows,target,start,end,fee,slip,lag=lag,skip_first=cold)
            independent=engine.independent_accounting(rows,oracle_target,start,end,fee,slip,lag=lag,skip_first=cold)
            if len(out["equity_curve"])!=len(independent["equity"]):
                raise AssertionError("candidate curve length mismatch")
            error=max(abs(x["equity"]-y) for x,y in zip(out["equity_curve"],independent["equity"]))
            if error>1e-7 or independent["fill_count"]!=out["metrics"]["fills"]:
                raise AssertionError("candidate independent accounting mismatch")
            allowed={x["entry_ms"] for x in old["positions"]}
            if any(x["entry_ms"] not in allowed for x in out["positions"]):
                raise AssertionError("new or late entry outside original positions")
            stats=dict(out["metrics"]);stats["fill_count"]=stats.pop("fills")
            stats.update({"admitted_episodes":sum(x["accepted"] for x in decisions),
                          "rejected_episodes":sum(not x["accepted"] for x in decisions),
                          "missing_history_rejections":sum(not x["has_30d_history"] for x in decisions)})
            result={**labels,**stats,"base_net_pnl_usdt":old["net_pnl_usdt"],
                    "base_max_close_drawdown_pct":old["max_close_drawdown_pct"],
                    "base_closed_positions":old["closed_positions"],
                    "difference_net_pnl_usdt":stats["net_pnl_usdt"]-old["net_pnl_usdt"],
                    "monthly_attribution":out["monthly_attribution"],"positions":out["positions"],"fills":out["fills"]}
            records.append(result)
            summaries.append({k:v for k,v in result.items() if k not in ("positions","fills","monthly_attribution")})
            for dest,source in [(fills,out["fills"]),(positions,out["positions"]),(equity,out["equity_curve"]),(monthly,out["monthly_attribution"]),(admissions,decisions)]:
                dest.extend({**labels,**x} for x in source)
            checks.append({**labels,"baseline_curve_maximum_error_usdt":control_error,
                           "independent_gate_match":True,"independent_accounting_maximum_error_usdt":error,
                           "prefix_checks":len(cuts),"entry_times_subset_of_baseline":True})
            print(json.dumps({**labels,"net_pnl_usdt":stats["net_pnl_usdt"],"positions":stats["closed_positions"],
                              "drawdown_pct":stats["max_close_drawdown_pct"],"base_net_pnl_usdt":old["net_pnl_usdt"]}),flush=True)
    report={"schema":"nexus.mr40-momentum30-entry-results.v1","code_commit":source_sha,"preregistered_contract_commit":prereg_sha,
            "executed_utc":datetime.now(timezone.utc).isoformat(),"physical_worker":platform.node(),
            "input_digest":INPUT_DIGEST,"baseline_result_digest":BASE_DIGEST,"independent_signal_bars":len(raw),
            "classification":"EXPLORATORY_ALREADY_SEEN_POST_HOC_HYPOTHESIS_NOT_INDEPENDENT_QUALIFICATION",
            "parameter_search":False,"prospective":False,"research_only":True,"auto_demo":False,"live_enabled":False,"orders":0,
            "results":records,"checks":checks,"source_files":{}}
    for rel,path in [
        ("research/nexus_mean_reversion_40_m2_momentum30_entry_v1.py",Path(__file__)),
        ("research/mean_reversion_40_m2_momentum30_entry_v1.json",root/"study_contract.json"),
        ("tests/test_nexus_mean_reversion_40_m2_momentum30_entry_v1.py",root/"tests"/"test_nexus_mean_reversion_40_m2_momentum30_entry_v1.py")]:
        data=path.read_bytes()
        report["source_files"][rel]={"bytes":len(data),"sha256":hashlib.sha256(data).hexdigest(),
                                    "git_blob":hashlib.sha1(f"blob {len(data)}\0".encode()+data).hexdigest()}
    report["result_digest"]=digest(report)
    output=root/"results";output.mkdir()
    (output/"results.json").write_text(json.dumps(report,ensure_ascii=False,separators=(",",":"),allow_nan=False)+"\n",encoding="utf-8",newline="\n")
    for name,values in [("summary.csv",summaries),("fills.csv",fills),("closed_positions.csv",positions),
                        ("equity_curve.csv",equity),("monthly_attribution.csv",monthly),("entry_admissions.csv",admissions)]:
        write_csv(output/name,values)
    print(json.dumps({"result_digest":report["result_digest"],"checks":len(checks),"output":str(output)}),flush=True)
    return report

if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--root",type=Path,required=True);parser.add_argument("--base-root",type=Path,required=True)
    parser.add_argument("--source-sha",required=True);parser.add_argument("--prereg-sha",required=True)
    args=parser.parse_args();run(args.root,args.base_root,args.source_sha,args.prereg_sha)
