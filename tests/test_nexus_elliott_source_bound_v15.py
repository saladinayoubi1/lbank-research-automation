"""V15 source-bound Elliott seven-extrema QA. Synthetic, not market replay."""
import unittest
from dataclasses import replace

import numpy as np
import pandas as pd

from nexus_elliott_five_swing_review import ConfirmedPivot
from nexus_elliott_source_bound_v15 import (
    ENTRY_SIGNAL, PAPER_ELIGIBLE, RECURSIVE_ELLIOTT_PROVEN,
    RESEARCH_ONLY, certify_seven_pivots_from_closed_15m,
)


ANCHORS = ((0, 110), (10, 100), (20, 120), (30, 112),
           (40, 140), (50, 125), (60, 160), (70, 130),
           (73, 159), (74, 161))
INDEXES = (10, 20, 30, 40, 50, 60, 70)
KINDS = ("low", "high", "low", "high", "low", "high", "low")


def make_ohlc():
    base=np.interp(np.arange(75),*[np.array(x) for x in zip(*ANCHORS)])
    utc=pd.date_range("2024-01-01T00:00:00Z",periods=75,freq="15min")
    f=pd.DataFrame({
        "timestamp":utc, "open":base, "high":base+.2,
        "low":base-.2, "close":base,
    })
    p=tuple(ConfirmedPivot(kind,index,index+3,
            float(f.loc[index,"low" if kind=="low" else "high"]))
            for kind,index in zip(KINDS,INDEXES))
    return f,p


class ElliottRawSourceV15Tests(unittest.TestCase):
    def setUp(self):
        self.f,self.p=make_ohlc()
        self.decision_close=self.f.timestamp.iloc[-1]+pd.Timedelta(minutes=15)

    def audit(self,frame=None,pivots=None,d=74,stamp=None):
        return certify_seven_pivots_from_closed_15m(
            self.f if frame is None else frame,
            self.p if pivots is None else pivots,
            d,decision_close_utc=self.decision_close if stamp is None else stamp)

    def test_source_bound_shape_only_no_order_or_recursive_claim(self):
        r=self.audit()
        self.assertTrue(r.source_bound)
        self.assertTrue(r.seven_pivots_confirmed)
        self.assertEqual(r.reason,"SOURCE_BOUND_LIMITED_SEVEN_PIVOT_SHAPE")
        self.assertEqual(r.pivot_indices,INDEXES)
        self.assertEqual(r.confirmation_indices,tuple(x+3 for x in INDEXES))
        self.assertEqual(r.structure_id,(10,60))
        self.assertFalse(r.entry_signal)
        self.assertFalse(r.paper_eligible)
        self.assertFalse(r.recursive_elliott_proven)
        self.assertTrue(RESEARCH_ONLY)
        self.assertFalse(ENTRY_SIGNAL)
        self.assertFalse(PAPER_ELIGIBLE)
        self.assertFalse(RECURSIVE_ELLIOTT_PROVEN)

    def test_price_forgery_detected(self):
        forged=list(self.p)
        forged[5]=replace(forged[5],price=160.3)
        self.assertEqual(self.audit(pivots=forged).reason,"PIVOT_PRICE_MISMATCH")

    def test_confirmation_backdating_detected(self):
        forged=list(self.p)
        forged[6]=replace(forged[6],confirmed_at=72)
        self.assertEqual(self.audit(pivots=forged).reason,"PIVOT_OR_CONFIRMATION_MISMATCH")

    def test_wrong_pivot_count_fails_closed(self):
        self.assertEqual(self.audit(pivots=self.p[1:]).reason,"SEVEN_EXPECTED_PIVOTS_REQUIRED")

    def test_missing_15m_bar_fails_closed(self):
        f=self.f.drop(index=25).reset_index(drop=True)
        with self.assertRaisesRegex(ValueError,"future tail / incomplete"):
            self.audit(frame=f)

    def test_gap_same_count_rejected(self):
        f=self.f.copy()
        f.loc[25:,"timestamp"]+=pd.Timedelta(minutes=15)
        with self.assertRaisesRegex(ValueError,"grid"):
            self.audit(frame=f)

    def test_naive_clock_rejected(self):
        f=self.f.copy()
        f["timestamp"]=f.timestamp.dt.tz_localize(None)
        with self.assertRaisesRegex(ValueError,"timezone"):
            self.audit(frame=f)

    def test_wrong_decision_timestamp_rejected(self):
        with self.assertRaisesRegex(ValueError,"future/incomplete"):
            self.audit(stamp=self.decision_close+pd.Timedelta(minutes=15))

    def test_future_append_is_not_accepted(self):
        f=pd.concat([self.f,self.f.iloc[[-1]]],ignore_index=True)
        f.loc[75,"timestamp"]+=pd.Timedelta(minutes=15)
        with self.assertRaisesRegex(ValueError,"future tail"):
            self.audit(frame=f)

    def test_flat_tie_pivot_fails_closed(self):
        f=self.f.copy()
        f.loc[11,"low"]=f.loc[10,"low"]
        r=self.audit(frame=f)
        self.assertFalse(r.source_bound)

    def test_broken_ohlc_rejected(self):
        f=self.f.copy()
        f.loc[50,"high"]=f.loc[50,"low"]-.1
        with self.assertRaisesRegex(ValueError,"OHLC"):
            self.audit(frame=f)

    def test_outside_bar_with_both_extrema_refused(self):
        f=self.f.copy()
        f.loc[10,"high"]=f.loc[10,"high"]+100
        r=self.audit(frame=f)
        self.assertFalse(r.source_bound)

    def test_origin_breach_refused(self):
        f=self.f.copy()
        f.loc[35,"low"]=95
        r=self.audit(frame=f)
        self.assertFalse(r.source_bound)

    def test_cannot_use_unconfirmed_correction(self):
        f=self.f.iloc[:73].copy()
        d=72
        stamp=f.timestamp.iloc[-1]+pd.Timedelta(minutes=15)
        r=self.audit(frame=f,d=d,stamp=stamp)
        self.assertFalse(r.source_bound)

    def test_structural_nonoverlap_refused(self):
        f=self.f.copy()
        f.loc[49,"low"]=119
        r=self.audit(frame=f)
        self.assertFalse(r.source_bound)

    def test_partial_shifted_relative_window_refused(self):
        f=self.f.iloc[10:].copy()
        with self.assertRaisesRegex(ValueError,"index-zero"):
            self.audit(frame=f)

    def test_nonnumeric_price_fails_closed(self):
        forged=list(self.p)
        forged[0]=replace(forged[0],price="NaN")
        self.assertEqual(self.audit(pivots=forged).reason,"PIVOT_PRICE_MISMATCH")


if __name__=="__main__":
    unittest.main()
