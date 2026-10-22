"""Run from the extracted MR40 RR/sizing evidence bundle, Python 3.12+, offline."""
import gzip
import hashlib
import importlib.util
import json
import lzma
import math
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT=Path(__file__).resolve().parent


def compare(actual,expected,path="result"):
    if isinstance(expected,dict):
        if set(actual)!=set(expected):raise AssertionError(path+": keys")
        for key,value in expected.items():
            if key!="result_digest":compare(actual[key],value,path+"/"+key)
    elif isinstance(expected,list):
        if len(actual)!=len(expected):raise AssertionError(path+": length")
        for i,(a,b) in enumerate(zip(actual,expected)):compare(a,b,path+"/"+str(i))
    elif isinstance(expected,float):
        if not math.isclose(actual,expected,rel_tol=1e-10,abs_tol=1e-7):raise AssertionError(path+": number")
    elif actual!=expected:raise AssertionError(path+": value")


manifest=json.loads((ROOT/"MANIFEST.json").read_bytes())
for name,item in manifest["files"].items():
    path=ROOT/name
    if not path.is_file() or path.stat().st_size!=item["bytes"] or hashlib.sha256(path.read_bytes()).hexdigest()!=item["sha256"]:
        raise AssertionError("bundle_file_changed: "+name)
source=ROOT/"source"
for pattern in ("test_nexus_mr40_isolated_improvement_v1.py","test_nexus_mr40_rr_sizing_v2.py"):
    subprocess.run([sys.executable,"-m","unittest","discover","-s",str(source/"tests"),"-p",pattern,"-q"],cwd=source,check=True)
spec=importlib.util.spec_from_file_location("mr40_rr_bundle_replay",source/"research/nexus_mr40_rr_sizing_v2.py")
study=importlib.util.module_from_spec(spec);spec.loader.exec_module(study)
recorded=json.loads((ROOT/"recorded/results.json").read_bytes())
if study.digest({k:v for k,v in recorded.items() if k!="result_digest"})!=recorded["result_digest"]:raise AssertionError("result_digest_changed")
with lzma.open(ROOT/"recorded/all_ledgers.json.xz","rb") as f:ledgers=json.load(f)
for sha,obj in ledgers["objects"].items():
    if study.digest(obj)!=sha:raise AssertionError("ledger_object_changed")
with tempfile.TemporaryDirectory() as tmp:
    output=Path(tmp)/"replayed"
    actual=study.run(source,ROOT/"inputs",output,recorded["protocol_commit"],recorded["code_commit"])
    compare(actual,recorded)
    observed=set()
    with gzip.open(output/"all_runs.jsonl.gz","rb") as f:
        for line in f:
            run=json.loads(line);key=run["key"]
            if key in observed:raise AssertionError("duplicate replay")
            observed.add(key);witness=ledgers["runs"][key]
            compare(run["fills"],[ledgers["objects"][sha] for sha in witness["fill_refs"]],key+"/fills")
            expected_positions=[]
            for p in witness["positions"]:
                position={k:v for k,v in p.items() if k not in ("entry_ref","exit_ref")}
                position.update(entry=ledgers["objects"][p["entry_ref"]],exit=ledgers["objects"][p["exit_ref"]])
                expected_positions.append(position)
            compare(run["positions"],expected_positions,key+"/positions")
            if run["equity_sha256_6dp"]!=witness["equity_sha256_6dp"]:raise AssertionError(key+": rounded equity digest")
    if observed!=set(ledgers["runs"]):raise AssertionError("missing ledger")
    compare(json.loads((output/"full_normal_curves.json").read_bytes()),json.loads((ROOT/"recorded/full_normal_curves.json").read_bytes()),"full curves")
print(json.dumps({"verified":True,"bundle_files":len(manifest["files"]),"independent_ledger_replays":len(ledgers["runs"]),
    "prefix_checks":recorded["prefix_checks"],"baseline_parity_checks":len(recorded["baseline_parity_checks"]),
    "unit_tests":30,"original_result_digest":recorded["result_digest"],"network_requests":0}),flush=True)
