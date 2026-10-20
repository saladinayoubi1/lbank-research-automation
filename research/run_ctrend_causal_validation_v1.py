"""Reproducible synthetic technical validation; never acquires market inputs."""
from __future__ import annotations
import argparse
from datetime import datetime,timezone
import hashlib
import importlib.metadata
import io
import json
from pathlib import Path
import platform
import sys
import time
import unittest

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--subset",choices=("all","features-wallet"),default="all")
    parser.add_argument("--report",type=Path,required=True)
    args=parser.parse_args()
    root=Path(__file__).resolve().parents[1]
    sys.path[:0]=[str(root),str(root/"tests")]
    patterns=(["test_nexus_ctrend_causal_*.py"] if args.subset=="all" else
        ["test_nexus_ctrend_causal_features_v1.py","test_nexus_ctrend_causal_wallet_v1.py"])
    suite=unittest.TestSuite()
    for pattern in patterns:
        suite.addTests(unittest.defaultTestLoader.discover(str(root/"tests"),pattern=pattern))
    count=suite.countTestCases()
    stream=io.StringIO()
    started=datetime.now(timezone.utc).isoformat()
    tick=time.monotonic()
    result=unittest.TextTestRunner(stream=stream,verbosity=2).run(suite)
    duration=time.monotonic()-tick
    versions={"python":platform.python_version(),"platform":platform.platform()}
    for name in ("numpy","scipy","scikit-learn"):
        try: versions[name]=importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError: versions[name]=None
    paths=list((root/"research").glob("*ctrend*.*"))+list((root/"tests").glob("test_nexus_ctrend_causal_*.py"))
    manifest={str(p.relative_to(root)).replace("\\","/"):hashlib.sha256(p.read_bytes()).hexdigest()
              for p in sorted(paths) if p.is_file()}
    report={"schema":"nexus.ctrend-causal-synthetic-validation.v1",
        "started_at_utc":started,"duration_seconds":duration,"subset":args.subset,
        "environment":versions,"discovered":count,"tests_run":result.testsRun,
        "failures":len(result.failures),"errors":len(result.errors),"skipped":len(result.skipped),
        "success":result.wasSuccessful() and result.testsRun==count and count>0,
        "evidence_class":"synthetic","financial_backtest":False,
        "demo_admitted":False,"paper_writer_enabled":False,"live_enabled":False,
        "real_orders":0,"protected_future_data_read":False,
        "sha256":manifest,"test_output":stream.getvalue()}
    args.report.parent.mkdir(parents=True,exist_ok=True)
    args.report.write_text(json.dumps(report,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    print(json.dumps({k:v for k,v in report.items() if k not in ("sha256","test_output")},ensure_ascii=False))
    if not report["success"]:
        print(stream.getvalue())
    return 0 if report["success"] else 1

if __name__=="__main__":raise SystemExit(main())
