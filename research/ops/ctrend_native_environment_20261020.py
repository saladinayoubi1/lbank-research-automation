"""Provision a NEW research-only venv, never the active NEXUS/pytest environments."""
import hashlib,json,os,subprocess,sys,venv
from datetime import datetime,timezone
from pathlib import Path
root=Path(r"E:\NEXUS-QA\ctrend-causal-full-20261020")
env=root/"venv"
root.mkdir(parents=True,exist_ok=True)
pins={"numpy":"2.3.5","scipy":"1.17.0","scikit-learn":"1.8.0","joblib":"1.5.3","threadpoolctl":"3.6.0"}
report={"schema":"nexus.ctrend-causal-isolated-environment.v1","started_at_utc":datetime.now(timezone.utc).isoformat(),"root":str(root),"active_env_modified":False,"pins":pins,"package_index":"https://pypi.org/simple","binary_wheels_only":True,"scope":"synthetic_research"}
out=root/"environment-status.json"
try:
    if env.exists():
        raise RuntimeError("New environment path already exists; inspect before any reuse")
    venv.EnvBuilder(with_pip=True,system_site_packages=False).create(env)
    py=env/"Scripts/python.exe"
    cmd=[str(py),"-m","pip","--isolated","install","--index-url","https://pypi.org/simple","--only-binary=:all:","--no-deps","--disable-pip-version-check","--retries","0","--timeout","20","--report",str(root/"pip-install-report.json")]+[n+"=="+v for n,v in pins.items()]
    with (root/"pip-install.log").open("w",encoding="utf-8") as log:
        result=subprocess.run(cmd,stdout=log,stderr=subprocess.STDOUT,timeout=240)
    report["pip_exit_code"]=result.returncode
    if result.returncode!=0:
        raise RuntimeError("Pinned binary installation failed; inspect pip-install.log, do not retry blindly")
    report["status"]="READY_FOR_SYNTHETIC_TESTS"
    report["pip_install_report_sha256"]=hashlib.sha256((root/"pip-install-report.json").read_bytes()).hexdigest()
except Exception as exc:
    report["status"]="BLOCKED"
    report["error"]=type(exc).__name__+": "+str(exc)
out.write_text(json.dumps(report,indent=2)+"\n",encoding="utf-8")
print(json.dumps(report))
raise SystemExit(0 if report["status"]=="READY_FOR_SYNTHETIC_TESTS" else 1)
