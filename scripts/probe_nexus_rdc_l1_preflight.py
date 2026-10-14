"""Read-only identities for later Laptop1 same-task adoption; never terminate or launch RDC."""
from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import ntpath
import os
import platform
import re
import struct
import sys
from ctypes import wintypes as w
from datetime import datetime, timezone
from pathlib import Path

DEPS = Path(r"E:\NEXUS-QA\rdc-l1-native-identity-20261014T0419Z\deps")
NATIVE_SHA = "0035450801bd7d938e9e146c5ec28e619cb5a5f4a18cdc53ac7e9734c7f94f78"
CJS = r"C:\Users\afaq\AppData\Local\NEXUS\desktop-commander-remote\remote-supervisor.cjs"
ENTRY = r"C:\Users\afaq\AppData\Local\npm-cache\_npx\4b4c857f6efdfb61\node_modules\@wonderwhy-er\desktop-commander\dist\index.js"
OWNER = r"DESKTOP-1R1081M\afaq"
CLI_ROOTS = (r"C:\Program Files\nodejs\node_modules\npm", r"C:\Users\afaq\AppData\Roaming\npm\node_modules\npm")
PACKAGE_RE = re.compile(r"@wonderwhy-er/desktop-commander(?:@(?:latest|\d+\.\d+\.\d+))?\Z")
SDK_RE = re.compile(r"c:\\users\\afaq\\appdata\\local\\npm-cache\\_npx\\[0-9a-f]+\\node_modules\\@wonderwhy-er\\desktop-commander\\dist\\index\.js\Z")
OLD = {
    2032: ("134364067509084762", "21fedff1304ab0a25bf83a85c1844ca8364b8f73e81cd8c36d6708459f5272b1"),
    12764: ("134364067859346874", "dccf2427765dd06d9111a3f94218958b25638bc87f6f66e42ac9e214c0af2a76"),
    5520: ("134364068135156379", "2a926c6300a3e815ac64b7a3a4b511fb26f260f93f91b56f2f1995834c619783"),
}


def norm(value):
    return ntpath.normpath(value.replace("/", "\\")).casefold()


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def classify(argv):
    allowed = {norm(ntpath.join(root, "bin", name)): ntpath.join(root, "bin", name)
               for root in CLI_ROOTS for name in ("npm-cli.js", "npx-cli.js")}
    cli = [allowed[norm(v)] for v in argv if norm(v) in allowed]
    sdk = [norm(v) for v in argv if SDK_RE.fullmatch(norm(v))]
    specs = [v for v in argv if PACKAGE_RE.fullmatch(v)]
    remote_count = argv.count("remote")
    remote = remote_count > 0
    cjs = any(norm(v) == norm(CJS) for v in argv)
    role = "unclassified"
    if cjs:
        role = "current_cjs_supervisor_candidate"
    elif len(cli) == 1 and len(specs) == 1 and remote_count == 1 and not sdk:
        role = "approved_npm_rdc_remote_launcher"
    elif len(sdk) == 1 and not cli and not specs and remote_count in (0, 1):
        role = "sdk_remote_candidate" if remote else "sdk_mcp_candidate"
    return {"role": role, "whitelisted_cli_entry": cli[0] if len(cli) == 1 else None,
            "whitelisted_package_spec": specs[0] if len(specs) == 1 else None,
            "sdk_entry": sdk[0] if len(sdk) == 1 else None,
            "remote_argument_present": remote, "current_cjs_argument_present": cjs}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    if not re.fullmatch(r"[0-9a-f]{40}", args.source_sha):
        raise ValueError("Immutable source SHA required")
    if platform.system() != "Windows" or os.environ.get("COMPUTERNAME") != "DESKTOP-1R1081M":
        raise ValueError("Wrong physical host")
    if struct.calcsize("P") != 8 or sys.version_info[:2] != (3, 12):
        raise ValueError("Observed amd64 Python3.12 required")
    if digest(DEPS / "psutil" / "_psutil_windows.pyd") != NATIVE_SHA:
        raise ValueError("Native dependency hash changed")
    sys.path.insert(0, str(DEPS))
    import psutil
    if psutil.__version__ != "7.2.2" or not Path(psutil.__file__).resolve().is_relative_to(DEPS.resolve()):
        raise ValueError("Unexpected dependency")
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes, kernel.OpenProcess.restype = [w.DWORD, w.BOOL, w.DWORD], w.HANDLE
    kernel.CloseHandle.argtypes, kernel.CloseHandle.restype = [w.HANDLE], w.BOOL
    kernel.GetProcessTimes.argtypes = [w.HANDLE] + [ctypes.POINTER(w.FILETIME)] * 4
    kernel.GetProcessTimes.restype = w.BOOL
    kernel.IsProcessInJob.argtypes, kernel.IsProcessInJob.restype = [w.HANDLE, w.HANDLE, ctypes.POINTER(w.BOOL)], w.BOOL
    kernel.ProcessIdToSessionId.argtypes, kernel.ProcessIdToSessionId.restype = [w.DWORD, ctypes.POINTER(w.DWORD)], w.BOOL
    kernel.WaitForSingleObject.argtypes, kernel.WaitForSingleObject.restype = [w.HANDLE, w.DWORD], w.DWORD

    def inspect(process):
        handle = kernel.OpenProcess(0x1000 | 0x100000, False, process.pid)
        if not handle:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            created, ended, kt, ut = (w.FILETIME() for _ in range(4))
            if not kernel.GetProcessTimes(handle, ctypes.byref(created), ctypes.byref(ended), ctypes.byref(kt), ctypes.byref(ut)):
                raise ctypes.WinError(ctypes.get_last_error())
            job, session = w.BOOL(), w.DWORD()
            if not kernel.IsProcessInJob(handle, None, ctypes.byref(job)) or not kernel.ProcessIdToSessionId(process.pid, ctypes.byref(session)):
                raise ctypes.WinError(ctypes.get_last_error())
            exe, name = process.exe(), process.name()
            protected = "adobe" in exe.casefold()
            argv = [] if protected else process.cmdline()
            result = classify(argv)
            if protected:
                result["role"] = "unrelated_adobe_protected"
            if kernel.WaitForSingleObject(handle, 0) != 258:
                raise ValueError("Process ended during read")
            result.update(pid=process.pid, ppid=process.ppid(), name=name, exe=exe,
                          owner=process.username(), session_id=session.value, in_job=bool(job.value),
                          creation_filetime=str((created.dwHighDateTime << 32) | created.dwLowDateTime),
                          argv_json_sha256=None if protected else hashlib.sha256(json.dumps(argv, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest(),
                          parents=[{"pid": p.pid, "name": p.name()} for p in process.parents()[:12]])
            return result
        finally:
            kernel.CloseHandle(handle)

    records = []
    fixed = {2032, 4000, 12764, 5520, 9040, 11520}
    for process in psutil.process_iter(["pid", "name"]):
        if process.pid not in fixed and (process.info["name"] or "").casefold() not in {"node.exe", "runner.listener.exe", "runner.worker.exe"}:
            continue
        try:
            records.append(inspect(process))
        except (psutil.Error, OSError, ValueError) as error:
            records.append({"pid": process.pid, "observed_name": process.info.get("name"), "error_type": type(error).__name__})
    by_pid = {record["pid"]: record for record in records}
    public_files = []
    for record in records:
        cli = record.get("whitelisted_cli_entry")
        if cli:
            path = Path(cli)
            package = path.parent.parent / "package.json"
            meta = json.loads(package.read_text(encoding="utf-8"))
            public_files.append({"path": str(path), "sha256": digest(path), "package_path": str(package),
                                 "package_sha256": digest(package), "name": meta.get("name"), "version": meta.get("version")})
    sdk_package = Path(ENTRY).parent.parent / "package.json"
    meta = json.loads(sdk_package.read_text(encoding="utf-8"))
    public_files.append({"path": ENTRY, "sha256": digest(Path(ENTRY)), "package_path": str(sdk_package),
                         "package_sha256": digest(sdk_package), "name": meta.get("name"), "version": meta.get("version")})
    old_match = all(by_pid.get(pid, {}).get("creation_filetime") == ticks and by_pid.get(pid, {}).get("argv_json_sha256") == sha for pid, (ticks, sha) in OLD.items())
    expected_chain = {2032: 9040, 4000: 2032, 12764: 4000, 5520: 12764}
    chain_match = all(by_pid.get(pid, {}).get("ppid") == ppid and by_pid.get(pid, {}).get("owner") == OWNER and by_pid.get(pid, {}).get("session_id") == 1 for pid, ppid in expected_chain.items())
    root_classified = by_pid.get(2032, {}).get("role") == "approved_npm_rdc_remote_launcher"
    sdk_match = meta.get("name") == "@wonderwhy-er/desktop-commander" and meta.get("version") == "0.3.0"
    npm_match = any(item.get("name") == "npm" and isinstance(item.get("version"), str) and re.fullmatch(r"\d+\.\d+\.\d+", item["version"]) for item in public_files)
    observer = inspect(psutil.Process(os.getpid()))
    observer_match = observer["owner"] == OWNER and observer["session_id"] == 1
    status = "PASS" if old_match and chain_match and root_classified and sdk_match and npm_match and observer_match else "HOLD"
    evidence = {"schema": "nexus.rdc-l1-task-preflight.v1", "status": status,
                "source_sha": args.source_sha, "probe_sha256": digest(Path(__file__)),
                "observed_utc": datetime.now(timezone.utc).isoformat(), "host": os.environ["COMPUTERNAME"],
                "observer": observer, "processes": sorted(records, key=lambda r: r["pid"]),
                "old_node_fingerprints_match": old_match, "expected_chain_match": chain_match,
                "root_launcher_classified": root_classified, "sdk_package_matches": sdk_match,
                "npm_package_matches": bool(npm_match), "observer_owner_session_matches": observer_match,
                "public_package_files": public_files,
                "observed_sdk_remote_count": sum(r.get("role") == "sdk_remote_candidate" for r in records),
                "permission_or_process_gaps": [r for r in records if "error_type" in r],
                "native_module_sha256": NATIVE_SHA, "raw_command_lines_exported": False,
                "credential_files_read": False, "real_rdc_restarted": False, "task_retargeted": False,
                "live_enabled": False, "cutover_authorized_by_snapshot": False}
    with (args.output_dir / "process-preflight.json").open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(evidence, sort_keys=True, indent=2) + "\n")
    print(json.dumps(evidence, sort_keys=True), flush=True)
    return 0 if status == "PASS" else 10


if __name__ == "__main__":
    raise SystemExit(main())
