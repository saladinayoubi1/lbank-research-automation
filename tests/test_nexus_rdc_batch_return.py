"""Byte/authority checks plus real Windows CMD crash-return regression."""
import importlib.util, os, subprocess, tempfile, unittest
from pathlib import Path

SOURCE=Path(__file__).resolve().parents[1]/"scripts/repair_nexus_rdc_batch_return.py"
spec=importlib.util.spec_from_file_location("rdc_return_repair",SOURCE)
repair=importlib.util.module_from_spec(spec)
spec.loader.exec_module(repair)

class ReturnRepairTests(unittest.TestCase):
    def test_exact_crlf_preservation_and_idempotence(self):
        original=b"\r\n".join(repair.ORIGINAL)+b"\r\n"
        changed=repair.corrected_bytes(original)
        self.assertEqual(changed,original.replace(repair.NPX,b"call "+repair.NPX,1))
        self.assertEqual(repair.corrected_bytes(changed),changed)

    def test_unrelated_or_authentication_content_fails_closed(self):
        for raw in (b"", b"other launcher", b"\n".join(repair.ORIGINAL)+b"\nset TOKEN=not-a-secret\n"):
            with self.subTest(raw=raw[:12]):
                with self.assertRaises(ValueError):
                    repair.corrected_bytes(raw)

    def test_backup_and_repeat_apply_preserve_original(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary); launcher=root/"remote-supervisor.cmd"
            original=b"\r\n".join(repair.ORIGINAL)+b"\r\n"
            launcher.write_bytes(original)
            result=repair.apply_with_backup(launcher,root/"proof")
            self.assertTrue(result["changed"])
            self.assertEqual((root/"proof/remote-supervisor.cmd.before").read_bytes(),original)
            self.assertEqual(repair.apply_with_backup(launcher,root/"another")["status"],
                             "ALREADY_CORRECT")
            self.assertFalse((root/"another").exists())

    @unittest.skipUnless(os.name=="nt","requires actual Windows CMD")
    def test_native_child_failure_returns_to_two_recovery_iterations(self):
        with tempfile.TemporaryDirectory(prefix="nexus rdc return ") as temporary:
            root=Path(temporary)
            child=root/"npx.cmd"
            child.write_bytes(b"@echo off\r\necho CHILD_RUN\r\nexit /b 7\r\n")
            original=b"\r\n".join(repair.ORIGINAL)+b"\r\n"
            for fixed in (False,True):
                raw=repair.corrected_bytes(original) if fixed else original
                raw=raw.replace(repair.NPX,('"'+str(child)+'" remote').encode())
                raw=raw.replace(b":loop",b"set /a attempts=0 >nul\r\n:loop\r\nset /a attempts+=1 >nul")
                raw=raw.replace(b"timeout /t 15 /nobreak >nul",
                                b"echo RECOVERED\r\nif %attempts% GEQ 2 exit /b 0")
                parent=root/("fixed.cmd" if fixed else "original.cmd")
                parent.write_bytes(raw)
                result=subprocess.run([os.environ["COMSPEC"],"/d","/c",'call "'+str(parent)+'"'],
                                      capture_output=True,text=True,timeout=10)
                with self.subTest(fixed=fixed):
                    self.assertEqual(result.returncode,0 if fixed else 7)
                    self.assertEqual(result.stdout.count("CHILD_RUN"),2 if fixed else 1)
                    self.assertEqual(result.stdout.count("RECOVERED"),2 if fixed else 0)

if __name__=="__main__":
    unittest.main()
