import ctypes, getpass, hashlib, json, os
from pathlib import Path
from datetime import datetime, timezone
session=ctypes.c_ulong()
if not ctypes.windll.kernel32.ProcessIdToSessionId(os.getpid(),ctypes.byref(session)):
    raise ctypes.WinError()
result={"schema":"nexus.rdc-independent-process-probe.v1","host":os.environ.get("COMPUTERNAME"),"username":getpass.getuser(),"pid":os.getpid(),"ppid":os.getppid(),"session_id":session.value,"source_sha256":hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),"observed_utc":datetime.now(timezone.utc).isoformat(),"remote_started":False,"process_stopped":False,"completed":True}
Path(__file__).with_name("INDEPENDENT_PROCESS_PROBE.json").write_bytes((json.dumps(result,sort_keys=True,indent=2)+"\n").encode())
