"""Read-only L1 file audit and optional native process metadata."""
import hashlib, importlib.util, json
from datetime import datetime, timezone
from pathlib import Path

qa = Path(r"E:\NEXUS-QA\rdc-l1-exit-source-20261014T0344Z")
target = Path(r"C:\Users\afaq\AppData\Local\NEXUS\desktop-commander-remote\remote-supervisor.cjs")
backup = Path(r"E:\NEXUS-QA\rdc-l1-exit-20261014T034809153080Z\remote-supervisor.cjs.before")
digest = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
assert digest(target) == "d762b259a74aa0b31188dcc02e259bbf9f2c7cd61952bc858297554c2412e35d"
assert digest(backup) == "6518fd61948239a6434a5569a5aaad87fc163cce7596377283e02d0889d05083"
before = json.loads((qa / "preinstall.json").read_text(encoding="utf-8-sig"))
after = json.loads((qa / "postinstall.json").read_text(encoding="utf-8-sig"))
for name in ("task_xml_sha256", "startup_sha256", "legacy_flag_sha256", "node_processes"):
    assert before[name] == after[name], name + " changed"
present = importlib.util.find_spec("psutil") is not None
info = {"schema": "nexus.rdc-l1-readonly-post-audit.v1",
        "observed_utc": datetime.now(timezone.utc).isoformat(),
        "source_file_sha256": digest(Path(__file__)),
        "supervisor_sha256": digest(target), "backup_sha256": digest(backup),
        "snapshot_unchanged_fields": ["task_xml_sha256", "startup_sha256", "legacy_flag_sha256", "node_processes"],
        "snapshot_observed_utc": after["observed_utc"],
        "psutil_available": present, "processes": [], "active_processes_modified": False}
if present:
    import psutil
    info["psutil_version"] = psutil.__version__
    for pid in (2032, 5520, 12764, 11624):
        try:
            process = psutil.Process(pid)
            argv = process.cmdline()
            command_text = " ".join(argv).lower()
            exe = process.exe()
            if "adobe" in exe.lower():
                role = "unrelated_adobe"
            elif "remote-supervisor.cjs" in command_text:
                role = "current_cjs_supervisor"
            elif "npm-cli.js" in command_text and "desktop-commander" in command_text:
                role = "rdc_npm_launcher"
            elif "desktop-commander" in command_text and "remote" in argv:
                role = "rdc_remote_candidate"
            elif "desktop-commander" in command_text:
                role = "rdc_other_candidate"
            else:
                role = "unclassified_node"
            info["processes"].append({
                "pid": pid, "ppid": process.ppid(), "exe": exe,
                "created_epoch": process.create_time(), "owner": process.username(), "role": role,
                "argv_json_sha256": hashlib.sha256(
                    json.dumps(argv, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest(),
                "parents": [{"pid": parent.pid, "name": parent.name()} for parent in process.parents()]})
        except (psutil.NoSuchProcess, psutil.AccessDenied) as error:
            info["processes"].append({"pid": pid, "error": type(error).__name__})
(qa / "read-only-post-audit.json").write_text(json.dumps(info, sort_keys=True, indent=2) + "\n", encoding="utf-8")
print(json.dumps(info, sort_keys=True))
