"""No network or broker: fixed future-window authorization and provenance tests."""
import hashlib
import json
import unittest
from unittest.mock import patch
from pathlib import Path
from tempfile import TemporaryDirectory
from research.nexus_mr40_bybit_forward_shadow_v1 import (
    check_clock,validate_bridge,NOT_BEFORE,run,mark_archive_signals_as_delayed)
from research.nexus_mr40_bybit_archive_bridge_v1 import canon

P={"schema":"nexus.mr40.prospective_spot_archive_shadow_protocol.v1",
   "fixed_observation_day":"2026-10-23",
   "prerequisites":{"historical_bridge_oct20_21_logical_digest":
         "f118d0affe21995f4bfa01c1b5261eb7e963d1c1d46bfb094debf28a35c3114e"},
   "constraints":{"orders":0,"promote":False}}


class TestMR40ForwardShadow(unittest.TestCase):
    def test_refuse_day23_during_unfinished_day(self):
        with self.assertRaisesRegex(ValueError,"future_full_day_not_finished"):
            check_clock(NOT_BEFORE-1)

    def test_ready_only_after_24_oct_utc_begins(self):
        check_clock(NOT_BEFORE)
        check_clock(NOT_BEFORE+3600000)

    def test_refuse_tampered_bridge_payload_before_network(self):
        with self.assertRaisesRegex(ValueError,"historical_bridge_logical_digest_modified"):
            validate_bridge({"digest":"bad","new_4h_rows_utc_day20_21":[]})

    def test_fail_closed_before_any_network_call(self):
        with TemporaryDirectory() as folder:
            root=Path(folder)
            spec=root/"lock.json"
            spec.write_text(json.dumps(P))
            with patch("research.nexus_mr40_bybit_forward_shadow_v1.time.time",return_value=(NOT_BEFORE-1)/1000),patch("research.nexus_mr40_bybit_forward_shadow_v1.get_archive",side_effect=AssertionError("network should not execute")):
                with self.assertRaisesRegex(ValueError,"future_full_day_not_finished"):
                    run(spec,root,root/"bridge.json",root,root/"out.json")
            self.assertFalse((root/"out.json").exists())

    def test_cannot_overwrite_approved_future_report(self):
        with TemporaryDirectory() as folder:
            root=Path(folder)
            out=root/"out.json";out.write_text("previous")
            spec=root/"lock.json";spec.write_text(json.dumps(P))
            with self.assertRaisesRegex(ValueError,"refuse_overwrite"):
                run(spec,root,root/"bridge.json",root,out)


    @staticmethod
    def valid_synthetic_markers():
        from datetime import datetime,timezone
        from research.nexus_mr40_bybit_archive_bridge_v1 import epoch,STEP4
        base=epoch("2026-10-23")
        return [
            {
                "four_hour_open_utc":datetime.fromtimestamp((base+i*STEP4)/1000,timezone.utc).isoformat(),
                "four_hour_end_utc":datetime.fromtimestamp((base+(i+1)*STEP4)/1000,timezone.utc).isoformat(),
                "first_entry_close_marker":i==0,
                "natural_exit_close_marker":False,
            }
            for i in range(6)
        ]

    def test_archive_signal_never_becomes_online_executable_at_market_close(self):
        source=self.valid_synthetic_markers()
        future_receipt=NOT_BEFORE+120000
        annotated=mark_archive_signals_as_delayed(source,future_receipt)
        self.assertEqual(len(annotated),6)
        self.assertTrue(all(r["signal_calculation_is_retrospective_after_archive_release"] for r in annotated))
        self.assertTrue(all(r["next_open_reference_already_past_at_receipt"] for r in annotated))
        self.assertTrue(all(not r["realtime_decision_available_at_original_bar_close"] for r in annotated))
        self.assertTrue(all(r["signal_not_authorized_for_live_or_paper"] for r in annotated))
        self.assertFalse("market_bar_close_ms" in source[0])
        self.assertTrue(annotated[0]["archive_receipt_lag_after_4h_close_ms"] > annotated[-1]["archive_receipt_lag_after_4h_close_ms"])

    def test_fake_early_receipt_fails_closed(self):
        with self.assertRaisesRegex(ValueError,"invalid_fixed_day_archive_receipt"):
            mark_archive_signals_as_delayed(self.valid_synthetic_markers(),NOT_BEFORE-1)

    def test_string_timestamp_not_trusted_as_external_receipt(self):
        with self.assertRaisesRegex(ValueError,"invalid_fixed_day_archive_receipt"):
            mark_archive_signals_as_delayed(self.valid_synthetic_markers(),str(NOT_BEFORE))

    def test_original_candle_market_clock_cannot_be_shifted(self):
        rows=self.valid_synthetic_markers()
        rows[2]["four_hour_open_utc"]="2026-10-23T12:00:00+00:00"
        with self.assertRaisesRegex(ValueError,"archive_signal_market_clock_modified"):
            mark_archive_signals_as_delayed(rows,NOT_BEFORE+1000)

    def test_full_fixed_six_candles_required(self):
        with self.assertRaisesRegex(ValueError,"invalid_fixed_day_archive_receipt"):
            mark_archive_signals_as_delayed(self.valid_synthetic_markers()[:5],NOT_BEFORE+1000)


if __name__=="__main__":
    unittest.main()
