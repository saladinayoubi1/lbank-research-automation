"""No-network guard checks for retrospective authentic Oct22 MR40 signals."""
import copy,tempfile,unittest,json
from pathlib import Path
from research.nexus_mr40_oct22_verified_spot_close_state_v1 import (
    verify_lock,verified_inputs,compute,run,utc,ROWS_SHA,ARCHIVE_SHA,REPORT_SHA,
    AUDIT_DIGEST,SCHEMA,EXPECTED_BRIDGE,EXPECTED_BRIDGE_ROWS,WS_SHA)
from research.nexus_mr40_bybit_archive_bridge_v1 import epoch
from research.nexus_mr40_independent_closed_signal_v1 import STEP

def locked():
    return {"schema":SCHEMA,
      "sources":{"original_4h_count":8514,"original_4h_digest":ROWS_SHA,
        "original_closed_entry_count":47,"original_closed_exit_count":47,
        "bridge_4h_count":12,"bridge_logical_digest":EXPECTED_BRIDGE,
        "bridge_12_rows_digest":EXPECTED_BRIDGE_ROWS,
        "oct22_day":"2026-10-22","oct22_4h_count":6,
        "verified_oct22_independent_spot_archive_gzip_sha256":ARCHIVE_SHA,
        "verified_oct22_public_tick_WS_parity_report_sha256":REPORT_SHA,
        "verified_oct22_public_tick_WS_parity_logical_digest":AUDIT_DIGEST,
        "original_native_confirmed_49_frame_WS_sha256":WS_SHA},
      "signal_contract":{"entry_z_lte":"-2","natural_exit_z_gte":"0",
         "episode_first_momentum30":"close[j]>=close[j-180]",
         "lookback_40_prior_closed_candles":True,
         "match_bridge_12_signal_states":True,
         "output_six_historical_oct22_closed_bar_states":True},
      "safety":{"orders":0,"promote":False,"live":False,
                "not_future_OOS":True,"paper_modified":False,
                "refuse_overwrite":True}}

class TestHistoricalOct22SourceLockedState(unittest.TestCase):
    def test_authentic_day_and_MR40_parameters_are_immutable(self):
        verify_lock(locked())
        p=locked();p["sources"]["oct22_day"]="2026-10-23"
        with self.assertRaisesRegex(ValueError,"lock_drift"):verify_lock(p)

    def test_no_after_the_fact_stop_or_threshold_tuning(self):
        p=locked();p["signal_contract"]["entry_z_lte"]="-1.5"
        with self.assertRaisesRegex(ValueError,"lock_drift"):verify_lock(p)
        p=locked();p["signal_contract"]["episode_first_momentum30"]="always"
        with self.assertRaisesRegex(ValueError,"lock_drift"):verify_lock(p)

    def test_no_live_or_paper_promotion(self):
        p=locked();p["safety"]["orders"]=1
        with self.assertRaisesRegex(ValueError,"lock_drift"):verify_lock(p)
        p=locked();p["safety"]["promote"]=True
        with self.assertRaisesRegex(ValueError,"lock_drift"):verify_lock(p)

    def test_source_incomplete_or_invalid_counts_fail_closed(self):
        with self.assertRaisesRegex(ValueError,"required_full_contiguous_history"):
            compute([],[],{},[],"2026-10-23T05:17:22+00:00")
        # Even a correctly sized but unverified historical bridge has no
        # permission to create an apparently valid Oct22 signal report.
        with self.assertRaisesRegex(ValueError,"pinned_bridge_12_signals_missing"):
            compute([[0]]*8514,[[0]]*12,{"new_asof_signal_descriptions":[]},
                    [[0]]*6,"2026-10-23T05:17:22+00:00")

    def test_source_file_or_audit_missing_rejected_before_any_engine_replay(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);spec=root/"policy.json";spec.write_text(json.dumps(locked()))
            with self.assertRaises(FileNotFoundError):
                verified_inputs(spec,root,root/"bridge.json",root/"missing.gz",root/"proof.json")

    def test_report_cannot_overwrite_existing_evidence(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);out=root/"existing.json";out.write_text("LOCKED_SOURCE")
            with self.assertRaisesRegex(ValueError,"never_overwrite"):
                run(root/"missing",root,root/"b",root/"a.gz",root/"proof",out)
            self.assertEqual(out.read_text(),"LOCKED_SOURCE")

    def test_bar_clock_is_UTC_fixed_4h_and_never_a_fill(self):
        self.assertEqual(utc(epoch("2026-10-22")),"2026-10-22T00:00:00+00:00")
        self.assertEqual(utc(epoch("2026-10-22")+5*STEP),"2026-10-22T20:00:00+00:00")

if __name__=="__main__":
    unittest.main()
