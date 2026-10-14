"""Bounded adoption of the existing Laptop1 recovery task; default is read-only."""
from __future__ import annotations

import argparse
import base64
import copy
import ctypes as C
import hashlib
import json
import ntpath
import os
import platform
import re
import struct
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from ctypes import wintypes as W
from datetime import datetime, timezone
from pathlib import Path

HOST, OWNER, SID = "DESKTOP-1R1081M", r"DESKTOP-1R1081M\afaq", "S-1-5-21-29241603-1126111165-4177284829-1001"
TASK = "NEXUS-Remote-Commander-Recovery"
PS = r"C:\WINDOWS\System32\WindowsPowerShell\v1.0\powershell.exe"
NODE = r"C:\Program Files\nodejs\node.exe"
ROOT = r"C:\Users\afaq\AppData\Local\NEXUS\desktop-commander-remote"
CJS = ROOT + r"\remote-supervisor.cjs"
STARTUP = r"C:\Users\afaq\AppData\Roaming\Microsoft\Windows\Start Menu\Programs\Startup\NEXUS-Remote-Desktop-Commander.vbs"
ENTRY = r"C:\Users\afaq\AppData\Local\npm-cache\_npx\4b4c857f6efdfb61\node_modules\@wonderwhy-er\desktop-commander\dist\index.js"
DEPS = Path(r"E:\NEXUS-QA\rdc-l1-native-identity-20261014T0419Z\deps")
DLL_SHA = "0035450801bd7d938e9e146c5ec28e619cb5a5f4a18cdc53ac7e9734c7f94f78"
TASK_SHA = "284b39bd04f936372d30f42c798bae76382882b8b84cea22b7338a5ebb8e2c74"
STARTUP_SHA = "a8fdc21df5a315308768376cc22f704b316101016e2445abbdd6ccd4b3b29887"
FILES = {
    CJS: "d762b259a74aa0b31188dcc02e259bbf9f2c7cd61952bc858297554c2412e35d",
    r"C:\Users\afaq\AppData\Local\NEXUS\RemoteCommander\LEGACY_DISABLED.flag": "862595a01549b7b44a920a99670fd99d996584bbae3e44d868efc530c5195944",
    r"C:\Users\afaq\AppData\Local\NEXUS\RemoteCommander\nexus-remote-commander-watchdog.ps1": "c5b185ed07e1894b8fb6ce1c373c5cde5dbbadabb12d87581e333fcdee9b25f7",
    ENTRY: "7e58b9d5d64732ff8cd77cd477de30751feb6b59bc2353dfaa78825f015b2f2b",
    ntpath.join(ntpath.dirname(ntpath.dirname(ENTRY)), "package.json"): "8ba64a033e75730c16f90b09f2749fa5e61c28240104ead151cabe93239ba14a",
    r"C:\Program Files\nodejs\node_modules\npm\bin\npx-cli.js": "a9ca027c18c5bd7da278230edc7a174ff1d8b6b558e0e0a4a2c9c2fae346d66b",
    r"C:\Program Files\nodejs\node_modules\npm\package.json": "40c49aec1ef9a0cd1edb50b900d678705319faf9e3117f5336960ba7b3619e47",
}
TARGETS = {
    2032: (9040, "node.exe", "134364067509084762", "21fedff1304ab0a25bf83a85c1844ca8364b8f73e81cd8c36d6708459f5272b1"),
    4000: (2032, "cmd.exe", "134364067854916476", "ea5688b87b68e44e6906428c9a56f94f585091ea63d627473fbec4d97a7bc225"),
    12764: (4000, "node.exe", "134364067859346874", "dccf2427765dd06d9111a3f94218958b25638bc87f6f66e42ac9e214c0af2a76"),
    5520: (12764, "node.exe", "134364068135156379", "2a926c6300a3e815ac64b7a3a4b511fb26f260f93f91b56f2f1995834c619783"),
}
NODE_COMMAND = f"& '{NODE}' '{CJS}'; exit $LASTEXITCODE"
TASK_ARGS = '-NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy RemoteSigned -Command "' + NODE_COMMAND + '"'
ORIGINAL_TASK_ARGS = '-NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File "C:\\Users\\afaq\\AppData\\Local\\NEXUS\\RemoteCommander\\nexus-remote-commander-watchdog.ps1"'
STARTUP_BYTES = ('Set sh = CreateObject("WScript.Shell")\r\nWScript.Sleep 20000\r\n'
                 'cmd = """C:\\Windows\\System32\\schtasks.exe"" /Run /TN ""\\NEXUS-Remote-Commander-Recovery"""\r\n'
                 'sh.Run cmd, 0, False\r\n').replace('\\\\', '\\').encode("utf-8")
NS = "http://schemas.microsoft.com/windows/2004/02/mit/task"
ET.register_namespace("", NS)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def norm(path):
    return ntpath.normpath(path.replace("/", "\\")).casefold()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def xml_node(root, path):
    return root.find("/".join("{" + NS + "}" + part for part in path.split("/")))


def xml_contract(xml, omit_actions=False):
    root = ET.fromstring(xml)
    for path in (("Actions", "Settings/Enabled") if omit_actions else ("Settings/Enabled",)):
        parent_path, _, leaf = path.rpartition("/")
        parent = xml_node(root, parent_path) if parent_path else root
        node = xml_node(root, path)
        if node is not None:
            parent.remove(node)
    def canonical(node):
        return [node.tag, sorted(node.attrib.items()), (node.text or "").strip(), [canonical(c) for c in node]]
    return canonical(root)


def preserved_contract(xml):
    return xml_contract(xml, omit_actions=True)


def require_original_task(original):
    require(original["xml_sha256"] == TASK_SHA and original["enabled"], "Original task definition or enabled state changed")
    require((original["state"], original["instances"]) in ((3, 0), (4, 1)), "Original task state or instance count differs")
    require(original["owner_sid"] == SID and original["allow_demand"], "Task owner or demand start differs")


def prepare_task(xml):
    root = ET.fromstring(xml)
    required = {"Principals/Principal/UserId": SID, "Principals/Principal/LogonType": "InteractiveToken",
                "Settings/MultipleInstancesPolicy": "IgnoreNew", "Settings/RestartOnFailure/Count": "99",
                "Settings/RestartOnFailure/Interval": "PT1M", "Triggers/LogonTrigger/Delay": "PT1M",
                "Triggers/LogonTrigger/Repetition/Interval": "PT5M", "RegistrationInfo/URI": "\\" + TASK}
    for path, value in required.items():
        node = xml_node(root, path)
        require(node is not None and node.text == value, "Original task contract changed: " + path)
    demand = xml_node(root, "Settings/AllowStartOnDemand")
    require(demand is None or demand.text == "true", "Task demand start disabled")
    actions = xml_node(root, "Actions")
    require(actions is not None and len(actions) == 1 and actions[0].tag == "{" + NS + "}Exec", "Unexpected task actions")
    original_exec = actions[0]
    require(norm(xml_node(root, "Actions/Exec/Command").text) == norm(PS), "Original task executable changed")
    require(xml_node(root, "Actions/Exec/Arguments").text == ORIGINAL_TASK_ARGS, "Original guarded task action changed")
    actions.remove(original_exec)
    action = ET.SubElement(actions, "{" + NS + "}Exec")
    for name, value in (("Command", PS), ("Arguments", TASK_ARGS), ("WorkingDirectory", ROOT)):
        ET.SubElement(action, "{" + NS + "}" + name).text = value
    settings = xml_node(root, "Settings")
    enabled = xml_node(root, "Settings/Enabled")
    if enabled is None:
        enabled = ET.SubElement(settings, "{" + NS + "}Enabled")
    enabled.text = "false"
    result = ET.tostring(root, encoding="unicode")
    require(preserved_contract(result) == preserved_contract(xml), "Non-action task contract changed")
    return result


def verify_task(actual, original, enabled):
    require(actual["enabled"] is enabled, "Task enabled state differs")
    require(actual["sddl"] == original["sddl"], "Task security descriptor changed")
    require(preserved_contract(actual["xml"]) == preserved_contract(original["xml"]), "Task settings/principal/triggers changed")
    root = ET.fromstring(actual["xml"])
    require(norm(xml_node(root, "Actions/Exec/Command").text) == norm(PS), "Wrong task executable")
    require(xml_node(root, "Actions/Exec/Arguments").text == TASK_ARGS, "Wrong current-CJS task command")
    require(norm(xml_node(root, "Actions/Exec/WorkingDirectory").text) == norm(ROOT), "Wrong task working directory")


def adopt(backend, apply=False):
    """Backend provides exact native handles; this function enforces transaction ordering."""
    state = {"phase": "VALIDATING", "live_enabled": False, "stop_intent": False, "task_run_requests": 0}
    staged = False
    try:
        original = backend.preflight(apply)
        prepared = prepare_task(original["xml"])
        backend.validate_task(prepared, original)
        state["phase"] = "READ_ONLY_PASS"
        backend.receipt(state)
        if not apply:
            return state
        backend.backup(original)
        staged = True
        backend.stage(prepared, original)
        backend.install_startup()
        backend.verify_staged(original)
        backend.revalidate_old()
        state["phase"] = "STOP_INTENT"
        state["stop_intent"] = True
        backend.receipt(state)
        backend.stop_and_prove_exits()
        backend.require_zero_clients()
        backend.refresh_guards(True)
        state["phase"] = "OLD_EXITED"
        backend.receipt(state)
        state["task_run_requests"] = 1
        state["phase"] = "TASK_RUN_INTENT"
        backend.receipt(state)
        backend.run_once(original)
        state["new_chain"] = backend.await_owned_client(original)
        state["phase"] = "ADOPTED_AWAITING_INDEPENDENT_AUDIT"
        backend.receipt(state)
        return state
    except Exception as error:
        state["phase"] = "FAILED_CLOSED"
        state["error_type"] = type(error).__name__
        state["error"] = str(error)
        if staged and not state["stop_intent"]:
            try:
                backend.rollback(original)
                state["configuration_rolled_back"] = True
            except Exception as rollback_error:
                state["rollback_error"] = str(rollback_error)
        backend.receipt(state)
        raise
    finally:
        backend.close()


QUIESCE_TASK = r'''
function Definition-Identity([string]$xml){
 $doc=New-Object Xml.XmlDocument
 $doc.PreserveWhitespace=$false
 $doc.LoadXml($xml)
 $ns=New-Object Xml.XmlNamespaceManager($doc.NameTable)
 $ns.AddNamespace('t','http://schemas.microsoft.com/windows/2004/02/mit/task')
 $enabled=$doc.SelectSingleNode('/t:Task/t:Settings/t:Enabled',$ns)
 if($null -ne $enabled){$null=$enabled.ParentNode.RemoveChild($enabled)}
 return (Hash-Text $doc.OuterXml)
}
function Quiesce-OriginalTask($t,[ScriptBlock]$refresh,[string]$originalSha,[string]$sddl){
 if($t.Name -ne 'NEXUS-Remote-Commander-Recovery' -or (Hash-Text ([string]$t.Xml)) -ne $originalSha -or -not $t.Enabled){throw 'Original task changed before disable'}
 $count=[int]$t.GetInstances(0).Count
 if(-not (($t.State -eq 3 -and $count -eq 0) -or ($t.State -eq 4 -and $count -eq 1))){throw 'Unknown original task state/count'}
 if([string]$t.GetSecurityDescriptor(7) -ne $sddl){throw 'Original task security changed'}
 $definition=Definition-Identity ([string]$t.Xml)
 $t.Enabled=$false
 $requested=$false
 $beforeStop=& $refresh
 if($beforeStop.Enabled -or (Definition-Identity ([string]$beforeStop.Xml)) -ne $definition -or [string]$beforeStop.GetSecurityDescriptor(7) -ne $sddl -or $beforeStop.GetInstances(0).Count -gt 1){throw 'Task changed before scoped stop'}
 if($beforeStop.GetInstances(0).Count -eq 1){$beforeStop.Stop(0);$requested=$true}
 $deadline=[DateTime]::UtcNow.AddSeconds(15)
 do {
  $current=& $refresh
  if($current.State -eq 3 -and $current.GetInstances(0).Count -eq 0){break}
  if([DateTime]::UtcNow -ge $deadline){throw 'Known legacy task stop timeout; no replacement registered'}
  Start-Sleep -Milliseconds 200
 } while($true)
 if($current.Enabled -or (Definition-Identity ([string]$current.Xml)) -ne $definition -or [string]$current.GetSecurityDescriptor(7) -ne $sddl){throw 'Task changed while waiting for idle'}
 return $requested
}
'''

TASK_RPC = r'''
$ErrorActionPreference='Stop'
$r=ConvertFrom-Json ([Text.Encoding]::UTF8.GetString($b))
if($env:COMPUTERNAME -ne 'DESKTOP-1R1081M'){throw 'Wrong task host'}
$identity=[Security.Principal.WindowsIdentity]::GetCurrent()
if($identity.User.Value -ne 'S-1-5-21-29241603-1126111165-4177284829-1001'){throw 'Wrong task owner'}
$service=New-Object -ComObject Schedule.Service
$service.Connect()
$folder=$service.GetFolder('\')
$name='NEXUS-Remote-Commander-Recovery'
$task=$folder.GetTask($name)
function Hash-Text([string]$s){[BitConverter]::ToString([Security.Cryptography.SHA256]::Create().ComputeHash([Text.Encoding]::UTF8.GetBytes($s))).Replace('-','').ToLowerInvariant()}
__QUIESCE_TASK__
function Read-Task {
 $t=$folder.GetTask($name)
 @{xml=[string]$t.Xml;xml_sha256=(Hash-Text ([string]$t.Xml));enabled=[bool]$t.Enabled;state=[int]$t.State;instances=[int]$t.GetInstances(0).Count;sddl=[string]$t.GetSecurityDescriptor(7);owner_sid=[string]$identity.User.Value;allow_demand=[bool]$t.Definition.Settings.AllowDemandStart}
}
switch([string]$r.operation){
 'read' { $result=Read-Task }
 'validate' {
  if((Hash-Text ([string]$task.Xml)) -ne $r.original_sha){throw 'Task changed before validation'}
  $def=$service.NewTask(0);$def.XmlText=[string]$r.xml
  $null=$folder.RegisterTaskDefinition($name,$def,1,'S-1-5-21-29241603-1126111165-4177284829-1001',$null,3,[string]$r.sddl)
  $result=@{validated=$true;registered=$false}
 }
 'stage' {
  $stopped=Quiesce-OriginalTask $task {$folder.GetTask($name)} ([string]$r.original_sha) ([string]$r.sddl)
  $def=$service.NewTask(0);$def.XmlText=[string]$r.xml
  $def.Settings.Enabled=$false
  $null=$folder.RegisterTaskDefinition($name,$def,52,'S-1-5-21-29241603-1126111165-4177284829-1001',$null,3,[string]$r.sddl)
  $result=Read-Task
  $result.legacy_stop_requested=$stopped
 }
 'rollback' {
  if((Hash-Text ([string]$task.Xml)) -ne $r.expected_sha -or [string]$task.GetSecurityDescriptor(7) -ne [string]$r.sddl){throw 'Rollback task changed'}
  if((Definition-Identity ([string]$task.Xml)) -eq (Definition-Identity ([string]$r.xml))){
   $task.Enabled=$true
  }else{
   if($task.GetInstances(0).Count -ne 0){throw 'Changed task still active; rollback registration refused'}
   $def=$service.NewTask(0);$def.XmlText=[string]$r.xml
   $null=$folder.RegisterTaskDefinition($name,$def,52,'S-1-5-21-29241603-1126111165-4177284829-1001',$null,3,[string]$r.sddl)
  }
  $result=Read-Task
 }
 'run' {
  if((Hash-Text ([string]$task.Xml)) -ne $r.expected_sha -or $task.Enabled -or $task.GetInstances(0).Count -ne 0){throw 'Staged task changed or active before run'}
  $task.Enabled=$true
  $null=$task.Run($null)
  $result=Read-Task
 }
 default {throw 'Unsupported bounded task operation'}
}
[IO.File]::WriteAllText([string]$r.response,($result|ConvertTo-Json -Depth 12),[Text.UTF8Encoding]::new($false))
exit 0
'''.replace('__QUIESCE_TASK__', QUIESCE_TASK)


class NativeBackend:
    def __init__(self, run, source_sha, code_sha):
        require(platform.system() == "Windows" and os.environ.get("COMPUTERNAME") == HOST, "Wrong physical host")
        require(struct.calcsize("P") == 8 and sys.version_info[:2] == (3, 12), "Python3.12 amd64 required")
        require(sha(Path(__file__).read_bytes()) == code_sha, "Controller source changed")
        require(sha((DEPS / "psutil" / "_psutil_windows.pyd").read_bytes()) == DLL_SHA, "Native dependency changed")
        sys.path.insert(0, str(DEPS))
        import psutil
        require(psutil.__version__ == "7.2.2" and Path(psutil.__file__).resolve().is_relative_to(DEPS.resolve()), "Wrong isolated dependency")
        self.psutil, self.run, self.source, self.code = psutil, run, source_sha, code_sha
        self.handles, self.rpc_number, self.staged_task = {}, 0, None
        self.k = C.WinDLL("kernel32", use_last_error=True)
        signatures = {
            "GetCurrentProcess": ([], W.HANDLE), "OpenProcess": ([W.DWORD, W.BOOL, W.DWORD], W.HANDLE),
            "CloseHandle": ([W.HANDLE], W.BOOL), "GetProcessTimes": ([W.HANDLE] + [C.POINTER(W.FILETIME)] * 4, W.BOOL),
            "IsProcessInJob": ([W.HANDLE, W.HANDLE, C.POINTER(W.BOOL)], W.BOOL),
            "ProcessIdToSessionId": ([W.DWORD, C.POINTER(W.DWORD)], W.BOOL),
            "WaitForSingleObject": ([W.HANDLE, W.DWORD], W.DWORD), "GetExitCodeProcess": ([W.HANDLE, C.POINTER(W.DWORD)], W.BOOL),
            "TerminateProcess": ([W.HANDLE, W.UINT], W.BOOL), "CreateMutexW": ([C.c_void_p, W.BOOL, W.LPCWSTR], W.HANDLE),
            "ReleaseMutex": ([W.HANDLE], W.BOOL),
        }
        for name, (params, result) in signatures.items():
            getattr(self.k, name).argtypes, getattr(self.k, name).restype = params, result
        self.mutex = self.ok(self.k.CreateMutexW(None, False, "Local\\NEXUS_RDC_L1_TASK_ADOPTION"))
        require(self.k.WaitForSingleObject(self.mutex, 0) in (0, 128), "Another controller is active")
        observer = self.inspect(os.getpid())
        require(observer["owner"].casefold() == OWNER.casefold() and observer["session_id"] == 1 and not observer["in_job"], "Worker owner/session/job proof failed")
        self.observer = observer

    def ok(self, value):
        if not value:
            raise C.WinError(C.get_last_error())
        return value

    def inspect(self, pid, handle=None):
        own = handle is None
        handle = handle or self.ok(self.k.OpenProcess(0x101000, False, pid))
        try:
            p = self.psutil.Process(pid)
            created, ended, kt, ut = (W.FILETIME() for _ in range(4))
            self.ok(self.k.GetProcessTimes(handle, C.byref(created), C.byref(ended), C.byref(kt), C.byref(ut)))
            job, session = W.BOOL(), W.DWORD()
            self.ok(self.k.IsProcessInJob(handle, None, C.byref(job)))
            self.ok(self.k.ProcessIdToSessionId(pid, C.byref(session)))
            argv = p.cmdline()
            result = {"pid": pid, "ppid": p.ppid(), "name": p.name(), "exe": p.exe(), "owner": p.username(),
                      "creation_filetime": str((created.dwHighDateTime << 32) | created.dwLowDateTime),
                      "argv_json_sha256": sha(json.dumps(argv, ensure_ascii=False, separators=(",", ":")).encode()),
                      "session_id": session.value, "in_job": bool(job.value), "argv": argv}
            require(self.k.WaitForSingleObject(handle, 0) == 258, "Process ended during read")
            return result
        finally:
            if own:
                self.k.CloseHandle(handle)

    def rpc(self, operation, **data):
        self.rpc_number += 1
        request = self.run / f"task-request-{self.rpc_number}.json"
        response = self.run / f"task-response-{self.rpc_number}.json"
        payload = json.dumps(dict(operation=operation, response=str(response), **data)).encode("utf-8")
        request.write_bytes(payload)
        guard = "$b=[IO.File]::ReadAllBytes('__REQUEST__');$h=[BitConverter]::ToString([Security.Cryptography.SHA256]::Create().ComputeHash($b)).Replace('-','').ToLowerInvariant();if($h -ne '" + sha(payload) + "'){throw 'Task request changed'}\n"
        script = ("$ErrorActionPreference='Stop'\n" + guard + TASK_RPC).replace("__REQUEST__", str(request).replace("'", "''"))
        code = base64.b64encode(script.encode("utf-16le")).decode("ascii")
        result = subprocess.run([PS, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "RemoteSigned", "-EncodedCommand", code],
                                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60, creationflags=subprocess.CREATE_NO_WINDOW)
        require(result.returncode == 0, "Task RPC failed: " + operation + "; " + result.stderr.decode("utf-8", errors="replace")[:1200])
        return json.loads(response.read_text(encoding="utf-8-sig"))

    def receipt(self, state):
        value = dict(state, source_sha=self.source, code_sha256=self.code, observer={k: v for k, v in self.observer.items() if k != "argv"},
                     updated_utc=datetime.now(timezone.utc).isoformat(), external_worker_os_exit_independently_captured=False)
        pending = self.run / "receipt.pending.json"
        pending.write_text(json.dumps(value, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        os.replace(pending, self.run / "receipt.json")

    def refresh_guards(self, staged=False):
        for path, expected in FILES.items():
            require(sha(Path(path).read_bytes()) == expected, "Bound file changed: " + path)
        require(sha(Path(STARTUP).read_bytes()) == (sha(STARTUP_BYTES) if staged else STARTUP_SHA), "Startup changed")

    def census(self):
        clients, supervisors, launchers = [], [], []
        for p in self.psutil.process_iter(["pid", "name", "exe"]):
            if (p.info["name"] or "").casefold() != "node.exe":
                continue
            if "adobe" in (p.info.get("exe") or "").casefold():
                continue
            row = self.inspect(p.pid)  # Any unknown Node access gap blocks this census.
            sdk = [v for v in row["argv"] if norm(v).endswith(r"\@wonderwhy-er\desktop-commander\dist\index.js")]
            if sdk and "remote" in row["argv"]:
                clients.append(row)
            cli = any(norm(v).endswith((r"\npx-cli.js", r"\npm-cli.js")) for v in row["argv"])
            package = any("@wonderwhy-er/desktop-commander" in v.casefold() for v in row["argv"])
            if cli and package and "remote" in row["argv"]:
                launchers.append(row)
            if any(norm(v) == norm(CJS) for v in row["argv"]):
                supervisors.append(row)
        return clients, supervisors, launchers

    def preflight(self, apply):
        self.refresh_guards()
        require(not Path(ROOT + r"\supervisor.json").exists(), "CJS supervisor lock already exists")
        state_path = Path(r"C:\Users\afaq\.desktop-commander-device\device.json")
        config = json.loads(state_path.read_text(encoding="utf-8"))
        require(bool(config.get("session", {}).get("refresh_token")), "Persisted session missing; no auth initiated")
        for pid in TARGETS:
            handle = self.ok(self.k.OpenProcess(0x101000 | (1 if apply else 0), False, pid))
            self.handles[pid] = handle
        self.revalidate_old()
        clients, supervisors, launchers = self.census()
        require([r["pid"] for r in clients] == [12764] and not supervisors and [r["pid"] for r in launchers] == [2032], "Existing SDK ownership changed")
        original = self.rpc("read")
        require_original_task(original)
        self.original = original
        return original

    def revalidate_old(self):
        for pid, (ppid, name, ticks, argv_sha) in TARGETS.items():
            row = self.inspect(pid, self.handles[pid])
            expected_exe = NODE if name == "node.exe" else r"C:\WINDOWS\system32\cmd.exe"
            require((row["ppid"], row["name"].casefold(), row["creation_filetime"], row["argv_json_sha256"]) == (ppid, name, ticks, argv_sha), "Old process identity changed")
            require(row["owner"].casefold() == OWNER.casefold() and row["session_id"] == 1 and norm(row["exe"]) == norm(expected_exe), "Old owner/session/executable changed")

    def validate_task(self, prepared, original):
        result = self.rpc("validate", xml=prepared, original_sha=original["xml_sha256"], sddl=original["sddl"])
        require(result.get("validated") is True and result.get("registered") is False, "Task validation result differs")

    def backup(self, original):
        with (self.run / "startup.before").open("xb") as stream:
            stream.write(Path(STARTUP).read_bytes())
        require(sha((self.run / "startup.before").read_bytes()) == STARTUP_SHA, "Startup backup differs")
        (self.run / "task.before.json").write_text(json.dumps(original, indent=2), encoding="utf-8")

    def stage(self, prepared, original):
        self.staged_task = self.rpc("stage", xml=prepared, original_sha=original["xml_sha256"], sddl=original["sddl"])
        verify_task(self.staged_task, original, False)
        self.revalidate_old()  # Scoped legacy-task stop must not affect the held SDK graph.

    def install_startup(self):
        require(sha(Path(STARTUP).read_bytes()) == STARTUP_SHA, "Startup changed before replacement")
        pending = Path(STARTUP + ".nexus-task-adoption.pending")
        with pending.open("xb") as stream:
            stream.write(STARTUP_BYTES)
            stream.flush(); os.fsync(stream.fileno())
        require(sha(Path(STARTUP).read_bytes()) == STARTUP_SHA, "Startup changed during staging")
        os.replace(pending, STARTUP)

    def verify_staged(self, original):
        actual = self.rpc("read")
        verify_task(actual, original, False)
        require(actual["instances"] == 0 and actual["state"] != 4, "Staged task became active")
        self.staged_task = actual
        self.refresh_guards(True)
        clients, supervisors, launchers = self.census()
        require([r["pid"] for r in clients] == [12764] and not supervisors and [r["pid"] for r in launchers] == [2032], "SDK changed before old stop")

    def stop_and_prove_exits(self):
        self.revalidate_old()
        require(set(self.handles) == set(TARGETS), "Held target set differs")
        exits = terminate_held_handles(self.k, [(pid, self.handles[pid]) for pid in (5520, 12764, 4000, 2032)])
        (self.run / "old-exits.json").write_text(json.dumps(exits, indent=2), encoding="utf-8")

    def require_zero_clients(self):
        clients, supervisors, launchers = self.census()
        require(not clients and not supervisors and not launchers, "A client/supervisor/launcher remains; no launch")

    def run_once(self, original):
        actual = self.rpc("read")
        verify_task(actual, original, False)
        require(actual["xml_sha256"] == self.staged_task["xml_sha256"], "Task changed before run")
        self.require_zero_clients()
        self.rpc("run", expected_sha=actual["xml_sha256"])

    def await_owned_client(self, original):
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            clients, supervisors, launchers = self.census()
            require(len(clients) <= 1 and len(supervisors) <= 1 and not launchers, "Duplicate client/supervisor/launcher after run")
            if len(clients) == len(supervisors) == 1:
                client, supervisor = clients[0], supervisors[0]
                require(client["ppid"] == supervisor["pid"] and norm(ENTRY) in [norm(a) for a in client["argv"]], "Client does not belong to current CJS")
                lock = json.loads(Path(ROOT + r"\supervisor.json").read_text(encoding="utf-8"))
                require(lock.get("pid") == supervisor["pid"], "Supervisor lock owner differs")
                parent = self.inspect(supervisor["ppid"])
                require(norm(parent["exe"]) == norm(PS) and NODE_COMMAND in parent["argv"], "CJS task action parent differs")
                for row in (client, supervisor, parent):
                    require(row["owner"].casefold() == OWNER.casefold() and row["session_id"] == 1, "New chain owner/session differs")
                actual = self.rpc("read")
                verify_task(actual, original, True)
                require(actual["state"] == 4 and actual["instances"] == 1, "Same task is not the single running owner")
                self.refresh_guards(True)
                return {"client_pid": client["pid"], "supervisor_pid": supervisor["pid"], "task_action_pid": parent["pid"], "task_instances": 1}
            time.sleep(0.5)
        raise TimeoutError("Same task started; client did not qualify within90s; no second run")

    def rollback(self, original):
        current = self.rpc("read")
        require(current["sddl"] == original["sddl"], "Task security changed; rollback refused")
        # Only known original or our staged current-CJS task may be restored.
        if current["xml_sha256"] != TASK_SHA:
            if self.staged_task is not None:
                require(current["xml_sha256"] == self.staged_task["xml_sha256"], "Unknown task change; rollback refused")
            else:
                root = ET.fromstring(current["xml"])
                args = xml_node(root, "Actions/Exec/Arguments").text
                require(args in (TASK_ARGS, xml_node(ET.fromstring(original["xml"]), "Actions/Exec/Arguments").text), "Unknown partially staged task")
                require(preserved_contract(current["xml"]) == preserved_contract(original["xml"]), "Partial stage changed protected contract")
        data = Path(STARTUP).read_bytes()
        require(sha(data) in (STARTUP_SHA, sha(STARTUP_BYTES)), "Unknown Startup change; rollback refused")
        Path(STARTUP).write_bytes((self.run / "startup.before").read_bytes())
        restored = self.rpc("rollback", expected_sha=current["xml_sha256"], xml=original["xml"], sddl=original["sddl"])
        require(restored["enabled"] and restored["sddl"] == original["sddl"] and preserved_contract(restored["xml"]) == preserved_contract(original["xml"]), "Rollback readback differs")
        require(ET.fromstring(restored["xml"]).find("{" + NS + "}Actions")[0].find("{" + NS + "}Arguments").text == xml_node(ET.fromstring(original["xml"]), "Actions/Exec/Arguments").text, "Rollback action differs")
        self.refresh_guards()

    def close(self):
        for handle in self.handles.values():
            self.k.CloseHandle(handle)
        self.k.ReleaseMutex(self.mutex)
        self.k.CloseHandle(self.mutex)


def terminate_held_handles(kernel, handles):
    """Only accepts already-open handles; caller must validate their immutable identities."""
    for pid, handle in handles:
        wait = kernel.WaitForSingleObject(handle, 0)
        require(wait in (0, 258), "Old handle wait failed")
        if wait == 258 and not kernel.TerminateProcess(handle, 70):
            # Root/job cleanup may have exited another held child concurrently.
            require(kernel.WaitForSingleObject(handle, 0) == 0, "Old termination failed")
    exits = []
    for pid, handle in handles:
        require(kernel.WaitForSingleObject(handle, 10000) == 0, "Old exit not proven")
        code = W.DWORD()
        require(kernel.GetExitCodeProcess(handle, C.byref(code)), "Old exit code unavailable")
        exits.append({"pid": pid, "positive_exit": True, "exit_code": code.value})
    return exits


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--code-sha", required=True)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--worker", action="store_true")
    args = parser.parse_args()
    require(re.fullmatch(r"[0-9a-f]{40}", args.source_sha) and re.fullmatch(r"[0-9a-f]{64}", args.code_sha), "Immutable source required")
    require(platform.system() == "Windows" and os.environ.get("COMPUTERNAME") == HOST, "Wrong physical host")
    require(sha(Path(__file__).read_bytes()) == args.code_sha, "Controller byte hash changed")
    require(norm(str(args.run_dir)).startswith(norm(r"E:\NEXUS-QA") + "\\"), "QA path outside allowed root")
    if not args.worker:
        args.run_dir.mkdir(parents=True, exist_ok=False)
        if args.apply:
            argv = [sys.executable, str(Path(__file__).resolve()), "--source-sha", args.source_sha,
                    "--code-sha", args.code_sha, "--run-dir", str(args.run_dir), "--apply", "--worker"]
            child = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                     close_fds=True, creationflags=subprocess.CREATE_BREAKAWAY_FROM_JOB | subprocess.DETACHED_PROCESS)
            deadline = time.monotonic() + 30
            ready = args.run_dir / "worker-ready.json"
            while not ready.exists():
                require(child.poll() is None, "Worker exited before handshake")
                require(time.monotonic() < deadline, "Worker handshake timed out; inspect receipt, no relaunch")
                time.sleep(0.1)
            meta = json.loads(ready.read_text(encoding="utf-8"))
            require(meta["pid"] == child.pid and meta["source_sha"] == args.source_sha and meta["code_sha256"] == args.code_sha and not meta["in_job"] and meta["owner"].casefold() == OWNER.casefold() and meta["session_id"] == 1, "Worker identity differs")
            pending = args.run_dir / "parent-ack.pending"
            pending.write_text(json.dumps(meta), encoding="utf-8")
            os.replace(pending, args.run_dir / "parent-ack.json")
            print(json.dumps({"status": "DETACHED_WORKER_ACKNOWLEDGED", "worker": meta, "worker_os_exit_captured": False}), flush=True)
            return 0
    try:
        backend = NativeBackend(args.run_dir, args.source_sha, args.code_sha)
    except Exception as error:
        (args.run_dir / "initialization-failure.json").write_text(json.dumps({"error_type": type(error).__name__, "error": str(error), "source_sha": args.source_sha, "live_enabled": False}), encoding="utf-8")
        raise
    if args.worker:
        meta = {k: backend.observer[k] for k in ("pid", "owner", "session_id", "in_job")}
        meta.update(source_sha=args.source_sha, code_sha256=args.code_sha)
        pending = args.run_dir / "worker-ready.pending"
        pending.write_text(json.dumps(meta), encoding="utf-8")
        os.replace(pending, args.run_dir / "worker-ready.json")
        deadline = time.monotonic() + 30
        ack_path = args.run_dir / "parent-ack.json"
        try:
            while not ack_path.exists():
                require(time.monotonic() < deadline, "No parent acknowledgement; no mutation")
                time.sleep(0.1)
            ack = json.loads(ack_path.read_text(encoding="utf-8"))
            require(ack == meta, "Parent acknowledgement differs; no mutation")
        except Exception as error:
            backend.receipt({"phase": "HANDSHAKE_FAILED", "error": str(error), "live_enabled": False, "stop_intent": False})
            backend.close()
            return 1
    try:
        result = adopt(backend, args.apply)
        print(json.dumps(result, sort_keys=True), flush=True)
        return 0
    except Exception:
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
