"""V60 archive availability timing regressions with physical synthetic V59 chain."""
import json
import unittest
from datetime import timedelta
from pathlib import Path
from prospective_v52 import ProspectiveGateError
import test_trace_capture_v59 as _fixture
from observability_v60 import audit_source_observability

class V60SourceObservabilityTests(unittest.TestCase):
    def setUp(self):
        self.base=_fixture.V59TwoDayPhysicalChainTests(
            methodName="test_complete_two_day_source_chain_remains_only_research")
        self.base.setUp()
        self.addCleanup(self.base.doCleanups)
    def chain(self):
        return self.base.scan()
    def report(self,chain=None):
        if chain is None:chain=self.chain()
        return audit_source_observability(chain,self.base.captures,self.base.minutes)
    def set_time(self,path,name,value):
        info=json.loads(Path(path).read_text(encoding="utf8"))
        info[name]=value
        Path(path).write_text(json.dumps(info),encoding="utf8")
    def normalize_receipt_creation(self,created="2026-10-18T00:03:00Z"):
        for path in self.base.minutes:
            self.set_time(path,"created_utc",created)
    def test_catches_impossible_synthetic_capture_then_older_minute_receipt(self):
        r=self.report()
        self.assertEqual(r.state,"INVALID_EVIDENCE_STAGE_CHRONOLOGY")
        self.assertFalse(r.physical_source_timing_consistent)
        self.assertFalse(r.physically_available_by_decision)
        self.assertFalse(r.executable_quote_proof or r.publication_time_known)
    def test_bounded_late_source_availability_is_not_realtime(self):
        self.normalize_receipt_creation()
        r=self.report()
        self.assertEqual(r.state,"RETROSPECTIVE_ARCHIVE_AVAILABLE_AFTER_DECISION")
        self.assertTrue(r.physical_source_timing_consistent)
        self.assertEqual(r.availability_lag_seconds,180)
        self.assertFalse(r.physically_available_by_decision)
        self.assertTrue(r.structural_only)
    def test_tamper_receipt_after_chain_check_rejected(self):
        chain=self.chain()
        self.set_time(self.base.minutes[1],"created_utc","2026-10-18T00:03:00Z")
        with self.assertRaisesRegex(ProspectiveGateError,"changed after V59"):
            self.report(chain)
    def test_missing_source_receipt_rejected(self):
        chain=self.chain()
        with self.assertRaisesRegex(ProspectiveGateError,"day count mismatch"):
            audit_source_observability(chain,self.base.captures[:1],self.base.minutes)
    def test_swapped_tls_receipts_rejected(self):
        chain=self.chain()
        with self.assertRaisesRegex(ProspectiveGateError,"changed after V59"):
            audit_source_observability(chain,self.base.captures[::-1],self.base.minutes)
    def test_naive_receipt_created_timestamp_rejected(self):
        self.normalize_receipt_creation()
        self.set_time(self.base.minutes[0],"created_utc","2026-10-18T00:03:00")
        with self.assertRaisesRegex(ProspectiveGateError,"timezone-unaware"):
            self.report()
    def test_missing_receipt_created_timestamp_rejected(self):
        self.set_time(self.base.minutes[0],"created_utc",None)
        with self.assertRaisesRegex(ProspectiveGateError,"timezone-unaware"):
            self.report()
    def test_at_decision_source_availability_is_only_data_gate(self):
        self.set_time(self.base.captures[0],"captured_utc","2026-10-17T00:00:00Z")
        self.set_time(self.base.captures[1],"captured_utc","2026-10-18T00:00:00Z")
        self.normalize_receipt_creation("2026-10-18T00:00:00Z")
        r=self.report()
        self.assertEqual(r.state,"PHYSICAL_SOURCE_AVAILABLE_BY_DECISION_ONLY")
        self.assertEqual(r.availability_lag_seconds,0)
        self.assertTrue(r.physically_available_by_decision)
        self.assertFalse(r.executable_quote_proof)
    def test_capture_before_original_source_day_end_rejected_by_v59(self):
        self.set_time(self.base.captures[1],"captured_utc","2026-10-17T22:00:00Z")
        with self.assertRaisesRegex(ProspectiveGateError,"impossible"):
            self.chain()

if __name__=="__main__":
    unittest.main()
