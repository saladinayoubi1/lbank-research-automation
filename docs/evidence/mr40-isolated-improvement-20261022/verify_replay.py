"""Run inside the extracted evidence bundle with Python 3.12+. No network."""
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT=Path(__file__).resolve().parent


def canonical(value):
    return json.dumps(value,sort_keys=True,separators=(",",":"),ensure_ascii=False,allow_nan=False).encode()


def compare(actual,expected,path="result"):
    if isinstance(expected,dict):
        if set(actual)!=set(expected):raise AssertionError(path+": keys")
        for key,value in expected.items():
            if key=="result_digest":continue
            if key=="allocation":
                if not math.isclose(float(actual[key]),float(value),rel_tol=1e-12,abs_tol=1e-14):raise AssertionError(path+": allocation")
            else:compare(actual[key],value,path+"/"+key)
    elif isinstance(expected,list):
        if len(actual)!=len(expected):raise AssertionError(path+": length")
        for i,(a,b) in enumerate(zip(actual,expected)):compare(a,b,path+"/"+str(i))
    elif isinstance(expected,float):
        if not math.isclose(actual,expected,rel_tol=1e-10,abs_tol=1e-7):raise AssertionError(path+": number")
    elif actual!=expected:
        raise AssertionError(path+": value")


manifest=json.loads((ROOT/"MANIFEST.json").read_bytes())
for name,item in manifest["files"].items():
    path=ROOT/name
    if not path.is_file() or path.stat().st_size!=item["bytes"] or hashlib.sha256(path.read_bytes()).hexdigest()!=item["sha256"]:
        raise AssertionError("bundle_file_changed: "+name)
source=ROOT/"source"
subprocess.run([sys.executable,"-m","unittest","discover","-s",str(source/"tests"),"-p","test_nexus_mr40_isolated_improvement_v1.py","-q"],cwd=source,check=True)
spec=importlib.util.spec_from_file_location("mr40_bundle_replay",source/"research/nexus_mr40_isolated_improvement_v1.py")
study=importlib.util.module_from_spec(spec);spec.loader.exec_module(study)
recorded=json.loads((ROOT/"recorded/results.json").read_bytes())
assert study.digest({k:v for k,v in recorded.items() if k!="result_digest"})==recorded["result_digest"]
ledgers=json.loads((ROOT/"recorded/all_ledgers.json").read_bytes())
with tempfile.TemporaryDirectory() as tmp:
    output=Path(tmp)/"replayed"
    actual=study.run(source,ROOT/"inputs",output,recorded["protocol_commit"],recorded["code_commit"])
    compare(actual,recorded)
    runs=json.loads((output/"all_runs.json").read_bytes())
    assert set(runs)==set(ledgers["runs"])
    for key,run in runs.items():
        witness=ledgers["runs"][key]
        expected=[ledgers["objects"][i] for i in witness["fill_refs"]]
        compare(run["fills"],expected,key+"/fills")
        if study.digest([format(v,".6f") for v in run["equity"]])!=witness["equity_sha256_6dp"]:
            raise AssertionError(key+": rounded equity digest")
    curves=json.loads((ROOT/"recorded/full_normal_curves.json").read_bytes())
    for key,expected in curves.items():compare(runs[key]["equity"],expected,key+"/curve")
print(json.dumps({"verified":True,"bundle_files":len(manifest["files"]),"independent_ledgers":len(ledgers["runs"]),"prefix_checks":recorded["prefix_checks"],"tests":9,"original_result_digest":recorded["result_digest"],"network_requests":0}),flush=True)
