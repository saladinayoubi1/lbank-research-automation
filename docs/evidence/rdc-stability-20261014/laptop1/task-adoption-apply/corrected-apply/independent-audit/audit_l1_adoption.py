"""One independent read-only audit of the completed Laptop1 adoption."""
import importlib.util
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

APPLY = Path("E:\\NEXUS-QA\\rdc-l1-task-active-correction-20261014T084420Z\\apply-retry-20261014T091011Z")
HELPER = Path(r"E:\NEXUS-QA\rdc-l1-task-active-correction-20261014T084420Z\adopt_nexus_rdc_l1_task.py")
SOURCE, CODE = "ab27ace2df7a967192dd04e87eef749e1c90e410", "5d310bb776eef3f388bece360c8487ec70a6703261a11b09b60c5295f7aad89b"
AUDIT = APPLY / "independent-audit"

def require(ok, message):
    if not ok:
        raise ValueError(message)

def sha(data):
    return hashlib.sha256(data).hexdigest()

def load(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))

require(sha(HELPER.read_bytes()) == CODE, "Reviewed controller bytes changed")
receipt = load(APPLY / "receipt.json")
require(receipt["phase"] == "ADOPTED_AWAITING_INDEPENDENT_AUDIT", "Adoption is not complete; do not launch again")
require(receipt["source_sha"] == SOURCE and receipt["code_sha256"] == CODE, "Executed source differs")
require(receipt["stop_intent"] is True and receipt["task_run_requests"] == 1 and receipt["live_enabled"] is False, "Transaction boundary differs")
original = load(APPLY / "task.before.json")
exits = load(APPLY / "old-exits.json")
require({x["pid"] for x in exits} == {2032, 4000, 12764, 5520} and all(x["positive_exit"] for x in exits), "Old positive exits missing")

spec = importlib.util.spec_from_file_location("bound_l1_controller", str(HELPER))
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
AUDIT.mkdir(exist_ok=False)
backend = m.NativeBackend(AUDIT, SOURCE, CODE)
try:
    backend.refresh_guards(True)
    require(sha((APPLY / "startup.before").read_bytes()) == m.STARTUP_SHA, "Original Startup backup differs")
    require(sha(Path(m.STARTUP).read_bytes()) == sha(m.STARTUP_BYTES), "Startup delegation differs")
    task = backend.rpc("read")  # Separate COM read; no validation, registration, stop or Run.
    m.verify_task(task, original, True)
    require(task["state"] == 4 and task["instances"] == 1, "Task is not the sole running owner")
    clients, supervisors, launchers = backend.census()
    require(len(clients) == len(supervisors) == 1 and not launchers, "RDC census differs")
    client, supervisor = clients[0], supervisors[0]
    parent = backend.inspect(supervisor["ppid"])
    lock = load(Path(m.ROOT + r"\supervisor.json"))
    require(client["ppid"] == supervisor["pid"] and m.norm(m.ENTRY) in [m.norm(a) for a in client["argv"]], "Current SDK not owned by current CJS")
    require(lock["pid"] == supervisor["pid"], "CJS lock differs")
    require(m.norm(parent["exe"]) == m.norm(m.PS) and m.NODE_COMMAND in parent["argv"], "Current CJS task parent differs")
    for row in (client, supervisor, parent):
        require(row["owner"].casefold() == m.OWNER.casefold() and row["session_id"] == 1, "New owner/session differs")
    require(receipt["new_chain"] == {"client_pid":client["pid"],"supervisor_pid":supervisor["pid"],"task_action_pid":parent["pid"],"task_instances":1}, "Independent new graph differs from worker receipt")
    old = []
    for pid, (_, _, ticks, _) in m.TARGETS.items():
        if backend.psutil.pid_exists(pid):
            row = backend.inspect(pid)
            require(row["creation_filetime"] != ticks, "Original SDK identity is still alive")
            old.append({"pid":pid,"old_identity_absent":True,"pid_reused":True})
        else:
            old.append({"pid":pid,"old_identity_absent":True,"pid_reused":False})
    protected = []
    for pid, ticks, argv_hash in (
        (9040,"134364067357038294","f5f6b91e7a6153cd2c7ba0b6ed3c96676245643a6552add8d819121b7cd5b24a"),
        (11520,"134363995178564217","66c8d0291186b7d77e450bc691dde7f299286c9b33aa7f1fb810d563c46a7667")):
        row = backend.inspect(pid)
        require(row["creation_filetime"] == ticks and row["argv_json_sha256"] == argv_hash, "Protected console/Explorer identity changed")
        protected.append({k:v for k,v in row.items() if k != "argv"})
    runner_names = []
    gaps = []
    for proc in backend.psutil.process_iter(["pid","name"]):
        if (proc.info["name"] or "").casefold() in ("runner.listener.exe","runner.worker.exe"):
            runner_names.append(proc.info)
    worker = receipt["observer"]
    same_worker_present = False
    if backend.psutil.pid_exists(worker["pid"]):
        try:
            now = backend.inspect(worker["pid"])
            same_worker_present = now["creation_filetime"] == worker["creation_filetime"]
        except Exception as err:
            gaps.append({"pid":worker["pid"],"scope":"worker absence query","error_type":type(err).__name__})
    result = {"schema":"nexus.rdc-l1-task-adoption-independent-audit.v1","phase":"INDEPENDENT_AUDIT_PASS",
              "updated_utc":datetime.now(timezone.utc).isoformat(),"controller_source_sha":SOURCE,"controller_sha256":CODE,
              "independent_read_only":True,"audit_task_run_requests":0,"audit_process_terminations":0,
              "worker_os_exit_independently_captured":False,"original_worker_identity_still_present":same_worker_present,
              "live_enabled":False,"task":task,"new_processes":[{k:v for k,v in row.items() if k != "argv"} for row in (parent,supervisor,client)],
              "counts":{"sdk_remote_clients":1,"cjs_supervisors":1,"npm_remote_launchers":0,"task_instances":1},
              "startup_sha256":sha(Path(m.STARTUP).read_bytes()),"startup_backup_sha256":sha((APPLY / "startup.before").read_bytes()),
              "bound_file_hashes":{p:sha(Path(p).read_bytes()) for p in m.FILES},
              "old_exits":exits,"old_identities":old,"protected_processes":protected,"runner_name_snapshot":runner_names,
              "runner_counts_are_not_writer_or_role_proof":True,"access_gaps":gaps,
              "limits":["No reboot test","No hang test","No24h qualification","Existing PID-only CJS lock unchanged","No market-data or Paper-freshness proof"]}
    (AUDIT / "audit.json").write_text(json.dumps(result,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    print(json.dumps({"phase":result["phase"],"counts":result["counts"],"live_enabled":False}),flush=True)
finally:
    backend.close()
