"""No-network locked Bybit Spot Oct22 tick-vs-live-4h source contract tests."""
from __future__ import annotations
import copy
import json
import tempfile
import unittest
from decimal import Decimal as D
from pathlib import Path
from unittest.mock import patch

from research.nexus_mr40_oct22_tick_vs_ws_reconcile_v1 import (
    DAY_BEGIN,DAY_END,FIXED_BAR_START,LAST_BRIDGE_BAR,
    pinned_protocol, reject_before_day_end, reconcile,verified_bridge,verified_raw_ws,
    execute, canonical,
)


def fixed_day_rows():
    prices=[
        ["82300","82400","81300","81700","300"],
        ["81700","82100","81400","81800","400"],
        ["81800","82150","81200","81500","500"],
        ["81500","82000","81000","81677.3","1000"],
        ["81677.3","81761.2","80927.9","81488.6","2951.920267"],
        ["81488.6","82000","81000","81600","950"]
    ]
    return [[DAY_BEGIN+i*14400000,*values] for i,values in enumerate(prices)]


def ws_fixed():
    return {"ohlcv":["81677.3","81761.2","80927.9","81488.6","2951.920267"]}


def protocol():
    return {
        "schema":"nexus.mr40.bybit_oct22_tick_ws_4h_reconciliation.protocol.v1",
        "archive":{"url":"https://public.bybit.com/spot/BTCUSDT/BTCUSDT_2026-10-22.csv.gz",
                   "timestamp_day_start_ms":DAY_BEGIN,"timestamp_day_end_exclusive_ms":DAY_END},
        "predefined_tolerances":{"absolute_max_per_OHLC_usdt":"0.01",
                                  "max_relative_base_volume_error":"0.001"},
        "historical_prefix":{"bridge_evidence_digest":"f118d0affe21995f4bfa01c1b5261eb7e963d1c1d46bfb094debf28a35c3114e",
                             "previous_12_rows_digest":"a3fe422736b0dd27342b711765e721608cb88f7ec49ef22b723d09b64acaf5a6"},
        "live_capture":{"raw_source_sha256":"7704589ec16144ee9852fb4c8d0aeea49287346891c27f5149825e0311445a7e",
                        "source_gate_digest":"d52988afdce73267a9a8489e516cbce20cd58707b96bf907fc79fcfe4904f30f",
                        "fixed_open_ms":FIXED_BAR_START},
        "safety":{"orders":0,"promote":False}
    }


class TestPinnedOct22Reconcile(unittest.TestCase):
    def test_exact_observed_same_venue_ohlcv_matches(self):
        r=reconcile(fixed_day_rows(),ws_fixed(),LAST_BRIDGE_BAR)
        self.assertTrue(r["source_same_venue_reconciliation_pass"])
        self.assertEqual(r["price_OHLC_abs_diff_usdt"],["0.0","0.0","0.0","0.0"])
        self.assertEqual(r["base_volume_relative_diff"],"0")

    def test_max_price_tolerance_inclusive(self):
        b=fixed_day_rows()
        b[4][4]="81488.61"
        self.assertTrue(reconcile(b,ws_fixed(),LAST_BRIDGE_BAR)["price_comparison_pass"])

    def test_price_exceeds_one_cent_stays_fail(self):
        b=fixed_day_rows()
        b[4][4]="81488.62"
        x=reconcile(b,ws_fixed(),LAST_BRIDGE_BAR)
        self.assertFalse(x["price_comparison_pass"])
        self.assertFalse(x["source_same_venue_reconciliation_pass"])

    def test_base_volume_more_than_point_one_percent_stays_fail(self):
        b=fixed_day_rows()
        b[4][5]=str(D("2951.920267")*D("1.002"))
        x=reconcile(b,ws_fixed(),LAST_BRIDGE_BAR)
        self.assertFalse(x["volume_comparison_pass"])
        self.assertFalse(x["source_same_venue_reconciliation_pass"])

    def test_missing_intermediate_candle_fails_not_filled_from_websocket(self):
        b=fixed_day_rows()
        del b[2]
        with self.assertRaisesRegex(ValueError,"six_complete"):
            reconcile(b,ws_fixed(),LAST_BRIDGE_BAR)

    def test_shifted_bar_gap_rejected_even_if_six_rows(self):
        b=fixed_day_rows()
        b[2][0]+=14400000
        with self.assertRaisesRegex(ValueError,"missing_or_out_of_order"):
            reconcile(b,ws_fixed(),LAST_BRIDGE_BAR)

    def test_unpinned_day_cannot_be_substituted(self):
        q=protocol()
        q["archive"]["url"]=q["archive"]["url"].replace("2026-10-22","2026-10-21")
        with self.assertRaisesRegex(ValueError,"protocol_drift"):
            pinned_protocol(q)

    def test_unpinned_price_tolerance_cannot_be_relaxed(self):
        q=protocol()
        q["predefined_tolerances"]["absolute_max_per_OHLC_usdt"]="1.0"
        with self.assertRaisesRegex(ValueError,"protocol_drift"):
            pinned_protocol(q)

    def test_late_archive_never_read_before_full_utc_day(self):
        with self.assertRaisesRegex(ValueError,"not_yet_completed_no_network"):
            reject_before_day_end(DAY_END-1)
        reject_before_day_end(DAY_END)

    def test_existing_output_prevents_any_archive_access(self):
        with tempfile.TemporaryDirectory() as dir:
            base=Path(dir)
            report=base/"existing.json"
            report.write_text("old_result")
            with patch("research.nexus_mr40_oct22_tick_vs_ws_reconcile_v1.urllib.request.urlopen",
                       side_effect=AssertionError("network_access_forbidden")):
                with self.assertRaisesRegex(ValueError,"refuse_overwrite"):
                    execute(base/"lock.json",base/"bridge.json",base/"ws.json",
                            base/"gate.json",base/"archive.gz",report)
            self.assertEqual(report.read_text(),"old_result")

    def test_archive_source_is_not_replaced_by_mismatched_WS(self):
        x=ws_fixed()
        x["ohlcv"]=["82000","82100","80927.9","81488.6","2951.920267"]
        r=reconcile(fixed_day_rows(),x,LAST_BRIDGE_BAR)
        self.assertFalse(r["source_same_venue_reconciliation_pass"])

    def test_wrong_prefix_cannot_move_start_of_day(self):
        with self.assertRaisesRegex(ValueError,"missing_or_out_of_order"):
            reconcile(fixed_day_rows(),ws_fixed(),LAST_BRIDGE_BAR-14400000)


if __name__=="__main__":
    unittest.main()
