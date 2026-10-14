"""Stage hash-bound research files and run native source tests; zero market jobs."""
from datetime import datetime, timezone
from pathlib import Path
import argparse, hashlib, importlib.util, io, json, os, platform, sys, time, unittest

def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()
def require(ok,message):
    if not ok: raise ValueError(message)
def put(path,value):
    temporary=path.with_suffix(path.suffix+".tmp")
    temporary.write_text(json.dumps(value,sort_keys=True,indent=2)+"\n",encoding="utf-8")
    temporary.replace(path)
def now(): return datetime.now(timezone.utc).isoformat()

parser=argparse.ArgumentParser()
parser.add_argument("--config",type=Path,required=True)
parser.add_argument("--config-sha",required=True)
parser.add_argument("--source-sha",required=True)
args=parser.parse_args()
require(sha(args.config)==args.config_sha,"Staging payload bytes changed")
config=json.loads(args.config.read_text(encoding="utf-8"))
root=args.config.parent
status_path=root/"native-status.json"
(root/"native-execution.lock").open("x").close()
start=time.monotonic()
source=root/"source"
def status(state,**extra):
    put(status_path,dict(schema="nexus.butterfly-v8-native-source-gate.v1",status=state,
        source_sha=args.source_sha,host=os.environ.get("COMPUTERNAME"),checked_at_utc=now(),
        research_only=True,live_enabled=False,market_backtests_executed=0,**extra))
try:
    require(platform.system()=="Windows" and os.environ.get("COMPUTERNAME")=="DESKTOP-F4SA4VL"
            and not sys.flags.optimize and sys.version_info[:2]==(3,12),"Wrong native lane/runtime")
    require(config["source_sha"]==args.source_sha,"Payload source differs")
    status("VERIFYING_BASE_SOURCE")
    base=Path(r"E:\NEXUS-QA\utc-slot-volume-v7-20261014\source")
    require(not source.exists(),"New source directory already exists; do not replay")
    source.mkdir()
    for relative,expected in config["base_file_sha256"].items():
        old=base/relative; target=source/relative
        require(not old.is_symlink() and sha(old)==expected,"Frozen v7 dependency changed: "+relative)
        require(target.resolve().is_relative_to(source.resolve()),"Unsafe source path")
        target.parent.mkdir(parents=True,exist_ok=True)
        target.write_bytes(old.read_bytes())
    for relative,text in config["new_files"].items():
        target=source/relative
        require(target.resolve().is_relative_to(source.resolve()),"Unsafe new source path")
        target.parent.mkdir(parents=True,exist_ok=True)
        target.write_bytes(text.encode("utf-8"))
        require(sha(target)==config["new_file_sha256"][relative],"New source bytes differ: "+relative)
    expected={**config["base_file_sha256"],**config["new_file_sha256"]}
    require({p:sha(source/p) for p in expected}==expected,"Staged source differs")
    sys.path.insert(0,str(source))
    import numpy,pandas,pyarrow
    require((numpy.__version__,pandas.__version__,pyarrow.__version__)==("2.3.5","2.3.3","23.0.1"),
            "Existing pinned native dependencies changed")
    import nexus_composite_strategy_research as engine
    prior=Path(r"E:\NEXUS-QA\utc-slot-volume-v7-20261014\producer\novelty-ledger.json")
    require(sha(prior)==config["previous_ledger_file_sha256"],"Original v7 ledger bytes changed")
    ledger=engine.load_ledger(prior)
    require(ledger["ledger_digest"]==config["previous_ledger_digest"],"Original v7 ledger semantics changed")
    choices=engine._frontier_configs_to_screen(ledger)
    require(len(choices)==1 and choices[0]["mechanism"]=="factory_causal_bullish_butterfly"
            and choices[0]["risk_variant"]==0,"Terminal v7 ledger did not advance to one fixed Butterfly")
    status("RUNNING_SOURCE_TESTS",candidate=choices[0])
    suite=unittest.TestSuite()
    for name in ("test_nexus_causal_butterfly_features","test_nexus_causal_slot_volume_features"):
        spec=importlib.util.spec_from_file_location(name,source/"tests"/(name+".py"))
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        suite.addTests(unittest.defaultTestLoader.loadTestsFromModule(module))
    output=io.StringIO()
    result=unittest.TextTestRunner(stream=output,verbosity=2).run(suite)
    (root/"native-source-tests.txt").write_text(output.getvalue(),encoding="utf-8")
    require(result.testsRun==39 and result.wasSuccessful(),"Native source test failure/count differs")
    require({p:sha(source/p) for p in expected}==expected and sha(prior)==config["previous_ledger_file_sha256"],
            "Source/prior ledger changed during tests")
    receipt=dict(schema="nexus.butterfly-v8-native-source-receipt.v1",source_sha=args.source_sha,
        completed_at_utc=now(),host=os.environ.get("COMPUTERNAME"),native_windows=True,
        python=sys.version,numpy=numpy.__version__,pandas=pandas.__version__,pyarrow=pyarrow.__version__,
        candidate_config=choices[0],source_file_sha256=expected,
        previous_ledger_path=str(prior),previous_ledger_file_sha256=sha(prior),
        previous_ledger_digest=ledger["ledger_digest"],tests_run=result.testsRun,
        failures=len(result.failures),errors=len(result.errors),expected_native_exit_code=0,
        elapsed_seconds=round(time.monotonic()-start,3),independent_strategy_qa=False,
        market_backtests_executed=0,research_only=True,owner_demo_admission=False,
        auto_demo_promotion=False,live_enabled=False)
    receipt["receipt_digest"]=engine.digest(receipt)
    put(root/"native-source-receipt.json",receipt)
    status("NATIVE_SOURCE_GATE_PASS",receipt_sha256=sha(root/"native-source-receipt.json"),
           tests_run=39,expected_native_exit_code=0,elapsed_seconds=receipt["elapsed_seconds"])
    print(json.dumps({"status":"NATIVE_SOURCE_GATE_PASS","tests_run":39,"source_sha":args.source_sha,
                      "market_backtests_executed":0,"live_enabled":False}),flush=True)
except Exception as exc:
    status("NATIVE_SOURCE_GATE_FAILED",error_type=type(exc).__name__,error=str(exc)[:1200])
    raise

