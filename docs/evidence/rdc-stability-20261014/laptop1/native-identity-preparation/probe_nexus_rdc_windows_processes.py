"""One-shot RDC identities; no WMI, task change or process termination."""
from __future__ import annotations
import argparse, ctypes, hashlib, json, os, platform, struct, sys
from ctypes import wintypes as w
from datetime import datetime, timezone
from pathlib import Path

QA = Path(r"E:\NEXUS-QA\rdc-l1-native-identity-20261014T0419Z")
TARGET = Path(r"C:\Users\afaq\AppData\Local\NEXUS\desktop-commander-remote\remote-supervisor.cjs")
EXPECTED_CJS = "d762b259a74aa0b31188dcc02e259bbf9f2c7cd61952bc858297554c2412e35d"
WHEEL_HASH = "eb7e81434c8d223ec4a219b5fc1c47d0417b12be7ea866e24fb5ad6e84b3d988"

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-sha", required=True)
    args = parser.parse_args()
    if len(args.source_sha) != 40 or any(c not in "0123456789abcdef" for c in args.source_sha):
        raise ValueError("Exact immutable source required")
    if platform.system() != "Windows" or os.environ.get("COMPUTERNAME") != "DESKTOP-1R1081M":
        raise ValueError("Wrong physical host")
    if struct.calcsize("P") != 8 or sys.version_info[:2] != (3, 12):
        raise ValueError("Observed amd64 Python 3.12 required")
    if digest(TARGET) != EXPECTED_CJS:
        raise ValueError("Installed supervisor changed")
    deps = QA / "deps"
    sys.path.insert(0, str(deps))
    import psutil
    module_file = Path(psutil.__file__).resolve()
    if psutil.__version__ != "7.2.2" or not module_file.is_relative_to(deps.resolve()):
        raise ValueError("Unexpected diagnostic dependency")
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]
    kernel.OpenProcess.restype = w.HANDLE
    kernel.CloseHandle.argtypes = [w.HANDLE]
    kernel.CloseHandle.restype = w.BOOL
    kernel.GetProcessTimes.argtypes = [w.HANDLE] + [ctypes.POINTER(w.FILETIME)] * 4
    kernel.GetProcessTimes.restype = w.BOOL
    kernel.IsProcessInJob.argtypes = [w.HANDLE, w.HANDLE, ctypes.POINTER(w.BOOL)]
    kernel.IsProcessInJob.restype = w.BOOL
    kernel.ProcessIdToSessionId.argtypes = [w.DWORD, ctypes.POINTER(w.DWORD)]
    kernel.ProcessIdToSessionId.restype = w.BOOL

    def inspect(process):
        pid = process.pid
        handle = kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            created, ended, ktime, utime = (w.FILETIME() for _ in range(4))
            if not kernel.GetProcessTimes(handle, ctypes.byref(created), ctypes.byref(ended),
                                          ctypes.byref(ktime), ctypes.byref(utime)):
                raise ctypes.WinError(ctypes.get_last_error())
            in_job, session = w.BOOL(), w.DWORD()
            if not kernel.IsProcessInJob(handle, None, ctypes.byref(in_job)):
                raise ctypes.WinError(ctypes.get_last_error())
            if not kernel.ProcessIdToSessionId(pid, ctypes.byref(session)):
                raise ctypes.WinError(ctypes.get_last_error())
            exe, name = process.exe(), process.name()
            protected_adobe = "adobe" in exe.casefold()
            argv = [] if protected_adobe else process.cmdline()
            sdk = next((value for value in argv if value.casefold().replace("/", "\\").endswith(
                r"\desktop-commander\dist\index.js")), None)
            current_cjs = any(value.casefold() == str(TARGET).casefold() for value in argv)
            npm = any(value.casefold().endswith("npm-cli.js") for value in argv)
            package_arg = any("@wonderwhy-er/desktop-commander" in value.casefold() for value in argv)
            remote = "remote" in argv
            if protected_adobe:
                role = "unrelated_adobe_protected"
            elif current_cjs:
                role = "current_cjs_supervisor_candidate"
            elif npm and package_arg:
                role = "rdc_npm_launcher_candidate"
            elif sdk:
                role = "rdc_remote_candidate" if remote else "rdc_mcp_candidate"
            elif name.casefold().startswith("runner."):
                role = "existing_runner_lane"
            else:
                role = "unclassified"
            if not process.is_running():
                raise psutil.NoSuchProcess(pid)
            ticks = (created.dwHighDateTime << 32) | created.dwLowDateTime
            return {"pid": pid, "ppid": process.ppid(), "name": name, "exe": exe,
                    "owner": process.username(), "session_id": session.value,
                    "creation_filetime": str(ticks), "in_job": bool(in_job.value),
                    "argv_json_sha256": None if protected_adobe else hashlib.sha256(
                        json.dumps(argv, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest(),
                    "sdk_entry": sdk, "remote_argument_present": remote,
                    "current_cjs_argument_present": current_cjs, "role": role,
                    "parents": [{"pid": parent.pid, "name": parent.name()}
                                for parent in process.parents()[:12]]}
        finally:
            kernel.CloseHandle(handle)

    records = []
    selected_names = {"node.exe", "runner.listener.exe", "runner.worker.exe"}
    for process in psutil.process_iter(["pid", "name"]):
        if (process.info["name"] or "").casefold() not in selected_names:
            continue
        try:
            records.append(inspect(process))
        except (psutil.Error, OSError) as error:
            records.append({"pid": process.pid, "error_type": type(error).__name__})
    evidence = {"schema": "nexus.rdc-l1-native-identities.v1",
                "observed_utc": datetime.now(timezone.utc).isoformat(),
                "host": os.environ["COMPUTERNAME"], "source_sha": args.source_sha,
                "probe_sha256": digest(Path(__file__)), "wheel_sha256": WHEEL_HASH,
                "psutil_version": psutil.__version__, "module_path": str(module_file),
                "native_module_sha256": {p.name: digest(p) for p in module_file.parent.glob("*.pyd")},
                "supervisor_sha256": digest(TARGET), "observer": inspect(psutil.Process(os.getpid())),
                "processes": sorted(records, key=lambda record: record["pid"]),
                "raw_command_lines_exported": False, "credential_files_read": False,
                "real_rdc_restarted": False, "task_retargeted": False, "live_enabled": False}
    (QA / "identities.json").write_text(json.dumps(evidence, sort_keys=True, indent=2)+"\n", encoding="utf-8")
    print(json.dumps(evidence, sort_keys=True))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
