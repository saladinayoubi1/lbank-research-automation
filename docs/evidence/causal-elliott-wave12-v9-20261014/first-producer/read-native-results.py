"""Read existing completed artifacts and verify input bytes; never run a producer."""
from datetime import datetime, timezone
from pathlib import Path
import base64, hashlib, json, os, platform, sys, zlib

root=Path(r"E:\NEXUS-QA\causal-elliott-wave12-v9-first-producer-20261014T161923Z")
assert platform.system()=="Windows" and os.environ.get("COMPUTERNAME")=="DESKTOP-F4SA4VL"
assert not sys.flags.optimize
freeze=json.loads((root/'invocation-freeze.json').read_bytes())
sha=lambda path:hashlib.sha256(path.read_bytes()).hexdigest()
names=['parent-status.json','producer-status.json','producer-receipt.json','parent-exit-receipt.json',
       'producer-result-summary.json','producer/research-report.json','producer/novelty-ledger.json',
       'producer-input-binding.json','producer-command.json','native-staging-receipt.json','producer-exit.txt']
files={}
for name in names:
    raw=(root/name).read_bytes()
    files[name]={'sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw),
                 'zlib_base64':base64.b64encode(zlib.compress(raw,9)).decode()}
checks={}
for name,expected in freeze['source_component_sha256'].items():
    checks['source/'+name]={'sha256':sha(Path(freeze['source_root'])/name),'expected':expected}
for name,expected in freeze['source_gate_file_sha256'].items():
    checks['native-gate/'+name]={'sha256':sha(Path(freeze['source_gate_root'])/name),'expected':expected}
for row in freeze['raw_inputs']:
    checks['raw/'+row['relative_path']]={'sha256':sha(Path(row['path'])),'expected':row['raw_file_sha256']}
for name,path,expected in [
    ('previous-ledger',freeze['previous_ledger_path'],freeze['previous_ledger_file_sha256']),
    ('delivery-zip',freeze['delivery_zip_path'],freeze['delivery_zip_byte_sha256']),
    ('manifest',str(Path(freeze['archive_root'])/'REPLAY_DATASET_MANIFEST.json'),freeze['manifest_file_sha256']),
    ('market-wrapper',str(root/'run-v9-first-producer.py'),freeze['wrapper_sha256']),
    ('precheck',str(root/'V9_PRODUCER_PRECHECK.md'),freeze['precheck_sha256'])]:
    checks[name]={'sha256':sha(Path(path)),'expected':expected}
for name,item in checks.items():assert item['sha256']==item['expected'],name
parent=json.loads((root/'parent-status.json').read_bytes())
producer=json.loads((root/'producer-status.json').read_bytes())
assert parent['state']==producer['status']=='COMPLETE_RESEARCH_NOT_QUALIFIED'
assert parent['wrapper_actual_os_exit_code']==parent['producer_actual_os_exit_code']==producer['child_exit_code']==0
print('NATIVE_RESULT_PAYLOAD '+json.dumps({'schema':'nexus.elliott-v9-existing-native-results.v1',
      'observed_at_utc':datetime.now(timezone.utc).isoformat(),'run_root':str(root),
      'source_sha':freeze['source_sha'],'host':platform.node(),'files':files,'byte_checks':checks,
      'all_source_gate_raw_previous_invocation_checks_match':True,'market_producer_not_restarted':True,
      'research_only':True,'live_enabled':False},sort_keys=True),flush=True)
