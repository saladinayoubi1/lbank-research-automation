from datetime import datetime, timezone
import hashlib, importlib.util, json, os, platform, sys, time, unittest
from pathlib import Path

ROOT=Path(r"E:\NEXUS-QA\utc-slot-volume-v7-20261014")
SOURCE="7cab4f0368823ef3dd9dec79f572bd05721e2316"
STATUS=ROOT/"native-gate-continuation-status.json"
def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()
def put(path,obj):
    tmp=path.with_suffix(path.suffix+".tmp")
    tmp.write_text(json.dumps(obj,sort_keys=True,indent=2),encoding="utf-8")
    tmp.replace(path)
def status(state,**extra):
    put(STATUS,dict(status=state,checked_at_utc=datetime.now(timezone.utc).isoformat(),
        source_sha=SOURCE,research_only=True,live_enabled=False,market_backtests_executed=0,**extra))
(ROOT/"native-gate-continuation.lock").open("x").close()
start=time.monotonic()
try:
    if sys.flags.optimize or platform.system() != "Windows":
        raise ValueError("native Windows gate with enabled assertions required")
    prior_stage=json.loads((ROOT/"native-gate-status.json").read_text())
    if prior_stage["status"] != "NATIVE_SOURCE_STAGE_FAILED" or prior_stage["market_backtests_executed"] != 0:
        raise ValueError("incorrect continuation predecessor")
    source=ROOT/"source"
    frozen=source/"docs/evidence/utc-slot-volume-v7-20261013"
    freeze=json.loads((frozen/"study-freeze.json").read_text())
    routing=json.loads((frozen/"routing-fix/freeze-amendment.json").read_text())
    serial=json.loads((ROOT/"ledger-serialization-amendment.json").read_text())
    if serial["source_sha"] != SOURCE or serial["original_freeze_digest"] != freeze["freeze_digest"] or serial["original_routing_amendment_digest"] != routing["amendment_digest"]:
        raise ValueError("serialization amendment binding failed")
    fixture=source/serial["file"]
    raw=fixture.read_bytes()
    if sha(fixture)!=serial["exact_github_lf_sha256"] or hashlib.sha1(b"blob "+str(len(raw)).encode()+b"\0"+raw).hexdigest()!=serial["exact_github_blob_sha1"]:
        raise ValueError("fixture differs from exact GitHub blob")
    if hashlib.sha256(raw.replace(b"\r\n",b"\n").replace(b"\n",b"\r\n")).hexdigest()!=serial["original_crlf_sha256"]:
        raise ValueError("original freeze CRLF reconstruction failed")
    value=json.loads(raw)
    unsigned={k:v for k,v in value.items() if k!="ledger_digest"}
    if hashlib.sha256(json.dumps(unsigned,sort_keys=True,separators=(",",":")).encode()).hexdigest()!=serial["canonical_ledger_digest"] or value["ledger_digest"]!=serial["canonical_ledger_digest"]:
        raise ValueError("ledger semantics changed")
    expected={**freeze["file_sha256"],**routing["file_sha256"],serial["file"]:serial["exact_github_lf_sha256"]}
    actual={p:sha(source/p) for p in expected}
    if actual != expected: raise ValueError("frozen source mismatch")
    sys.path.insert(0,str(source))
    import numpy, pandas, pyarrow
    import nexus_composite_strategy_research as engine
    prior=Path(r"E:\NEXUS-QA\causal-jump-v6-20261013\producer\novelty-ledger.json")
    ledger=engine.load_ledger(prior)
    configs=engine._frontier_configs_to_screen(ledger)
    if ledger["ledger_digest"]!=freeze["previous_ledger_digest"] or configs!=[freeze["candidate_config"]]:
        raise ValueError("candidate or prior ledger changed")
    binding=dict(source_sha=SOURCE,source_file_sha256=actual,
        source_archive_sha256=sha(ROOT/"exact-source.zip"),serialization_amendment_sha256=sha(ROOT/"ledger-serialization-amendment.json"),
        previous_ledger_path=str(prior),previous_ledger_file_sha256=sha(prior),previous_ledger_digest=ledger["ledger_digest"],
        candidate_config=configs[0],python=sys.version,numpy=numpy.__version__,pandas=pandas.__version__,
        pyarrow=pyarrow.__version__,host=os.environ.get("COMPUTERNAME"),platform=platform.platform(),
        native_windows=True,producer_host_source_gate_only=True,independent_strategy_qa=False,research_only=True,live_enabled=False)
    put(ROOT/"native-source-binding.json",binding)
    status("RUNNING_NATIVE_SOURCE_GATE",source_binding_sha256=sha(ROOT/"native-source-binding.json"))
    harness_path=frozen/"routing-fix/run_targeted_regressions.py"
    spec=importlib.util.spec_from_file_location("v7_frozen_harness",harness_path)
    harness=importlib.util.module_from_spec(spec);spec.loader.exec_module(harness)
    suite=unittest.TestSuite(harness.selected_cases())
    suite.addTests(unittest.TestLoader().discover(str(source/"tests"),pattern="test_nexus_causal_*features.py"))
    with (ROOT/"native-gate.stdout.log").open("w",encoding="utf-8") as out:
        result=unittest.TextTestRunner(stream=out,verbosity=2).run(suite)
    exit_code=0 if result.wasSuccessful() else 1
    (ROOT/"native-gate-exit.txt").write_text(str(exit_code),encoding="ascii")
    receipt=dict(schema="nexus.v7-native-source-gate.v1",source_sha=SOURCE,
        checked_at_utc=datetime.now(timezone.utc).isoformat(),exit_code=exit_code,test_count=result.testsRun,
        failures=len(result.failures),errors=len(result.errors),elapsed_seconds=time.monotonic()-start,
        source_binding_sha256=sha(ROOT/"native-source-binding.json"),stdout_sha256=sha(ROOT/"native-gate.stdout.log"),
        frozen_harness_sha256=sha(harness_path),native_windows=True,host=os.environ.get("COMPUTERNAME"),
        market_backtests_executed=0,independent_strategy_qa=False,research_only=True,live_enabled=False)
    put(ROOT/"native-gate-receipt.json",receipt)
    status("NATIVE_SOURCE_GATE_PASS" if exit_code==0 else "NATIVE_SOURCE_GATE_FAILED",exit_code=exit_code,
           receipt_sha256=sha(ROOT/"native-gate-receipt.json"),test_count=result.testsRun)
    print(json.dumps(receipt));raise SystemExit(exit_code)
except Exception as exc:
    status("NATIVE_SOURCE_CONTINUATION_FAILED",error_type=type(exc).__name__)
    (ROOT/"native-continuation-error.txt").write_text(type(exc).__name__+": "+str(exc),encoding="utf-8")
    raise
