"""Harmless private-job drill; never stops a real SDK, runner or task."""
import argparse, ctypes as C, hashlib, json, os, platform, struct, subprocess, sys, time
from ctypes import wintypes as W
from datetime import datetime, timezone
from pathlib import Path

QA = Path(r"E:\NEXUS-QA\rdc-l1-detached-proof-20261014T0455Z")
RUN = QA / "RUN"
DEPS = Path(r"E:\NEXUS-QA\rdc-l1-native-identity-20261014T0419Z\deps")
DLL_HASH = "0035450801bd7d938e9e146c5ec28e619cb5a5f4a18cdc53ac7e9734c7f94f78"

class BasicLimits(C.Structure):
    _fields_ = [("process_time", C.c_int64), ("job_time", C.c_int64),
                ("flags", C.c_uint32), ("min_working", C.c_size_t),
                ("max_working", C.c_size_t), ("active", C.c_uint32),
                ("affinity", C.c_size_t), ("priority", C.c_uint32),
                ("scheduling", C.c_uint32)]

class IoCounters(C.Structure):
    _fields_ = [(name, C.c_uint64) for name in
                ("read_ops", "write_ops", "other_ops", "read_bytes", "write_bytes", "other_bytes")]

class ExtendedLimits(C.Structure):
    _fields_ = [("basic", BasicLimits), ("io", IoCounters),
                ("process_memory", C.c_size_t), ("job_memory", C.c_size_t),
                ("peak_process", C.c_size_t), ("peak_job", C.c_size_t)]

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def write_receipt(name, value):
    pending = RUN / (name + ".tmp")
    with pending.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(value, sort_keys=True, indent=2) + "\n")
        stream.flush(); os.fsync(stream.fileno())
    os.replace(pending, RUN / name)

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--worker", action="store_true")
    parser.add_argument("--parent-pid", type=int)
    args = parser.parse_args()
    if len(args.source_sha) != 40 or any(c not in "0123456789abcdef" for c in args.source_sha):
        raise ValueError("Immutable source required")
    if platform.system() != "Windows" or os.environ.get("COMPUTERNAME") != "DESKTOP-1R1081M":
        raise ValueError("Wrong physical host")
    if struct.calcsize("P") != 8 or C.sizeof(ExtendedLimits) != 144:
        raise ValueError("Unsupported native job layout")
    sys.path.insert(0, str(DEPS))
    import psutil
    module = Path(psutil.__file__).resolve()
    if psutil.__version__ != "7.2.2" or not module.is_relative_to(DEPS.resolve()):
        raise ValueError("Wrong isolated dependency")
    if digest(module.parent / "_psutil_windows.pyd") != DLL_HASH:
        raise ValueError("Native diagnostic library changed")
    kernel = C.WinDLL("kernel32", use_last_error=True)
    signatures = {
        "GetCurrentProcess": ([], W.HANDLE),
        "CreateJobObjectW": ([C.c_void_p, W.LPCWSTR], W.HANDLE),
        "SetInformationJobObject": ([W.HANDLE, C.c_int, C.c_void_p, W.DWORD], W.BOOL),
        "AssignProcessToJobObject": ([W.HANDLE, W.HANDLE], W.BOOL),
        "IsProcessInJob": ([W.HANDLE, W.HANDLE, C.POINTER(W.BOOL)], W.BOOL),
        "ProcessIdToSessionId": ([W.DWORD, C.POINTER(W.DWORD)], W.BOOL),
        "OpenProcess": ([W.DWORD, W.BOOL, W.DWORD], W.HANDLE),
        "WaitForSingleObject": ([W.HANDLE, W.DWORD], W.DWORD),
        "GetExitCodeProcess": ([W.HANDLE, C.POINTER(W.DWORD)], W.BOOL),
        "CloseHandle": ([W.HANDLE], W.BOOL),
    }
    for name, (parameters, result) in signatures.items():
        function = getattr(kernel, name)
        function.argtypes, function.restype = parameters, result
    def required(value):
        if not value:
            raise C.WinError(C.get_last_error())
        return value
    def in_job():
        value = W.BOOL()
        required(kernel.IsProcessInJob(kernel.GetCurrentProcess(), None, C.byref(value)))
        return bool(value.value)
    def session(pid):
        value = W.DWORD()
        required(kernel.ProcessIdToSessionId(pid, C.byref(value)))
        return value.value
    def own_meta():
        return {"pid": os.getpid(), "owner": psutil.Process().username(),
                "session_id": session(os.getpid()), "in_job": in_job(),
                "source_sha": args.source_sha, "source_sha256": digest(Path(__file__)),
                "observed_utc": datetime.now(timezone.utc).isoformat()}

    if args.worker:
        if not args.parent_pid or args.parent_pid <= 0:
            raise ValueError("Exact diagnostic parent required")
        parent = json.loads((RUN / "parent.json").read_text(encoding="utf-8"))
        if parent["pid"] != args.parent_pid or parent["source_sha"] != args.source_sha:
            raise ValueError("Parent receipt mismatch")
        handle = required(kernel.OpenProcess(0x00101000, False, args.parent_pid))
        try:
            started = own_meta()
            started.update(parent_pid=args.parent_pid, parent_was_in_private_job=parent["in_job"])
            if started["in_job"] or not parent["in_job"]:
                raise ValueError("Detached child job proof failed")
            if started["owner"] != parent["owner"] or started["session_id"] != parent["session_id"]:
                raise ValueError("Owner/session changed")
            write_receipt("worker-started.json", started)
            wait = kernel.WaitForSingleObject(handle, 40000)
            exit_code = W.DWORD()
            exited = wait == 0
            if exited:
                required(kernel.GetExitCodeProcess(handle, C.byref(exit_code)))
            status = "PASS" if exited and exit_code.value == 0 and not in_job() else "FAIL"
            terminal = own_meta()
            terminal.update(status=status, positive_parent_exit=exited,
                            parent_exit_code=exit_code.value if exited else None,
                            wait_result=wait, survived_private_job_parent_exit=exited,
                            real_rdc_stopped=False, task_retargeted=False, live_enabled=False)
            write_receipt("terminal.json", terminal)
            return 0 if status == "PASS" else 2
        finally:
            kernel.CloseHandle(handle)

    RUN.mkdir(parents=True, exist_ok=False)
    if in_job():
        raise ValueError("Diagnostic caller already in a job; no existing job changed")
    job = required(kernel.CreateJobObjectW(None, None))
    limits = ExtendedLimits()
    limits.basic.flags = 0x00002000 | 0x00000800
    required(kernel.SetInformationJobObject(job, 9, C.byref(limits), C.sizeof(limits)))
    required(kernel.AssignProcessToJobObject(job, kernel.GetCurrentProcess()))
    try:
        parent = own_meta()
        if not parent["in_job"]:
            raise ValueError("Self-only private job assignment failed")
        parent.update(job_flags=limits.basic.flags, job_layout_bytes=C.sizeof(limits))
        write_receipt("parent.json", parent)
        child = subprocess.Popen(
            [sys.executable, str(Path(__file__).resolve()), "--source-sha", args.source_sha,
             "--worker", "--parent-pid", str(os.getpid())],
            cwd=QA, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            close_fds=True,
            creationflags=subprocess.CREATE_BREAKAWAY_FROM_JOB | subprocess.DETACHED_PROCESS)
        deadline = time.monotonic() + 30
        while not (RUN / "worker-started.json").exists():
            if child.poll() is not None:
                raise ValueError("Diagnostic worker exited before handshake")
            if time.monotonic() >= deadline:
                raise TimeoutError("Diagnostic handshake timeout")
            time.sleep(0.1)
        started = json.loads((RUN / "worker-started.json").read_text(encoding="utf-8"))
        if started["pid"] != child.pid or started["source_sha256"] != parent["source_sha256"]:
            raise ValueError("Worker source/identity mismatch")
        print(json.dumps({"status": "DIAGNOSTIC_PARENT_EXITING", "parent": parent,
                          "worker_pid": child.pid, "worker_started": started}, sort_keys=True), flush=True)
        os._exit(0)
    except BaseException as error:
        write_receipt("parent-failure.json", {"error_type": type(error).__name__,
                                             "message": str(error), "source_sha": args.source_sha})
        print("DIAGNOSTIC_PARENT_FAILED=" + type(error).__name__, flush=True)
        os._exit(30)

if __name__ == "__main__":
    raise SystemExit(main())
