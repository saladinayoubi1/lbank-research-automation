"""Read-only independent check after the corrected apply was denied."""
import hashlib
import importlib.util
import json
from pathlib import Path
from datetime import datetime, timezone

RUN = Path("E:\\NEXUS-QA\\rdc-l1-task-active-correction-20261014T084420Z\\apply-retry-20261014T091011Z")
HELPER = Path(r"E:\NEXUS-QA\rdc-l1-task-active-correction-20261014T084420Z\adopt_nexus_rdc_l1_task.py")
SOURCE, CODE = "ab27ace2df7a967192dd04e87eef749e1c90e410", "5d310bb776eef3f388bece360c8487ec70a6703261a11b09b60c5295f7aad89b"
assert hashlib.sha256(HELPER.read_bytes()).hexdigest() == CODE, "Reviewed source changed"
receipt = json.loads((RUN / "receipt.json").read_text(encoding="utf-8"))
assert receipt["phase"] == "FAILED_CLOSED" and receipt["stop_intent"] is False and receipt["task_run_requests"] == 0
assert receipt["source_sha"] == SOURCE and receipt["code_sha256"] == CODE
out = RUN / "independent-unchanged"
out.mkdir(exist_ok=False)
spec = importlib.util.spec_from_file_location("bound_l1_controller",str(HELPER))
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
backend = m.NativeBackend(out,SOURCE,CODE)
try:
    task = backend.preflight(False)
    # Reads exact source/file/task/owner/SDK fingerprints and holds query-only handles.
    assert task["xml_sha256"] == m.TASK_SHA and task["enabled"] is True
    assert Path(m.STARTUP).read_bytes() == (RUN / "startup.before").read_bytes()
    clients, supervisors, launchers = backend.census()
    protected = []
    for pid,ticks in ((9040,"134364067357038294"),(11520,"134363995178564217")):
        row=backend.inspect(pid)
        assert row["creation_filetime"] == ticks, "Protected console/Explorer changed"
        protected.append({k:v for k,v in row.items() if k!="argv"})
    result={"schema":"nexus.rdc-l1-adoption-denied-independent-check.v1","phase":"UNCHANGED_AFTER_ACCESS_DENIED",
      "checked_at_utc":datetime.now(timezone.utc).isoformat(),"controller_source_sha":SOURCE,"controller_sha256":CODE,
      "live_enabled":False,"task_run_requests":0,"sdk_stop_intent":False,"read_only":True,"task":task,
      "startup_sha256":hashlib.sha256(Path(m.STARTUP).read_bytes()).hexdigest(),
      "startup_matches_backup":True,"bound_file_hashes":{p:hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in m.FILES},
      "sdk_remote_clients":[{k:v for k,v in row.items() if k!="argv"} for row in clients],
      "cjs_supervisors":len(supervisors),"npm_remote_launchers":[row["pid"] for row in launchers],
      "old_exact_sdk_identities_still_verified":True,"protected_processes":protected,
      "worker_os_exit_independently_captured":False,
      "remaining_blocker":"Windows E_ACCESSDENIED at changing existing task Enabled; no third apply attempted"}
    (out/"check.json").write_text(json.dumps(result,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    print(json.dumps({"phase":result["phase"],"old_exact_sdk_client":clients[0]["pid"],"task_enabled":task["enabled"],"live_enabled":False}),flush=True)
finally:
    backend.close()
