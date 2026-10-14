"""Native synthetic source tests only; no market producer."""
from datetime import datetime,timezone
from pathlib import Path
import ast,hashlib,importlib.util,io,json,os,platform,sys,time,unittest
ROOT=Path(__file__).parent;SOURCE=ROOT/"source";start=time.monotonic()
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def load(p):return json.loads(p.read_text(encoding="utf-8"))
def require(ok,message):
    if not ok:raise ValueError(message)
config=load(ROOT/"native-input-binding.json")
require(platform.system()=="Windows" and os.environ.get("COMPUTERNAME")=="DESKTOP-F4SA4VL"
        and sys.version_info[:2]==(3,12) and not sys.flags.optimize,"Wrong native lane/runtime")
for name,expected in config["source_file_sha256"].items():
    require(sha(SOURCE/name)==expected,"Native source differs before tests: "+name)
prior=Path(config["previous_ledger_path"])
require(sha(prior)==config["previous_ledger_file_sha256"],"Completed predecessor bytes differ")
sys.path.insert(0,str(SOURCE))
import numpy,pandas,pyarrow
require((numpy.__version__,pandas.__version__,pyarrow.__version__)==("2.3.5","2.3.3","23.0.1"),"Pinned dependencies differ")
import nexus_composite_strategy_research as engine
prereg=load(SOURCE/"research/causal_elliott_wave12_v9_preregistration.json")
previous=engine.load_ledger(prior)
require(previous["ledger_digest"]==config["previous_ledger_digest"],"Wrong terminal predecessor")
choices=engine._frontier_configs_to_screen(previous)
require(choices==[{**prereg["candidate_config"],"fingerprint":prereg["candidate_config_fingerprint"]}],"Expected exactly the fixed new Elliott candidate")
suite=unittest.TestSuite()
for name in ("test_nexus_causal_butterfly_features","test_nexus_causal_slot_volume_features","test_nexus_causal_elliott_wave12_features"):
    spec=importlib.util.spec_from_file_location(name,SOURCE/"tests"/(name+".py"))
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    suite.addTests(unittest.defaultTestLoader.loadTestsFromModule(module))
output=io.StringIO();result=unittest.TextTestRunner(stream=output,verbosity=2).run(suite)
(ROOT/"native-source-tests.txt").write_bytes(output.getvalue().encode("utf-8"))
require(result.testsRun==72 and result.wasSuccessful(),"Native source test failure/count differs")
path=SOURCE/"tests/test_nexus_composite_fast_frontier.py"
node=next(n for n in ast.parse(path.read_text(encoding="utf-8")).body
          if isinstance(n,ast.FunctionDef) and n.name=="test_all_frontier_mechanisms_emit_bounded_boolean_signals")
namespace={"np":numpy,"pd":pandas,"research":engine}
exec(compile(ast.Module(body=[node],type_ignores=[]),str(path),"exec"),namespace)
namespace[node.name]()
for name,expected in config["source_file_sha256"].items():
    require(sha(SOURCE/name)==expected,"Native source changed during tests: "+name)
require(sha(prior)==config["previous_ledger_file_sha256"],"Completed predecessor changed during tests")
receipt={"schema":"nexus.elliott-v9-native-source-test-result.v1",
 "completed_at_utc":datetime.now(timezone.utc).isoformat(),"source_sha":config["source_sha"],
 "host":os.environ.get("COMPUTERNAME"),"native_windows":True,"python":sys.version,
 "numpy":numpy.__version__,"pandas":pandas.__version__,"pyarrow":pyarrow.__version__,
 "tests_run":72,"new_elliott_methods":33,"prior_source_regression_methods":39,"failures":0,"errors":0,
 "source_schema_regression_functions":1,"source_schema_frontier_mechanisms":110,
 "full_pytest_module_executed":False,"candidate_config":choices[0],
 "source_file_sha256":config["source_file_sha256"],"source_and_previous_ledger_unchanged":True,
 "previous_ledger_digest":previous["ledger_digest"],"previous_ledger_file_sha256":sha(prior),
 "test_log_sha256":sha(ROOT/"native-source-tests.txt"),"elapsed_seconds":round(time.monotonic()-start,3),
 "market_backtests_submitted":0,"independent_strategy_qa_complete":False,
 "research_only":True,"owner_demo_admission":False,"auto_demo_promotion":False,"live_enabled":False}
receipt["receipt_digest"]=engine.digest(receipt)
(ROOT/"native-worker-receipt.json").write_bytes((json.dumps(receipt,sort_keys=True,indent=2,allow_nan=False)+"\n").encode())
print(json.dumps({"status":"NATIVE_WORKER_TESTS_PASS","tests_run":72,"extra_source_regression_functions":1,
                  "source_sha":config["source_sha"],"market_backtests_submitted":0,"live_enabled":False}),flush=True)
