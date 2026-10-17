"""V69 source-arrival classification from a physical synthetic V59 chain."""
import json
import unittest
from pathlib import Path
from prospective_v52 import ProspectiveGateError
from test_trace_capture_v59 import V59TwoDayPhysicalChainTests
from source_asof_v69 import audit_scanned_daily_source_availability

class V69SourceAvailabilityTests(unittest.TestCase):
    def setUp(self):
        self.fixture=V59TwoDayPhysicalChainTests(
            "test_complete_two_day_source_chain_remains_only_research")
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)

    def evaluate(self,**kw):
        opts=dict(symbol="ETHUSDT",
                  tls_receipt_paths=self.fixture.captures,
                  minute_receipt_paths=self.fixture.minutes,
                  decision_close_utc="2026-10-18T00:00:00Z",
                  fixture_mode=True,observed_utc=self.fixture.now)
        opts.update(kw)
        return audit_scanned_daily_source_availability(**opts)

    def edit(self,path,key,value):
        p=Path(path)
        j=json.loads(p.read_text(encoding="utf8"))
        j[key]=value
        p.write_text(json.dumps(j),encoding="utf8")

    def test_inconsistent_stage_time_rejected(self):
        result=self.evaluate()
        self.assertEqual(result.state,"BLOCK_INVALID_SOURCE_STAGE_CHRONOLOGY")
        self.assertFalse(result.research_asof_reporting_eligible)
        self.assertFalse(result.entry_signal or result.live_enabled)

    def test_three_minute_late_receipt_not_backdated(self):
        for p in self.fixture.minutes:
            self.edit(p,"created_utc","2026-10-18T00:03:00Z")
        result=self.evaluate()
        self.assertEqual(result.state,
                         "BLOCK_RETROSPECTIVE_SOURCE_ARRIVED_AFTER_DECISION")
        self.assertEqual(result.availability_lag_seconds,180)
        self.assertFalse(result.actual_source_available_by_decision)

    def test_at_decision_fixture_still_never_market_authority(self):
        self.edit(self.fixture.captures[0],"captured_utc",
                  "2026-10-17T00:00:00Z")
        self.edit(self.fixture.captures[1],"captured_utc",
                  "2026-10-18T00:00:00Z")
        for p in self.fixture.minutes:
            self.edit(p,"created_utc","2026-10-18T00:00:00Z")
        result=self.evaluate()
        self.assertEqual(result.state,"SYNTHETIC_SOURCE_ONLY_NO_REAL_SCORE")
        self.assertTrue(result.actual_source_available_by_decision)
        self.assertFalse(result.research_asof_reporting_eligible)
        self.assertIsNone(result.pnl)

    def test_corrupted_captured_http_status_fails_before_scoring(self):
        self.fixture.corrupt_capture(1,"http_status",302)
        with self.assertRaises(ProspectiveGateError):
            self.evaluate()

    def test_real_market_clock_override_denied(self):
        with self.assertRaisesRegex(ProspectiveGateError,"clock injection"):
            self.evaluate(fixture_mode=False)

if __name__=="__main__":
    unittest.main()
