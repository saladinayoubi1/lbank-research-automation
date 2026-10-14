"""One bounded test-only exit proof after the first RDC session was unavailable."""
from pathlib import Path
from datetime import datetime, timezone
import hashlib, importlib.util, json, os, platform, subprocess, sys, unittest

ROOT=Path("E:\\NEXUS-QA\\causal-butterfly-v8-20261014T104229Z")
SOURCE=ROOT/"source"
SHA="2b89f6e89abdacc16b3288b9fd9ebcb3bdea7e69"
def hash_file(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def require(ok,message):
    if not ok:raise ValueError(message)
def verify():
    require(platform.system()=="Windows" and os.environ.get("COMPUTERNAME")=="DESKTOP-F4SA4VL"
            and sys.version_info[:2]==(3,12) and not sys.flags.optimize,"Wrong test lane/runtime")
    require(hash_file(ROOT/"native-source-receipt.json")=="cd61f544e8c0e5dda583139608aaacd44270234658dede844c07effca5d16dc0","Completed native source receipt differs")
    receipt=json.loads((ROOT/"native-source-receipt.json").read_text())
    require(receipt["source_sha"]==SHA and receipt["tests_run"]==39 and receipt["failures"]==receipt["errors"]==0,"First test receipt is not passed")
    require(all(hash_file(SOURCE/p)==h for p,h in receipt["source_file_sha256"].items()),"Source changed")
    require(hash_file(Path(receipt["previous_ledger_path"]))==receipt["previous_ledger_file_sha256"],"Prior ledger changed")
    return receipt
prior=verify()
if "--child" in sys.argv:
    sys.path.insert(0,str(SOURCE))
    suite=unittest.TestSuite()
    for name in ("test_nexus_causal_butterfly_features","test_nexus_causal_slot_volume_features"):
        spec=importlib.util.spec_from_file_location(name,SOURCE/"tests"/(name+".py"))
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        suite.addTests(unittest.defaultTestLoader.loadTestsFromModule(module))
    result=unittest.TextTestRunner(verbosity=2).run(suite)
    verify()
    raise SystemExit(0 if result.wasSuccessful() and result.testsRun==39 else 1)
out=ROOT/"exit-proof"
out.mkdir(exist_ok=False)
try:
    with (out/"stdout.txt").open("wb") as stdout,(out/"stderr.txt").open("wb") as stderr:
        child=subprocess.run([sys.executable,str(Path(__file__).resolve()),"--child"],
            cwd=SOURCE,stdin=subprocess.DEVNULL,stdout=stdout,stderr=stderr,timeout=120)
    verify()
    value={"schema":"nexus.butterfly-v8-native-true-exit-proof.v1","source_sha":SHA,
      "checked_at_utc":datetime.now(timezone.utc).isoformat(),"true_child_exit_code":child.returncode,
      "native_source_tests":39,"bounded_test_only_retry_due_to_lost_first_rdc_session":True,
      "original_parent_os_exit_independently_captured":False,"deadline_seconds":120,
      "source_and_prior_ledger_unchanged":True,"stdout_sha256":hash_file(out/"stdout.txt"),
      "stderr_sha256":hash_file(out/"stderr.txt"),"market_backtests_executed":0,
      "research_only":True,"live_enabled":False}
    (out/"receipt.json").write_text(json.dumps(value,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(value),flush=True)
    raise SystemExit(child.returncode)
except subprocess.TimeoutExpired:
    (out/"failure.json").write_text(json.dumps({"status":"DEADLINE_FAILED","no_further_retry":True,
         "source_sha":SHA,"market_backtests_executed":0,"live_enabled":False}),encoding="utf-8")
    raise
