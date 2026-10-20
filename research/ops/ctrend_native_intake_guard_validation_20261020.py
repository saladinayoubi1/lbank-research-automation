from pathlib import Path
from datetime import datetime,timezone
import hashlib,io,json,os,platform,sys,time,unittest
root=Path(r"E:\NEXUS-QA\ctrend-causal-full-20261020")
project=root/"project"
assert Path(sys.prefix).resolve()==(root/"venv").resolve()
payload=json.loads(Path(r"E:\NEXUS-QA\ctrend-intake-guard-stage-20261020.json").read_text(encoding="utf-8-sig"))
for rel,content in payload["files"].items():
    data=content.encode("utf-8")
    assert hashlib.sha256(data).hexdigest()==payload["sha256"][rel]
    p=project/rel
    if p.exists() and p.read_bytes()!=data:raise ValueError("Existing source differs: "+rel)
    p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(data)
sys.path[:0]=[str(project),str(project/"tests")]
from research.nexus_ctrend_intake_guard_v1 import preflight
contract=json.loads((project/"research/ctrend_real_intake_v1.json").read_bytes())
probe=json.loads((root/"real-source-probe.json").read_bytes())
allowed=preflight(probe["url"])
assert allowed["metadata_only"] and not allowed["financial_fetch_authorized"]
envelope=contract["historical_collection_envelope"]
annotation=preflight(probe["url"],coverage_start=envelope["start_inclusive_utc"],coverage_end=envelope["end_exclusive_utc"])
assert annotation["coverage_is_caller_annotation_only"] and not annotation["historical_vintage_certified"]
frozen=json.loads((project/"docs/evidence/ctrend-causal-20261020/laptop2-full-validation.json").read_bytes())
for rel,digest in frozen["sha256"].items():assert hashlib.sha256((project/rel).read_bytes()).hexdigest()==digest
stream=io.StringIO()
suite=unittest.defaultTestLoader.discover(str(project/"tests"),pattern="test_nexus_ctrend_intake_guard_v1.py")
tick=time.monotonic();result=unittest.TextTestRunner(stream=stream,verbosity=2).run(suite)
report={"schema":"nexus.ctrend-native-intake-guard-validation.v1","recorded_at_utc":datetime.now(timezone.utc).isoformat(),"python":platform.python_version(),"platform":platform.platform(),"isolated_prefix":sys.prefix,"tests_run":result.testsRun,"failures":len(result.failures),"errors":len(result.errors),"skipped":len(result.skipped),"success":result.wasSuccessful() and result.testsRun==10,"duration_seconds":time.monotonic()-tick,"sha256":payload["sha256"],"frozen_49_sources_unchanged":True,"prior_metadata_request_preflight":allowed,"preflight_executed_before_original_capture":False,"historical_coverage_is_only_annotation":True,"financial_backtest":False,"demo_admitted":False,"live_enabled":False,"real_orders":0,"test_output":stream.getvalue()}
(root/"native-intake-guard-validation.json").write_bytes((json.dumps(report,indent=2)+"\n").encode("utf-8"))
print(json.dumps({k:v for k,v in report.items() if k not in ("test_output","sha256","prior_metadata_request_preflight")}))
raise SystemExit(0 if report["success"] else 1)
