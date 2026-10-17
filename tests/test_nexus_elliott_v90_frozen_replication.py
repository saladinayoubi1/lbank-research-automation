"""V90 fixed temporal/safety/immutability gates; synthetic, no network."""
import copy
import json
import unittest
from unittest.mock import patch
from research.elliott_v82_causal_degree_observer.observer_v82 import Witness
from research.elliott_v88_replication_lock import lock_v88
from research.elliott_v90_frozen_replication import replicate_v90 as v90


def witness(kind,center,confirmed,idx):
    return Witness(kind,center,idx,confirmed,"100","synthetic")


class V90FixedReplicationTests(unittest.TestCase):
    def test_week_boundary_first_observable_not_pivot_center(self):
        self.assertEqual(v90.split_for(v90.START_MS),"A")
        self.assertEqual(v90.split_for(v90.SPLIT_MS-60000),"A")
        self.assertEqual(v90.split_for(v90.SPLIT_MS),"B")
        self.assertEqual(v90.split_for(v90.END_MS),"B")
        self.assertEqual(v90.END_MS-v90.START_MS,14*1440*60000)

    def test_week_boundary_out_of_range_rejected(self):
        for x in (v90.START_MS-60000,v90.END_MS+60000):
            with self.subTest(timestamp=x):
                with self.assertRaisesRegex(ValueError,"outside original"):
                    v90.split_for(x)

    def test_malformed_timestamp_rejected(self):
        for x in (True,0.0,"2024-07-08",None):
            with self.subTest(value=x):
                with self.assertRaisesRegex(ValueError,"typed"):
                    v90.split_for(x)

    def test_future_confirmed_child_not_backfilled(self):
        start=v90.START_MS
        a=witness("high",start+10*60000,start+18*60000,10)
        b=witness("low",start+50*60000,start+60*60000,50)
        included=witness("low",start+25*60000,start+40*60000,25)
        late=witness("high",start+35*60000,start+65*60000,35)
        out_of_interval=witness("high",start+100*60000,start+110*60000,100)
        observed=v90.matching_children(a,b,[included,late,out_of_interval],
                                       start+60*60000)
        self.assertEqual(observed,[included])

    def test_frozen_source_not_changed(self):
        m=lock_v88.manifest()
        self.assertEqual(m["frozen_recognition"]["zigzag_535_inner_1m_pivot_counts_ABC"],[4,2,4])
        self.assertEqual(m["frozen_recognition"]["flat_335_inner_1m_pivot_counts_ABC"],[2,2,4])
        self.assertEqual(v90.V89_HEAD,"7f61fa134ecd1e937f3aa9a242820f5f3e99d322")
        self.assertEqual(v90.SOURCE_RECEIPT_SHA,"e1c3988f6112ccd12883e35704b63024dc56bf52cc7a38f36ef42e743c2ed7df")

    def test_never_executable(self):
        self.assertTrue(v90.RESEARCH_ONLY)
        self.assertFalse(v90.ENTRY_SIGNAL)
        self.assertFalse(v90.PAPER_ELIGIBLE)
        self.assertFalse(v90.LIVE_ENABLED)
        self.assertTrue(v90.V52_UNCHANGED)

    def test_wrong_locked_rules_fail_before_any_source_read(self):
        altered=lock_v88.manifest()
        altered["frozen_recognition"]["flat_335_inner_1m_pivot_counts_ABC"]=[2,3,4]
        with patch.object(v90,"verify_locked_receipts",
                          return_value=(altered,{"archives":[]})
                          ),patch.object(v90,"assess_symbol",
                                         side_effect=AssertionError("source must not open")):
            with self.assertRaisesRegex(ValueError,"frozen classifier"):
                v90.full_replication()

    def test_exact_interior_excludes_boundary_centers(self):
        start=v90.START_MS
        left=witness("high",start+10*60000,start+15*60000,10)
        right=witness("low",start+40*60000,start+45*60000,40)
        border_l=witness("low",left.center_ms,start+20*60000,10)
        inside=witness("low",start+25*60000,start+30*60000,25)
        border_r=witness("high",right.center_ms,start+44*60000,40)
        self.assertEqual(v90.matching_children(left,right,[border_l,inside,border_r],
                                                start+45*60000),[inside])

    def test_no_third_symbol_admitted_by_preselected_calendar(self):
        schedule=lock_v88.manifest()["scheduled_inputs"]
        self.assertEqual({x["symbol"] for x in schedule},{"BTCUSDT","ETHUSDT"})
        self.assertEqual(len(schedule),28)

    def test_frozen_result_write_is_idempotent_and_fail_closed(self):
        import tempfile
        from pathlib import Path
        fake=lock_v88.manifest()
        output={"all_weeks_counts":{"parent_intervals_observed":3},
                "parent_15m_pivot_witnesses":4,
                "child_3m_pivot_witnesses":12,
                "week_A_counts":{"parent_intervals_observed":1},
                "week_B_counts":{"parent_intervals_observed":2}}
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(v90,"ROOT",Path(tmp)),patch.object(
                    v90,"verify_locked_receipts",return_value=(fake,{})),patch.object(
                    v90,"assess_symbol",return_value=output):
                x=v90.full_replication()
                stored=(Path(tmp)/"V90_REPLICATION_AUDIT.json")
                first=stored.read_bytes()
                self.assertFalse(x["paper_eligible"])
                self.assertFalse(x["live_enabled"])
                self.assertIsNone(x["net_pnl"])
                v90.full_replication()
                self.assertEqual(first,stored.read_bytes())
                original=json.loads(first)
                original["signal_count"]=10
                stored.write_text(json.dumps(original))
                with self.assertRaisesRegex(ValueError,"cannot overwrite"):
                    v90.full_replication()
