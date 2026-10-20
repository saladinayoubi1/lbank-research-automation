"""Verify pytest collection in the isolated CTREND test environment."""
from pathlib import Path
from datetime import datetime,timezone
import hashlib,json,os,subprocess,sys
root=Path(r"E:\NEXUS-QA\ctrend-causal-full-20261020")
py=root/"venv/Scripts/python.exe"
project=root/"project"
env=dict(os.environ,PYTHONDONTWRITEBYTECODE="1",OPENBLAS_NUM_THREADS="1",MKL_NUM_THREADS="1",OMP_NUM_THREADS="1")
pins=["pytest==9.1.1","iniconfig==2.3.0","packaging==26.3","pluggy==1.6.0","Pygments==2.20.0"]
with (root/"pytest-collection-install.log").open("w",encoding="utf-8") as log:
    install=subprocess.run([str(py),"-m","pip","--isolated","install","--index-url","https://pypi.org/simple","--only-binary=:all:","--disable-pip-version-check","--retries","0","--timeout","20","--report",str(root/"pytest-collection-pip-report.json")]+pins,stdout=log,stderr=subprocess.STDOUT,timeout=90)
assert install.returncode==0,"Test tooling install failed"
check=subprocess.run([str(py),"-m","pip","check"],env=env,capture_output=True,text=True,timeout=30)
assert check.returncode==0,check.stdout+check.stderr
files=["tests/test_nexus_ctrend_causal_features_v1.py","tests/test_nexus_ctrend_causal_model_v1.py","tests/test_nexus_ctrend_causal_wallet_v1.py","tests/test_nexus_ctrend_causal_pipeline_v1.py","tests/test_nexus_ctrend_intake_guard_v1.py"]
result=subprocess.run([str(py),"-m","pytest","--collect-only","-q"]+files,cwd=project,env=env,capture_output=True,text=True,timeout=60)
report={"schema":"nexus.ctrend-ci-pytest-collection-fix.v1","recorded_at_utc":datetime.now(timezone.utc).isoformat(),"scope":"Only59CTRENDtests in isolated research project; hosted full-repository CI remains separate","pytest_version":"9.1.1","install_exit":install.returncode,"pip_check_exit":check.returncode,"collection_exit":result.returncode,"success":result.returncode==0 and "59 tests collected" in result.stdout,"test_execution":False,"collection_only":True,"code_files_unchanged":True,"financial_backtest":False,"demo_admitted":False,"orders":0,"output":result.stdout+result.stderr}
(root/"pytest-collection-validation.json").write_bytes((json.dumps(report,indent=2)+"\n").encode())
print(json.dumps({k:v for k,v in report.items() if k!="output"}))
if not report["success"]:print(result.stdout+result.stderr)
raise SystemExit(0 if report["success"] else 1)
