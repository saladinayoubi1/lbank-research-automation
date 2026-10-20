"""Run the frozen 49-test version inside the isolated research environment."""
from pathlib import Path
from datetime import datetime,timezone
import hashlib,json,os,subprocess,sys,urllib.parse
root=Path(r"E:\NEXUS-QA\ctrend-causal-full-20261020")
status=json.loads((root/"environment-status.json").read_text(encoding="utf-8"))
assert status["status"]=="READY_FOR_SYNTHETIC_TESTS"
py=root/"venv/Scripts/python.exe"
payload=json.loads(Path(r"E:\NEXUS-QA\ctrend-causal-full-stage-20261020.json").read_text(encoding="utf-8-sig"))
project=root/"project"
for rel,content in payload["files"].items():
    if Path(rel).is_absolute() or ".." in Path(rel).parts:raise ValueError("Invalid staged path")
    data=content.encode("utf-8")
    assert hashlib.sha256(data).hexdigest()==payload["sha256"][rel]
    p=project/rel
    p.parent.mkdir(parents=True,exist_ok=True)
    if p.exists() and p.read_bytes()!=data:raise ValueError("Existing isolated source differs: "+rel)
    p.write_bytes(data)
env=dict(os.environ,PYTHONDONTWRITEBYTECODE="1",OPENBLAS_NUM_THREADS="1",MKL_NUM_THREADS="1",OMP_NUM_THREADS="1")
check=subprocess.run([str(py),"-m","pip","check"],capture_output=True,text=True,timeout=30,env=env)
assert check.returncode==0,check.stdout+check.stderr
probe="import sys,json,numpy,scipy,sklearn;print(json.dumps({'prefix':sys.prefix,'executable':sys.executable,'numpy':numpy.__version__,'scipy':scipy.__version__,'sklearn':sklearn.__version__,'numpy_file':numpy.__file__,'scipy_file':scipy.__file__,'sklearn_file':sklearn.__file__}))"
runtime=json.loads(subprocess.check_output([str(py),"-c",probe],text=True,timeout=30,env=env))
assert Path(runtime["prefix"]).resolve()==(root/"venv").resolve()
for name in ("numpy_file","scipy_file","sklearn_file"):
    assert (root/"venv").resolve() in Path(runtime[name]).resolve().parents
report=project/"docs/evidence/ctrend-causal-20261020/laptop2-full-validation.json"
result=subprocess.run([str(py),str(project/"research/run_ctrend_causal_validation_v1.py"),"--report",str(report)],cwd=project,env=env,capture_output=True,text=True,timeout=180)
(root/"full-test-process.log").write_text(result.stdout+result.stderr,encoding="utf-8")
tests=json.loads(report.read_text(encoding="utf-8"))
for rel,digest in payload["sha256"].items():assert tests["sha256"][rel]==digest
baseline=json.loads(subprocess.check_output([r"E:\NEXUS-QA\pytest-env\Scripts\python.exe","-c","import sys,numpy,json;print(json.dumps({'prefix':sys.prefix,'numpy':numpy.__version__}))"],text=True,timeout=30))
assert baseline["numpy"]=="2.5.3"
install=json.loads((root/"pip-install-report.json").read_text(encoding="utf-8"))
packages=[]
for item in install["install"]:
    d=item["download_info"];m=item["metadata"]
    assert urllib.parse.urlsplit(d["url"]).hostname=="files.pythonhosted.org"
    assert m["version"]==status["pins"][m["name"]]
    packages.append({"name":m["name"],"version":m["version"],"wheel_url":d["url"],"archive_info":d["archive_info"]})
out={"schema":"nexus.ctrend-causal-native-full-proof.v1","recorded_at_utc":datetime.now(timezone.utc).isoformat(),"parent_code_commit":"4c722cf0c6e00d6176fd7ea22ddc1d97ece282fd","source_hashes_match_frozen_inputs":True,"pip_check":{"exit_code":check.returncode,"output":check.stdout.strip()},"new_environment":runtime,"existing_qa_environment_after":baseline,"baseline_numpy_preserved":True,"thread_limits":{k:env[k] for k in ("OPENBLAS_NUM_THREADS","MKL_NUM_THREADS","OMP_NUM_THREADS")},"packages":packages,"test_process_exit_code":result.returncode,"test_report_sha256":hashlib.sha256(report.read_bytes()).hexdigest(),"tests_run":tests["tests_run"],"success":tests["success"] and result.returncode==0,"real_orders":0,"financial_backtest":False,"demo_admitted":False,"paper_writer_enabled":False}
(root/"native-full-proof.json").write_text(json.dumps(out,indent=2)+"\n",encoding="utf-8")
print(json.dumps(out))
raise SystemExit(0 if out["success"] else 1)
