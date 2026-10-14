import copy
import base64
import ctypes as C
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from ctypes import wintypes as W
from pathlib import Path

path = Path(__file__).parents[1] / "scripts" / "adopt_nexus_rdc_l1_task.py"
spec = importlib.util.spec_from_file_location("nexus_task_adoption", path)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
XML = (Path(__file__).parent / "fixtures" / "nexus_rdc_l1_task_before.xml").read_text(encoding="utf-8")


class BackendFixture:
    def __init__(self, fail=None, xml=XML):
        self.fail, self.events, self.receipts = fail, [], []
        self.original = {"xml": xml, "sddl": "O:SYG:SYD:(A;;FA;;;SY)", "enabled": True}

    def event(self, name):
        self.events.append(name)
        if name == self.fail:
            raise RuntimeError("fixture failure: " + name)

    def preflight(self, apply): self.event("preflight"); return self.original
    def validate_task(self, prepared, original): self.event("validate")
    def receipt(self, state): self.receipts.append(copy.deepcopy(state))
    def backup(self, original): self.event("backup")
    def stage(self, prepared, original): self.event("stage")
    def install_startup(self): self.event("startup")
    def verify_staged(self, original): self.event("verify")
    def revalidate_old(self): self.event("identities")
    def stop_and_prove_exits(self): self.event("positive_exits")
    def require_zero_clients(self): self.event("zero_clients")
    def refresh_guards(self, staged): self.event("guards")
    def run_once(self, original): self.event("run")
    def await_owned_client(self, original): self.event("new_chain"); return {"client_pid": 20000}
    def rollback(self, original): self.event("rollback")
    def close(self): self.event("close")


class TaskAdoptionTests(unittest.TestCase):
    def test_default_is_read_only_and_closes_handles(self):
        backend = BackendFixture()
        result = mod.adopt(backend)
        self.assertEqual(result["phase"], "READ_ONLY_PASS")
        self.assertEqual(backend.events, ["preflight", "validate", "close"])
        self.assertFalse(result["stop_intent"])

    def test_known_running_original_task_is_valid_for_read_only_planning(self):
        original = {"xml_sha256": mod.TASK_SHA, "enabled": True, "state": 4, "instances": 1, "owner_sid": mod.SID, "allow_demand": True}
        mod.require_original_task(original)
        backend = BackendFixture()
        backend.original.update(original)
        mod.adopt(backend)
        self.assertEqual(backend.events, ["preflight", "validate", "close"])

    def test_unknown_definition_state_or_parallel_instances_block_planning(self):
        original = {"xml_sha256": mod.TASK_SHA, "enabled": True, "state": 4, "instances": 1, "owner_sid": mod.SID, "allow_demand": True}
        for change in ({"xml_sha256": "foreign"}, {"instances": 2}, {"state": 2}, {"enabled": False}, {"owner_sid": "S-1-5-18"}):
            with self.subTest(change=change), self.assertRaises(ValueError): mod.require_original_task(dict(original, **change))

    def test_whole_original_definition_identity_ignores_only_enabled_flag(self):
        root = mod.ET.fromstring(XML)
        mod.ET.SubElement(mod.xml_node(root, "Settings"), "{" + mod.NS + "}Enabled").text = "false"
        disabled = mod.ET.tostring(root, encoding="unicode")
        self.assertEqual(mod.xml_contract(disabled), mod.xml_contract(XML))
        self.assertNotEqual(mod.xml_contract(mod.prepare_task(XML)), mod.xml_contract(XML))

    def test_success_stages_disabled_configuration_before_old_exit_and_one_run(self):
        backend = BackendFixture()
        result = mod.adopt(backend, apply=True)
        self.assertEqual(backend.events, ["preflight", "validate", "backup", "stage", "startup", "verify", "identities", "positive_exits", "zero_clients", "guards", "run", "new_chain", "close"])
        self.assertEqual(result["task_run_requests"], 1)
        self.assertEqual(result["phase"], "ADOPTED_AWAITING_INDEPENDENT_AUDIT")

    def test_stale_preflight_or_invalid_native_xml_cannot_mutate(self):
        for fail in ("preflight", "validate"):
            with self.subTest(fail=fail):
                backend = BackendFixture(fail=fail)
                with self.assertRaises(RuntimeError): mod.adopt(backend, apply=True)
                self.assertNotIn("backup", backend.events)
                self.assertNotIn("run", backend.events)

    def test_partial_stage_or_startup_or_verify_failure_rolls_back_before_stop(self):
        for fail in ("stage", "startup", "verify", "identities"):
            with self.subTest(fail=fail):
                backend = BackendFixture(fail=fail)
                with self.assertRaises(RuntimeError): mod.adopt(backend, apply=True)
                self.assertIn("rollback", backend.events)
                self.assertNotIn("positive_exits", backend.events)
                self.assertNotIn("run", backend.events)
                self.assertTrue(backend.receipts[-1]["configuration_rolled_back"])

    def test_unproven_exit_remaining_client_or_changed_file_prevents_run(self):
        for fail in ("positive_exits", "zero_clients", "guards"):
            with self.subTest(fail=fail):
                backend = BackendFixture(fail=fail)
                with self.assertRaises(RuntimeError): mod.adopt(backend, apply=True)
                self.assertNotIn("run", backend.events)
                self.assertNotIn("rollback", backend.events)
                self.assertTrue(backend.receipts[-1]["stop_intent"])

    def test_run_or_postcheck_failure_never_retries_or_rolls_back_blindly(self):
        for fail in ("run", "new_chain"):
            with self.subTest(fail=fail):
                backend = BackendFixture(fail=fail)
                with self.assertRaises(RuntimeError): mod.adopt(backend, apply=True)
                self.assertEqual(backend.events.count("run"), 1)
                self.assertNotIn("rollback", backend.events)

    def test_task_changes_only_action_and_enabled_preserving_all_other_xml(self):
        prepared = mod.prepare_task(XML)
        self.assertEqual(mod.preserved_contract(XML), mod.preserved_contract(prepared))
        root = mod.ET.fromstring(prepared)
        self.assertEqual(mod.xml_node(root, "Settings/Enabled").text, "false")
        self.assertEqual(mod.xml_node(root, "Actions/Exec/Arguments").text, mod.TASK_ARGS)

    def test_foreign_principal_parallel_policy_or_changed_restart_contract_rejected(self):
        for old, new in ((mod.SID, "S-1-5-18"), ("IgnoreNew", "Parallel"), ("<Count>99</Count>", "<Count>1</Count>"), ("PT5M", "PT1M")):
            with self.subTest(new=new), self.assertRaises(ValueError):
                mod.prepare_task(XML.replace(old, new))

    def test_extra_action_or_lookalike_watchdog_command_rejected(self):
        extra = XML.replace("</Actions>", "<Exec><Command>cmd.exe</Command></Exec></Actions>")
        with self.assertRaises(ValueError): mod.prepare_task(extra)
        with self.assertRaises(ValueError): mod.prepare_task(XML.replace("-File ", "-Command "))

    def test_staged_readback_rejects_changed_security_or_non_action_setting(self):
        original = BackendFixture().original
        actual = dict(original, xml=mod.prepare_task(XML), enabled=False)
        mod.verify_task(actual, original, False)
        with self.assertRaises(ValueError): mod.verify_task(dict(actual, sddl="other"), original, False)
        with self.assertRaises(ValueError): mod.verify_task(dict(actual, xml=actual["xml"].replace("PT5M", "PT3M")), original, False)

    def test_frozen_target_set_excludes_console_explorer_adobe_and_runners(self):
        self.assertEqual(set(mod.TARGETS), {2032, 4000, 12764, 5520})
        self.assertTrue(set(mod.TARGETS).isdisjoint({9040, 11520, 11624, 9176, 9556}))

    def test_native_identity_check_rejects_pid_reuse_and_wrong_owner(self):
        backend = object.__new__(mod.NativeBackend)
        backend.handles = {pid: pid for pid in mod.TARGETS}
        records = {}
        for pid, (ppid, name, ticks, digest) in mod.TARGETS.items():
            records[pid] = {"ppid": ppid, "name": name, "creation_filetime": ticks, "argv_json_sha256": digest,
                            "owner": mod.OWNER, "session_id": 1, "exe": mod.NODE if name == "node.exe" else r"C:\WINDOWS\system32\cmd.exe"}
        backend.inspect = lambda pid, handle: records[pid]
        backend.revalidate_old()
        records[2032]["creation_filetime"] = "999"
        with self.assertRaises(ValueError): backend.revalidate_old()
        records[2032]["creation_filetime"] = mod.TARGETS[2032][2]
        records[2032]["owner"] = "different-user"
        with self.assertRaises(ValueError): backend.revalidate_old()

    def test_startup_requests_only_the_existing_task(self):
        text = mod.STARTUP_BYTES.decode()
        self.assertIn('schtasks.exe"" /Run /TN ""\\NEXUS-Remote-Commander-Recovery', text)
        self.assertNotIn("node.exe", text)
        self.assertNotIn("/Create", text)

    def test_census_catches_other_installations_and_pending_npx_launchers(self):
        backend = object.__new__(mod.NativeBackend)
        class Process:
            def __init__(self, pid): self.pid = pid; self.info = {"name": "node.exe", "exe": mod.NODE}
        rows = {1: {"argv": [mod.NODE, mod.ENTRY, "remote"]},
                2: {"argv": [mod.NODE, r"D:\other\node_modules\@wonderwhy-er\desktop-commander\dist\index.js", "remote"]},
                3: {"argv": [mod.NODE, r"D:\npm\bin\npx-cli.js", "@wonderwhy-er/desktop-commander", "remote"]}}
        backend.psutil = type("Psutil", (), {"process_iter": staticmethod(lambda fields: [Process(pid) for pid in rows])})
        backend.inspect = lambda pid: dict(pid=pid, **rows[pid])
        clients, supervisors, launchers = backend.census()
        self.assertEqual([r["pid"] for r in clients], [1, 2])
        self.assertEqual([r["pid"] for r in launchers], [3])
        self.assertFalse(supervisors)
        with self.assertRaises(ValueError): backend.require_zero_clients()

    def test_unknown_node_permission_gap_blocks_zero_client_gate(self):
        backend = object.__new__(mod.NativeBackend)
        p = type("Process", (), {"pid": 7, "info": {"name": "node.exe", "exe": None}})()
        backend.psutil = type("Psutil", (), {"process_iter": staticmethod(lambda fields: [p])})
        def denied(pid): raise PermissionError("fixture unknown Node")
        backend.inspect = denied
        with self.assertRaises(PermissionError): backend.require_zero_clients()

    @unittest.skipUnless(os.name == "nt", "Native PowerShell5.1 parser fixture")
    def test_real_windows_powershell_rpc_parses_without_executing_any_task_call(self):
        payload = base64.b64encode(mod.TASK_RPC.encode("utf-8")).decode("ascii")
        script = "$s=[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('" + payload + "'));$t=$null;$e=$null;$null=[Management.Automation.Language.Parser]::ParseInput($s,[ref]$t,[ref]$e);if(@($e).Count -gt 0){$e|ForEach-Object{Write-Output $_.Message};exit 1};exit 0"
        encoded = base64.b64encode(script.encode("utf-16le")).decode("ascii")
        result = subprocess.run([mod.PS, "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded], capture_output=True, timeout=30, creationflags=subprocess.CREATE_NO_WINDOW)
        self.assertEqual(result.returncode, 0, (result.stdout + result.stderr).decode(errors="replace"))

    @unittest.skipUnless(os.name == "nt", "Native VBScript parser fixture")
    def test_real_windows_startup_string_parses_without_running_task(self):
        script = mod.STARTUP_BYTES.decode().replace("WScript.Sleep 20000", "").replace("sh.Run cmd, 0, False", "WScript.Echo cmd")
        with tempfile.TemporaryDirectory() as directory:
            file = Path(directory) / "parse-startup.vbs"
            file.write_text(script, encoding="utf-8")
            result = subprocess.run([r"C:\Windows\System32\cscript.exe", "//NoLogo", str(file)], capture_output=True, timeout=30, creationflags=subprocess.CREATE_NO_WINDOW)
        self.assertEqual(result.returncode, 0, (result.stdout + result.stderr).decode(errors="replace"))
        self.assertEqual(result.stdout.decode().strip(), '"C:\\Windows\\System32\\schtasks.exe" /Run /TN "\\NEXUS-Remote-Commander-Recovery"')

    def run_task_double(self, never_stops=False):
        payload = base64.b64encode(XML.encode()).decode()
        behavior = "$this.StopCount++;" if never_stops else "$this.StopCount++;$this.InstanceCount=0;$this.State=3;"
        script = "function Hash-Text([string]$s){[BitConverter]::ToString([Security.Cryptography.SHA256]::Create().ComputeHash([Text.Encoding]::UTF8.GetBytes($s))).Replace('-','').ToLowerInvariant()}\n" + mod.QUIESCE_TASK
        script += "$xml=[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('" + payload + "'));"
        script += "$task=[pscustomobject]@{Name='NEXUS-Remote-Commander-Recovery';Xml=$xml;Enabled=$true;State=4;InstanceCount=1;StopCount=0};"
        script += "$task|Add-Member ScriptMethod GetInstances {param($f) return [pscustomobject]@{Count=$this.InstanceCount}};"
        script += "$task|Add-Member ScriptMethod GetSecurityDescriptor {param($f) return 'fixture-sddl'};"
        script += "$task|Add-Member ScriptMethod Stop {param($f) if($f -ne 0 -or $this.Enabled){throw 'Stopped before disabled'};" + behavior + "};"
        if never_stops:
            script += "try{$null=Quiesce-OriginalTask $task {$task} (Hash-Text $xml) 'fixture-sddl';throw 'Expected timeout'}catch{if($_.Exception.Message -notlike '*stop timeout*'){throw}};if($task.Enabled -or $task.StopCount -ne 1 -or $task.InstanceCount -ne 1){throw 'Timeout boundary differs'};exit 0"
        else:
            script += "$needed=Quiesce-OriginalTask $task {$task} (Hash-Text $xml) 'fixture-sddl';if(-not $needed -or $task.Enabled -or $task.State -ne 3 -or $task.InstanceCount -ne 0 -or $task.StopCount -ne 1){throw 'Quiesce result differs'};"
            script += "$task.Enabled=$true;$task.State=4;$task.InstanceCount=1;try{$null=Quiesce-OriginalTask $task {$task} 'wrong-hash' 'fixture-sddl';throw 'Expected guard rejection'}catch{if($_.Exception.Message -notlike '*Original task changed*'){throw}};if(-not $task.Enabled -or $task.StopCount -ne 1){throw 'Unknown definition mutated'};exit 0"
        encoded = base64.b64encode(script.encode("utf-16le")).decode()
        result = subprocess.run([mod.PS, "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded], capture_output=True, timeout=45, creationflags=subprocess.CREATE_NO_WINDOW)
        self.assertEqual(result.returncode, 0, (result.stdout + result.stderr).decode(errors="replace"))

    @unittest.skipUnless(os.name == "nt", "Native task double; no real task registered or stopped")
    def test_windows_task_double_disables_before_scoped_stop_and_rejects_unknown_definition(self):
        self.run_task_double()

    @unittest.skipUnless(os.name == "nt", "Native bounded task timeout double")
    def test_windows_task_double_timeout_keeps_replacement_unregistered(self):
        self.run_task_double(never_stops=True)

    @unittest.skipUnless(os.name == "nt", "Native Windows handle fixture")
    def test_real_windows_positive_exit_on_only_our_harmless_python_child(self):
        kernel = C.WinDLL("kernel32", use_last_error=True)
        for name, params, result in (
            ("OpenProcess", [W.DWORD, W.BOOL, W.DWORD], W.HANDLE),
            ("WaitForSingleObject", [W.HANDLE, W.DWORD], W.DWORD),
            ("TerminateProcess", [W.HANDLE, W.UINT], W.BOOL),
            ("GetExitCodeProcess", [W.HANDLE, C.POINTER(W.DWORD)], W.BOOL),
            ("CloseHandle", [W.HANDLE], W.BOOL)):
            getattr(kernel, name).argtypes, getattr(kernel, name).restype = params, result
        child = subprocess.Popen([sys.executable, "-c", "import time;time.sleep(30)"], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW)
        handle = kernel.OpenProcess(0x101001, False, child.pid)
        try:
            self.assertTrue(handle)
            self.assertEqual(mod.terminate_held_handles(kernel, [(child.pid, handle)]), [{"pid": child.pid, "positive_exit": True, "exit_code": 70}])
            self.assertEqual(child.wait(timeout=5), 70)
        finally:
            if handle: kernel.CloseHandle(handle)
            if child.poll() is None: child.kill(); child.wait(timeout=5)


if __name__ == "__main__": unittest.main()
