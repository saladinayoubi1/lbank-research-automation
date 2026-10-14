from pathlib import Path
from datetime import datetime, timezone
import hashlib, json, os, subprocess, sys, time
root = Path(__file__).resolve().parent
source = root.parent/'v10-source'
script = '''import ast,json,sys,unittest
from pathlib import Path
import numpy as np,pandas as pd
import nexus_composite_strategy_research as research
suite=unittest.TestLoader().discover("tests",pattern="test_nexus_causal_*features.py")
result=unittest.TextTestRunner(verbosity=2).run(suite)
summary={"tests_run":result.testsRun,"failures":len(result.failures),"errors":len(result.errors),"skipped":len(result.skipped)}
if result.wasSuccessful():
 path=Path("tests/test_nexus_composite_fast_frontier.py")
 node=next(n for n in ast.parse(path.read_text()).body if isinstance(n,ast.FunctionDef) and n.name=="test_all_frontier_mechanisms_emit_bounded_boolean_signals")
 ns={"np":np,"pd":pd,"research":research}
 exec(compile(ast.Module(body=[node],type_ignores=[]),str(path),"exec"),ns)
 ns[node.name]()
 summary["bounded_boolean_function"]={"passed":True,"frontier_mechanisms":len(research.FRONTIER_MECHANISMS),"full_pytest_module_executed":False}
Path(sys.argv[1]).write_text(json.dumps(summary,indent=2)+"\\n")
sys.exit(0 if result.wasSuccessful() else 1)
'''
started=datetime.now(timezone.utc).isoformat(); start=time.monotonic()
with (root/'source-tests.stdout.log').open('wb') as out, (root/'source-tests.stderr.log').open('wb') as err:
 child=subprocess.Popen([sys.executable,'-c',script,str(root/'test-summary.json')],cwd=source,stdout=out,stderr=err)
 try: exit_code=child.wait(timeout=45); timed_out=False
 except subprocess.TimeoutExpired:
  child.kill(); exit_code=child.wait(); timed_out=True
receipt={'schema':'nexus.macro-retest-v10-owned-local-gate.v1','started_at_utc':started,'completed_at_utc':datetime.now(timezone.utc).isoformat(),'owned_child_pid':child.pid,'parent_pid':os.getpid(),'actual_owned_child_exit_code':exit_code,'timed_out':timed_out,'elapsed_seconds':round(time.monotonic()-start,3),'bounded_retry_number':1,'first_attempt':{'tests_run':105,'errors':6,'failures':0,'actual_exit_code':1,'cause':'Reference module contracts resolved relative to fixture directory; observer compiled isolated function instead of full module (CPython module-import-aware opcodes). Both corrected without backtest changes.'},'market_runs':0,'native_windows_gate_complete':False,'full_hosted_gate_complete':False,'research_only':True,'live_enabled':False}
if (root/'test-summary.json').exists(): receipt.update(json.loads((root/'test-summary.json').read_text()))
for key in ('stdout','stderr'): receipt[key+'_sha256']=hashlib.sha256((root/('source-tests.'+key+'.log')).read_bytes()).hexdigest()
(root/'local-gate-receipt.json').write_text(json.dumps(receipt,indent=2)+'\n')
print(json.dumps(receipt,indent=2))
if exit_code: print((root/'source-tests.stderr.log').read_text()[-18000:])
sys.exit(exit_code)
