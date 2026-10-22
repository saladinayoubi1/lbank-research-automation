"""No network or broker: fixed future-window authorization and provenance tests."""
import hashlib
import json
import unittest
from unittest.mock import patch
from pathlib import Path
from tempfile import TemporaryDirectory
from research.nexus_mr40_bybit_forward_shadow_v1 import (
    check_clock,validate_bridge,NOT_BEFORE,run)
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


if __name__=="__main__":
    unittest.main()
