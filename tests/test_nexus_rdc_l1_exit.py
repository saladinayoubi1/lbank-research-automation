"""Actual isolated Node child behavior and strict byte/backup boundaries."""
import importlib.util, json, shutil, subprocess, tempfile, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "scripts/repair_nexus_rdc_l1_exit.py"
BASELINE = ROOT / "docs/evidence/rdc-stability-20261014/laptop1/current-supervisor.cjs"
spec = importlib.util.spec_from_file_location("l1_exit_repair", SOURCE)
repair = importlib.util.module_from_spec(spec)
spec.loader.exec_module(repair)

class ByteTests(unittest.TestCase):
    def test_only_exit_expression_changes_and_is_idempotent(self):
        for ending in (b"\n", b"\r\n"):
            raw = ending.join(BASELINE.read_bytes().splitlines()) + ending
            after = repair.corrected_bytes(raw)
            self.assertEqual(after, raw.replace(repair.OLD, repair.NEW, 1))
            self.assertEqual(repair.corrected_bytes(after), after)

    def test_unexpected_and_full_source_mismatch_fail_closed(self):
        for raw in (b"", b"process.exit(code||0); process.exit(code||0)",
                    BASELINE.read_bytes()+b"// unexpected\n"):
            with self.subTest(raw=raw[:10]):
                with self.assertRaises(ValueError):
                    repair.verify_source(raw)

    def test_backup_exact_repeat_and_no_unrelated_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); target = root/"supervisor.cjs"
            raw = BASELINE.read_bytes(); expected = repair.digest(raw)
            target.write_bytes(raw)
            result = repair.apply_with_backup(target, root/"proof", expected)
            self.assertTrue(result["backup_byte_verified"])
            self.assertEqual((root/"proof/remote-supervisor.cjs.before").read_bytes(), raw)
            self.assertEqual(repair.apply_with_backup(target, root/"again", expected)["status"],
                             "ALREADY_CORRECT")
            self.assertFalse((root/"again").exists())
            target.write_bytes(b"unrelated")
            with self.assertRaises(ValueError):
                repair.apply_with_backup(target, root/"bad", expected)
            self.assertEqual(target.read_bytes(), b"unrelated")

class NodeBehaviorTests(unittest.TestCase):
    def run_fixture(self, fixed, child, auth=True, vm_signal=False):
        node = shutil.which("node")
        self.assertIsNotNone(node, "Actual Node is required for the behavior regression")
        with tempfile.TemporaryDirectory(prefix="nexus l1 exit ") as directory:
            root = Path(directory); source = BASELINE.read_bytes()
            if fixed:
                source = repair.corrected_bytes(source)
            lines = source.decode().splitlines()
            lines[1] = "const root="+json.dumps(str(root))+";"
            lines[2] = "const entry="+json.dumps(str(root/"harmless-child.js"))+";"
            lines[3] = "const state="+json.dumps(str(root/"fixture-session.json"))+";"
            (root/"supervisor.cjs").write_text("\n".join(lines)+"\n", encoding="utf-8")
            (root/"harmless-child.js").write_text(
                "require('fs').writeFileSync('CHILD_EXECUTED','yes');\n"+child+"\n",
                encoding="utf-8")
            (root/"fixture-session.json").write_text(
                json.dumps({"session":{"refresh_token":"isolated-fixture"}} if auth else {}),
                encoding="utf-8")
            program = root/"supervisor.cjs"
            if vm_signal:
                program = root/"signal-fixture.cjs"
                program.write_text(
                    "const vm=require('vm'),fs=require('fs');\n"
                    "const fake={pid:777,on:(event,handler)=>setImmediate(()=>handler(null,'SIGTERM'))};\n"
                    "const supplied=n=>n==='child_process'?{spawn:()=>fake}:require(n);\n"
                    "vm.runInNewContext(fs.readFileSync('supervisor.cjs','utf8'),"
                    "{require:supplied,process,console});\n", encoding="utf-8")
            result = subprocess.run([node,str(program)], cwd=root,
                                    capture_output=True, text=True, timeout=10)
            return result, (root/"CHILD_EXECUTED").exists(), (root/"supervisor.json").exists()

    def test_actual_clean_exit_requests_recovery(self):
        for fixed, expected in ((False,0),(True,1)):
            result, spawned, lock = self.run_fixture(fixed,"process.exit(0);")
            self.assertEqual(result.returncode,expected,result.stderr)
            self.assertTrue(spawned)
            self.assertFalse(lock)

    def test_actual_failure_code_preserved(self):
        for fixed in (False,True):
            result, spawned, lock = self.run_fixture(fixed,"process.exit(7);")
            self.assertEqual(result.returncode,7,result.stderr)
            self.assertTrue(spawned)
            self.assertFalse(lock)

    def test_signal_callback_requests_recovery(self):
        for fixed, expected in ((False,0),(True,1)):
            result, spawned, lock = self.run_fixture(fixed,"process.exit(0);",vm_signal=True)
            self.assertEqual(result.returncode,expected,result.stderr)
            self.assertFalse(spawned)
            self.assertFalse(lock)

    def test_missing_persisted_auth_still_blocks_any_child(self):
        for fixed in (False,True):
            result, spawned, lock = self.run_fixture(fixed,"process.exit(0);",auth=False)
            self.assertEqual(result.returncode,22,result.stderr)
            self.assertFalse(spawned)
            self.assertFalse(lock)

if __name__ == "__main__":
    unittest.main()
