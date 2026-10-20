"""Run source-bound synthetic IOC regression checks; never load market inputs."""
from pathlib import Path
import argparse
from datetime import datetime, timezone
import hashlib
import io
import json
import platform
import sys
import time
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
SUITES={
    "test_nexus_ctrend_bybit_spot_ioc_v1.py":30,
    "test_nexus_ctrend_causal_wallet_v1.py":18,
    "test_nexus_ctrend_intake_guard_v1.py":10,
}
SOURCES=["research/nexus_ctrend_bybit_spot_ioc_v1.py",
    "research/ctrend_bybit_spot_ioc_technical_v1.json",
    "research/nexus_ctrend_causal_wallet_v1.py",
    "research/nexus_ctrend_intake_guard_v1.py",
    "research/run_ctrend_spot_ioc_validation_v1.py",
    *("tests/"+name for name in SUITES)]


def main():
    parser=argparse.ArgumentParser();parser.add_argument("--report",type=Path,required=True)
    args=parser.parse_args()
    if args.report.exists():
        parser.error("Use a new report path; source-bound evidence is write-once")
    started=datetime.now(timezone.utc).isoformat();clock=time.perf_counter()
    hashes={name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in SOURCES}
    reports=[]
    for name,expected in SUITES.items():
        suite=unittest.TestLoader().discover(str(ROOT/"tests"),pattern=name)
        output=io.StringIO()
        result=unittest.TextTestRunner(stream=output,verbosity=2).run(suite)
        success=(result.wasSuccessful() and result.testsRun==expected and not result.skipped
                 and not result.expectedFailures and not result.unexpectedSuccesses)
        reports.append(dict(pattern=name,expected=expected,tests_run=result.testsRun,
            failures=len(result.failures),errors=len(result.errors),skipped=len(result.skipped),
            expected_failures=len(result.expectedFailures),success=success,log=output.getvalue()))
    unchanged=all(hashlib.sha256((ROOT/name).read_bytes()).hexdigest()==sha for name,sha in hashes.items())
    report=dict(schema="nexus.ctrend-spot-ioc-validation.v1",started_at_utc=started,
        finished_at_utc=datetime.now(timezone.utc).isoformat(),duration_seconds=time.perf_counter()-clock,
        environment=dict(python=platform.python_version(),platform=platform.platform()),
        suites=reports,expected_tests=sum(SUITES.values()),tests_run=sum(r["tests_run"] for r in reports),
        source_sha256=hashes,source_unchanged_after_execution=unchanged,
        success=unchanged and all(r["success"] for r in reports),evidence_class="synthetic",
        financial_backtest=False,demo_admitted=False,paper_writer_enabled=False,
        live_enabled=False,real_orders=0,protected_future_data_read=False)
    args.report.parent.mkdir(parents=True,exist_ok=True)
    with args.report.open("x",encoding="utf-8") as stream:json.dump(report,stream,indent=2);stream.write("\n")
    print(json.dumps({k:v for k,v in report.items() if k not in ("suites","source_sha256")}))
    return 0 if report["success"] else 1


if __name__=="__main__":raise SystemExit(main())
