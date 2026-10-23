"""Synthetic pinned 47 MR40 MAE-tail and time-in-market summary guard tests."""
from __future__ import annotations
import tempfile
import unittest
from pathlib import Path
from decimal import Decimal as D
from datetime import datetime,timedelta,timezone
from research.nexus_mr40_all47_tail_risk_distribution_v1 import (
    nearest_rank,normalize,describe,guard_protocol,run
)


def row(i,entry_price="100",lowest="90",hours=8):
    first=datetime(2024,1,1,tzinfo=timezone.utc)+timedelta(days=i)
    low=first+timedelta(hours=4)
    out=first+timedelta(hours=hours)
    mae=(D(lowest)/D(entry_price)-D(1))*D(100)
    return {
        "trade_index":i,
        "window":"train",
        "entry_open_utc":first.isoformat(),
        "exit_open_utc":out.isoformat(),
        "lowest_held_candle_open_utc":low.isoformat(),
        "holding_hours":hours,
        "entry_open_price":entry_price,
        "lowest_held_4h_candle_low":lowest,
        "MAE_price_only_pct_from_entry_OPEN":str(mae),
        "MFE_price_only_pct_from_entry_OPEN":"2",
    }


class TestPinnedTailDistribution(unittest.TestCase):
    def test_nearest_rank_quantile_no_interpolation(self):
        v=[D(1),D(2),D(3),D(8),D(10)]
        self.assertEqual(nearest_rank(v,D("0.5")),D(3))
        self.assertEqual(nearest_rank(v,D("0.95")),D(10))
        self.assertEqual(nearest_rank(v,D("0.75")),D(8))

    def test_percentile_source_denominators_are_fixed(self):
        q=normalize([row(1,lowest="99",hours=8),row(2,lowest="90",hours=48),
                     row(3,lowest="85",hours=124),row(4,lowest="80",hours=168)])
        s=describe(q)
        self.assertEqual(s["n_positions"],4)
        self.assertEqual(s["MAE_count_at_or_above_percent"]["5"],3)
        self.assertEqual(s["MAE_count_at_or_above_percent"]["15"],2)
        self.assertEqual(s["holding_count_at_or_above_hours"]["168"],1)
        self.assertEqual(s["hold_duration_categories"]["lt_48_hours"]["n_positions"],1)
        self.assertEqual(s["hold_duration_categories"]["48_to_119_hours"]["n_positions"],1)
        self.assertEqual(s["hold_duration_categories"]["gte_120_hours"]["n_positions"],2)
        self.assertEqual(D(s["adverse_price_MAE_nearest_rank_pct"]["0.95"]),D("20"))

    def test_malformed_entry_to_low_price_percent_refused(self):
        x=row(1)
        x["MAE_price_only_pct_from_entry_OPEN"]="-5"
        with self.assertRaisesRegex(ValueError,"tampered_entry_low_MAE"):
            normalize([x])

    def test_minimum_candle_cannot_come_after_exit(self):
        x=row(1)
        x["lowest_held_candle_open_utc"]=x["exit_open_utc"]
        with self.assertRaisesRegex(ValueError,"impossible_held_bar_clock"):
            normalize([x])

    def test_duplicate_indices_are_not_silently_dropped(self):
        with self.assertRaisesRegex(ValueError,"missing_or_duplicate"):
            normalize([row(1),row(1)])

    def test_no_gap_between_trade_indexes(self):
        with self.assertRaisesRegex(ValueError,"nonconsecutive"):
            normalize([row(1),row(3)])

    def test_protocol_verifies_expected_source_and_never_promotes(self):
        p={
            "schema":"nexus.mr40.frozen47_tail_risk_exposure_distribution_v1",
            "source":{
                "full_risk_file_sha256":"c401f4920d8f51abe2ed77c11aa3a9616df8cde2d0dd958d7dfd0a59c6cac051",
                "full_risk_logical_digest":"6ec8b21dc24ef1de962c4b439f870420493cecab570c53311eb836dbe7240ba9",
                "market_rows_sha256":"a458d9f83df633df8ee5cab5f2a19de41c4c79c61185b5abd258fdefa80d575a",
                "fee_scenario":"OFFICIAL_SPOT_VIP0_TAKER_REFERENCE",
                "expected_pairs":47},
            "precommitted_descriptive_metrics":{
                "tail_thresholds_price_MAE_pct":[3,5,10,15,20],
                "long_holding_thresholds_hours":[24,72,120,168],
                "quantile_probabilities":[0.5,0.75,0.9,0.95]},
            "constraints":{"orders":0,"promote":False,"live":False},
        }
        guard_protocol(p)
        p["precommitted_descriptive_metrics"]["tail_thresholds_price_MAE_pct"]=[3,5,10,15,25]
        with self.assertRaisesRegex(ValueError,"protocol_drift"):
            guard_protocol(p)

    def test_existing_output_immutable_even_if_sources_missing(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            outfile=root/"existing.json"
            outfile.write_text("prior")
            with self.assertRaisesRegex(ValueError,"refuse_overwrite"):
                run(root/"missing_lock",root/"missing_risk",outfile)
            self.assertEqual(outfile.read_text(),"prior")


if __name__=="__main__":
    unittest.main()
