"""Historical October follow-up of an unchanged, hash-pinned MR40 candidate."""
from __future__ import annotations
import argparse,csv,hashlib,importlib.util,json,platform
from datetime import datetime,timezone
from pathlib import Path
STEP=14_400_000
OLD_INPUT="fba66860376d9ad24af7a2388e878db0dfdbae16468de9381ef6a95f95563ffe"
OLD_RESULT="959832aa111ba6bbab7a899547a7d4e031a0f3cd0a283de30397635f1ba5f118"
ENGINE="e9b898040d4680f128da330177df84e2fcc4ba1e2f70f467cf5455d685247b27"
CANDIDATE="d899e9dd991695959c230426b50ebdb4bab2eca8c5f413ea3c471d957c1f69bb"

def canonical(value):
    return json.dumps(value,sort_keys=True,separators=(",",":"),ensure_ascii=False,allow_nan=False).encode()

def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()

def check_digest(value,key,expected):
    if value.get(key)!=expected or digest({k:v for k,v in value.items() if k!=key})!=expected:
        raise ValueError("substituted "+key)

def load_module(name,path,expected):
    if hashlib.sha256(path.read_bytes()).hexdigest()!=expected:raise ValueError("frozen module substitution")
    spec=importlib.util.spec_from_file_location(name,path);module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module);return module

def append_october(old,extension):
    rows=extension["rows"]
    start=1790812800000
    if len(rows)!=114 or rows[0][0]!=start or rows[-1][0]!=start+113*STEP:
        raise ValueError("wrong complete October 1-19 boundary")
    if old[-1][0]+STEP!=rows[0][0] or any(rows[i][0]-rows[i-1][0]!=STEP for i in range(1,len(rows))):
        raise ValueError("October gap/overlap")
    return old+rows

def write_csv(path,records):
    with path.open("w",encoding="utf-8",newline="") as out:
        writer=csv.DictWriter(out,fieldnames=list(records[0]),lineterminator="\n")
        writer.writeheader();writer.writerows(records)

def run(root,frozen_root,source_sha,protocol_sha,extension_sha):
    if (root/"results").exists():raise ValueError("refuse results overwrite")
    for sha in (source_sha,protocol_sha):
        if len(sha)!=40 or any(c not in "0123456789abcdef" for c in sha):raise ValueError("exact source commit required")
    engine=load_module("mr40_oct_frozen_core",frozen_root/"research"/"nexus_mean_reversion_40_m2_retest_v1.py",ENGINE)
    candidate=load_module("mr40_oct_frozen_gate",frozen_root/"research"/"nexus_mean_reversion_40_m2_momentum30_entry_v1.py",CANDIDATE)
    previous=json.loads((frozen_root/"baseline"/"prepared_inputs.json").read_text(encoding="utf-8"))
    check_digest(previous,"input_digest",OLD_INPUT)
    old_result=json.loads((frozen_root/"recorded_results"/"results.json").read_text(encoding="utf-8"))
    check_digest(old_result,"result_digest",OLD_RESULT)
    extension=json.loads((root/"october_input_extension.json").read_text(encoding="utf-8"))
    check_digest(extension,"digest",extension_sha)
    if extension["base_input_digest"]!=OLD_INPUT:raise ValueError("wrong frozen prefix")
    manifest=json.loads((root/"source_manifest.json").read_text(encoding="utf-8"))
    check_digest(manifest,"digest",extension["source_manifest_digest"])
    if len(manifest["files"])!=19 or len(extension["audits"])!=19:raise ValueError("incomplete source days")
    policy=json.loads((root/"study_contract.json").read_text(encoding="utf-8"))
    if policy["frozen_candidate_commit"]!="764d544af246769ffae0c6aca00d02c00fb34078":
        raise ValueError("policy candidate changed")
    rows=append_october(previous["rows"],extension);engine.validate_frame(rows)
    raw=engine.targets(rows);independent_raw=engine.decimal_targets(rows)
    if raw!=independent_raw or raw[:len(previous["rows"])]!=engine.targets(previous["rows"]):
        raise AssertionError("future affects frozen prefix or Decimal signal")
    old_curves={}
    with (frozen_root/"recorded_results"/"equity_curve.csv").open(encoding="utf-8",newline="") as source:
        for row in csv.DictReader(source):
            if row["cohort"]=="august_september_continuous":
                old_curves.setdefault(row["profile"],[]).append((int(row["bar_open_ms"]),float(row["equity"])))
    records=[];checks=[];summaries=[];fills=[];trades=[];curves=[];monthly=[];admissions=[]
    for cohort in policy["cohorts"]:
        start=next(i for i,r in enumerate(rows) if r[0]==engine.ms(cohort["start"]))
        end=next((i for i,r in enumerate(rows) if r[0]==engine.ms(cohort["end_exclusive"])),len(rows))
        for profile in policy["profiles"]:
            fee=profile["fee_bps"];slip=profile["slippage_bps"];lag=profile["lag_bars"]
            base=engine.simulate(rows,raw,start,end,fee,slip,lag=lag)
            first=start-lag;last=end-lag
            target,decisions=candidate.admit_episodes(rows,raw,first,last)
            oracle=candidate.independent_admission(rows,independent_raw,first,last)
            if target!=oracle:raise AssertionError("unchanged admission oracle mismatch")
            filtered=engine.simulate(rows,target,start,end,fee,slip,lag=lag)
            allowed={t["entry_ms"] for t in base["positions"]}
            if any(t["entry_ms"] not in allowed for t in filtered["positions"]):
                raise AssertionError("candidate invents a late entry")
            prefix_error=None
            if cohort["id"]=="august_october19_continuous":
                expected=old_curves[profile["id"]]
                prefix=filtered["equity_curve"][:len(expected)]
                prefix_error=max(abs(a["equity"]-b[1]) for a,b in zip(prefix,expected))
                if len(prefix)!=len(expected) or prefix_error>1e-7 or any(a["bar_open_ms"]!=b[0] for a,b in zip(prefix,expected)):
                    raise AssertionError("augmented data changes prior candidate equity")
            for name,out,signal in [("original",base,independent_raw),("momentum30",filtered,oracle)]:
                labels={"cohort":cohort["id"],"profile":profile["id"],"strategy":name}
                independent=engine.independent_accounting(rows,signal,start,end,fee,slip,lag=lag)
                if len(out["equity_curve"])!=len(independent["equity"]):raise AssertionError("curve size")
                error=max(abs(a["equity"]-b) for a,b in zip(out["equity_curve"],independent["equity"]))
                if error>1e-7 or out["metrics"]["fills"]!=independent["fill_count"]:
                    raise AssertionError("independent account mismatch")
                stats=dict(out["metrics"]);stats["fill_count"]=stats.pop("fills")
                record={**labels,**stats,"baseline_net_pnl_usdt":base["metrics"]["net_pnl_usdt"],
                        "difference_net_pnl_usdt":stats["net_pnl_usdt"]-base["metrics"]["net_pnl_usdt"],
                        "positions":out["positions"],"fills":out["fills"],"monthly_attribution":out["monthly_attribution"]}
                records.append(record)
                summaries.append({k:v for k,v in record.items() if k not in ("positions","fills","monthly_attribution")})
                for destination,source in [(fills,out["fills"]),(trades,out["positions"]),(curves,out["equity_curve"]),(monthly,out["monthly_attribution"])]:
                    destination.extend({**labels,**x} for x in source)
                checks.append({**labels,"maximum_decimal_equity_error_usdt":error,
                               "prior_august_september_candidate_prefix_error_usdt":prefix_error})
                print(json.dumps({**labels,"net_pnl_usdt":stats["net_pnl_usdt"],"closed":stats["closed_positions"],
                                  "terminal":stats["terminal_exits"],"close_dd_pct":stats["max_close_drawdown_pct"]}),flush=True)
            admissions.extend({"cohort":cohort["id"],"profile":profile["id"],**x} for x in decisions)
    result={"schema":"nexus.mr40-momentum30-october-followup-results.v1","code_commit":source_sha,"protocol_commit":protocol_sha,
            "created_utc":datetime.now(timezone.utc).isoformat(),"physical_worker":platform.node(),
            "frozen_candidate_commit":policy["frozen_candidate_commit"],"previous_candidate_result_digest":OLD_RESULT,
            "previous_input_digest":OLD_INPUT,"source_manifest_digest":manifest["digest"],"extension_digest":extension_sha,
            "combined_rows":len(rows),"combined_rows_digest":digest(rows),"original_prefix_unchanged":True,
            "classification":"HISTORICAL_FOLLOWUP_PREVIOUSLY_USED_IN_OTHER_STUDIES_NOT_PRISTINE_OOS_OR_PROSPECTIVE",
            "parameter_search":False,"research_only":True,"auto_demo":False,"live_enabled":False,"orders":0,
            "results":records,"checks":checks}
    result["source_files"]={}
    for rel,path in [("research/nexus_mr40_momentum30_october_followup_v1.py",Path(__file__)),
                     ("research/mean_reversion_40_m2_momentum30_october_followup_v1.json",root/"study_contract.json"),
                     ("scripts/nexus_mr40_october_followup_intake_v1.py",root/"scripts"/"nexus_mr40_october_followup_intake_v1.py")]:
        blob=path.read_bytes();result["source_files"][rel]={"sha256":hashlib.sha256(blob).hexdigest(),
            "git_blob":hashlib.sha1(f"blob {len(blob)}\0".encode()+blob).hexdigest(),"bytes":len(blob)}
    result["result_digest"]=digest(result)
    output=root/"results";output.mkdir()
    (output/"results.json").write_text(json.dumps(result,separators=(",",":"),allow_nan=False)+"\n",encoding="utf-8",newline="\n")
    for name,values in [("summary.csv",summaries),("fills.csv",fills),("closed_positions.csv",trades),
                        ("equity_curve.csv",curves),("monthly_attribution.csv",monthly),("entry_admissions.csv",admissions)]:
        write_csv(output/name,values)
    print(json.dumps({"result_digest":result["result_digest"],"checks":len(checks),"rows":len(rows)}),flush=True)
    return result

if __name__=="__main__":
    parser=argparse.ArgumentParser()
    for name in ("root","frozen-root"):parser.add_argument("--"+name,type=Path,required=True)
    for name in ("source-sha","protocol-sha","extension-sha"):parser.add_argument("--"+name,required=True)
    args=parser.parse_args();run(args.root,args.frozen_root,args.source_sha,args.protocol_sha,args.extension_sha)
