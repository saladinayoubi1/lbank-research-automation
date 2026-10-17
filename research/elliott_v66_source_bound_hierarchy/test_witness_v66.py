"""V66 offline source-proof guard regressions; synthetic, not real prices."""
import copy
import unittest
import numpy as np
import pandas as pd
from witness_v66 import (
    verify_historical_vertices,strict_utc,RESEARCH_ONLY,ENTRY_SIGNAL,
    PAPER_ELIGIBLE,LIVE_ENABLED,ETH_1M_SHA,START
)
def invented_evidence():
    row={
      "schema":"nexus.elliott-v63-real-historical-first-leg-fixed-degree-forensics.v1",
      "source_sha256":ETH_1M_SHA,
      "strict_3m_child_interior_count":6,
      "frozen_strict_child_count_expected":4,
      "selective_pivot_deletion_allowed":False,
      "entry_signal":False,"live_enabled":False,
      "parent_first_low":{"index":3405,"price":"2492.76","open_utc":"2026-10-10T08:45:00Z"},
      "parent_next_high":{"index":3451,"price":"2498.71","open_utc":"2026-10-10T09:31:00Z"},
      "verified_1m_mapped_interior_pivots":[]
    }
    for index,kind,price in (
      (3413,"high","2496.32"),(3422,"low","2495.33"),
      (3432,"high","2498.5"),(3438,"low","2496.03"),
      (3442,"high","2497.78"),(3447,"low","2496.65")):
        row["verified_1m_mapped_interior_pivots"].append({
            "minute_center_index":index,"kind":kind,"price":price,
            "center_open_utc":(START+pd.Timedelta(minutes=index)).isoformat(),
            "one_minute_strict_confirm_close_utc":(START+pd.Timedelta(minutes=index+4)).isoformat(),
            "three_minute_right_confirm_close_utc":(START+pd.Timedelta(minutes=index+6)).isoformat(),
            "first_physical_bar_observable_utc":(START+pd.Timedelta(minutes=index+6)).isoformat()
        })
    return row

def fake_source():
    n=7200
    base=np.full(n,2500.0)
    return pd.DataFrame({
        "timestamp":pd.date_range(START,periods=n,freq="min",tz="UTC"),
        "open":base,"close":base,
        "high":base+0.1,"low":base-0.1
    })

class V66StrictPhysicalGateTests(unittest.TestCase):
    def setUp(self):
        self.source=fake_source()
        self.record=invented_evidence()
    def test_cannot_claim_8_vertices_on_flat_synthetic_history(self):
        with self.assertRaisesRegex(ValueError,"VERTEX_PRICE_OR_STRICT_1M_PIVOT_MISMATCH"):
            verify_historical_vertices(self.source,self.record)
    def test_source_hash_lineage_mismatch_denied(self):
        self.record["source_sha256"]="0"*64
        with self.assertRaisesRegex(ValueError,"LINEAGE"):
            verify_historical_vertices(self.source,self.record)
    def test_missing_1m_bar_denied(self):
        self.source=self.source.drop(index=500).reset_index(drop=True)
        with self.assertRaisesRegex(ValueError,"NOT_FULL"):
            verify_historical_vertices(self.source,self.record)
    def test_out_of_order_minute_grid_denied(self):
        self.source.loc[200,"timestamp"]=self.source.loc[201,"timestamp"]
        with self.assertRaisesRegex(ValueError,"GRID"):
            verify_historical_vertices(self.source,self.record)
    def test_malformed_ohlc_extrema_denied(self):
        self.source.loc[300,"high"]=1.0
        with self.assertRaisesRegex(ValueError,"OHLC"):
            verify_historical_vertices(self.source,self.record)
    def test_price_omission_or_child_pivot_deletion_denied(self):
        self.record["verified_1m_mapped_interior_pivots"].pop()
        with self.assertRaisesRegex(ValueError,"INTERIOR_COUNT"):
            verify_historical_vertices(self.source,self.record)
    def test_version_change_denied(self):
        self.record["schema"]="fake"
        with self.assertRaisesRegex(ValueError,"SCHEMA"):
            verify_historical_vertices(self.source,self.record)
    def test_no_claim_of_live_signals(self):
        self.assertTrue(RESEARCH_ONLY)
        self.assertFalse(ENTRY_SIGNAL or PAPER_ELIGIBLE or LIVE_ENABLED)
    def test_naive_clock_rejected(self):
        with self.assertRaisesRegex(ValueError,"NAIVE"):
            strict_utc("2026-10-10T09:31:00")
if __name__=="__main__":unittest.main()
