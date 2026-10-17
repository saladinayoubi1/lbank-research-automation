"""V56 adversarial transactional source-day intake regressions.

Tests use synthetic, explicitly marked OS-temp archive fixtures only.
No Bybit requests, trading, clock bypass in real mode, or external writes.
"""
from __future__ import annotations
from pathlib import Path
from unittest.mock import patch
import hashlib
import unittest
import pandas as pd

from prospective_v52 import ProspectiveGateError,verify_official_day_source
from test_official_source_v55 import V55OfflineOfficialIntakeTests
import build_official_day_v55 as mod

class V56AtomicIntakeTests(unittest.TestCase):
    def setUp(self):
        self.ctx=V55OfflineOfficialIntakeTests(methodName="test_complete_future_day_fixture_and_independent_oracle")
        # Reuse the standalone V55 test fixture's exact synthetic raw trades
        # but explicitly register cleanup on *this* test.
        self.ctx.setUp()
        self.addCleanup(self.ctx.doCleanups)
    def _run(self):
        return self.ctx.build()
    def _clean_stages(self):
        return tuple(self.ctx.root.glob(".nexus-elliott-staging-*"))
    def test_commit_only_after_separately_independent_full_oracle(self):
        output=self._run()
        self.assertEqual(output["schema"],"nexus.elliott-v56-transactional-source-intake.v1")
        parquet=Path(output["parquet_path"])
        self.assertEqual(parquet.parent,self.ctx.out)
        self.assertTrue(parquet.is_file())
        self.assertTrue((self.ctx.out/"SOURCE_INTAKE_RECEIPT.json").is_file())
        self.assertFalse(self._clean_stages())
        self.assertEqual(hashlib.sha256(parquet.read_bytes()).hexdigest(),output["parquet_sha256"])
        self.assertEqual(output["status"],"SYNTHETIC_TEST_ONLY")
        self.assertFalse(output["entry_signal"] or output["paper_eligible"] or output["live_enabled"])
    def test_independent_oracle_rejects_and_staging_rolls_back(self):
        rawsha=hashlib.sha256(self.ctx.archive.read_bytes()).hexdigest()
        with patch.object(mod,"verify_official_day_source",
                          side_effect=ProspectiveGateError("forced independent oracle rejection")):
            with self.assertRaisesRegex(ProspectiveGateError,"oracle rejection"):
                self._run()
        self.assertFalse(self.ctx.out.exists())
        self.assertFalse(self._clean_stages())
        self.assertEqual(hashlib.sha256(self.ctx.archive.read_bytes()).hexdigest(),rawsha)
    def test_source_changed_during_build_fails_without_partial_publish(self):
        def tamper_and_verify(*args,**kwargs):
            with self.ctx.archive.open("ab") as stream:stream.write(b"TAMPERED")
            return verify_official_day_source(*args,**kwargs)
        with patch.object(mod,"verify_official_day_source",
                          side_effect=tamper_and_verify):
            with self.assertRaisesRegex(ProspectiveGateError,"SHA mismatch"):
                self._run()
        self.assertFalse(self.ctx.out.exists())
        self.assertFalse(self._clean_stages())
    def test_parquet_writer_failure_rolls_back_unverified_staging(self):
        with patch.object(pd.DataFrame,"to_parquet",
                          side_effect=OSError("synthetic disk I/O failure")):
            with self.assertRaisesRegex(OSError,"disk I/O failure"):
                self._run()
        self.assertFalse(self.ctx.out.exists())
        self.assertFalse(self._clean_stages())
    def test_concurrent_destination_never_overwritten(self):
        original=mod.verify_official_day_source
        def race(*args,**kwargs):
            result=original(*args,**kwargs)
            self.ctx.out.mkdir()
            (self.ctx.out/"existing-marker.txt").write_text("KEEP")
            return result
        with patch.object(mod,"verify_official_day_source",side_effect=race):
            with self.assertRaisesRegex(ProspectiveGateError,"concurrently"):
                self._run()
        self.assertEqual((self.ctx.out/"existing-marker.txt").read_text(),"KEEP")
        self.assertFalse((self.ctx.out/"SOURCE_INTAKE_RECEIPT.json").exists())
        self.assertFalse(self._clean_stages())
    def test_receipt_write_fault_rolls_back_without_evidence_folder(self):
        original=Path.write_text
        def disk_failure(path,*a,**kw):
            if path.name=="SOURCE_INTAKE_RECEIPT.json":
                raise OSError("synthetic receipt write I/O fault")
            return original(path,*a,**kw)
        with patch.object(Path,"write_text",new=disk_failure):
            with self.assertRaisesRegex(OSError,"receipt write"):
                self._run()
        self.assertFalse(self.ctx.out.exists())
        self.assertFalse(self._clean_stages())

if __name__=="__main__":
    unittest.main()
