"""V87 synthetic sourced 1m correction skeleton cases, no trading."""
import unittest
from decimal import Decimal as D
from research.elliott_v82_causal_degree_observer.observer_v82 import (
    Minute, Witness, MINUTE_MS,
)
from research.elliott_v87_correction_witness.correction_v87 import (
    assess_correction,
)

START=1709251200000
ASOF=START+75*MINUTE_MS
ZIG=[(0,110),(5,100),(9,110),(12,104),(16,115),(19,108),
     (23,125),(27,112),(31,118),(35,107),
     (39,127),(42,113),(46,135),(49,122),(53,143),(75,130)]
FLAT=[(0,110),(5,100),(9,110),(12,104),
      (23,125),(27,112),(31,118),(35,107),
      (39,127),(42,113),(46,135),(49,122),(53,143),(75,130)]
CENTERS=(5,23,35,53)
KINDS=("low","high","low","high")


def fixture(knots=ZIG, n=75):
    values={}
    for (a,x),(b,y) in zip(knots,knots[1:]):
        for i in range(a,b+1):
            values[i]=D(x)+(D(y)-D(x))*D(i-a)/D(b-a)
    source=[Minute(START+i*MINUTE_MS,values[i]+D("0.01"),
                   values[i]-D("0.01")) for i in range(n)]
    witnesses=[]
    for center,kind in zip(CENTERS,KINDS):
        p=source[center].low if kind=="low" else source[center].high
        witnesses.append(Witness(kind,source[center].ms,center,
                                 source[center].ms+4*MINUTE_MS,str(p),"synthetic"))
    return source,witnesses

class V87CorrectionWitnessTests(unittest.TestCase):
    def test_zigzag_535_skeleton_only(self):
        rows,v=fixture(ZIG)
        got=assess_correction(v,rows,ASOF)
        self.assertEqual(got["inner_counts_ABC"],[4,2,4])
        self.assertTrue(got["zigzag_535_skeleton"])
        self.assertFalse(got["flat_335_skeleton"])
        self.assertFalse(got["zigzag_subwave_geometry_proven"])
        self.assertFalse(got["entry_signal"])
        self.assertIsNone(got["new_pnl"])

    def test_flat_335_skeleton_only(self):
        rows,v=fixture(FLAT)
        got=assess_correction(v,rows,ASOF)
        self.assertEqual(got["inner_counts_ABC"],[2,2,4])
        self.assertTrue(got["flat_335_skeleton"])
        self.assertFalse(got["zigzag_535_skeleton"])
        self.assertFalse(got["flat_subwave_geometry_proven"])

    def test_reject_incomplete_ABC_vertices(self):
        rows,v=fixture()
        with self.assertRaisesRegex(ValueError,"exactly four"):
            assess_correction(v[:3],rows,ASOF)

    def test_source_price_mismatch_rejected(self):
        rows,v=fixture()
        w=v[1]
        v[1]=Witness(w.kind,w.center_ms,w.source_minute_index,
                     w.confirmed_ms,"999",w.degree)
        with self.assertRaisesRegex(ValueError,"OHLC"):
            assess_correction(v,rows,ASOF)

    def test_future_confirmed_outer_rejected(self):
        rows,v=fixture()
        w=v[2]
        v[2]=Witness(w.kind,w.center_ms,w.source_minute_index,
                     ASOF+MINUTE_MS,w.price,w.degree)
        with self.assertRaisesRegex(ValueError,"future"):
            assess_correction(v,rows,ASOF)

    def test_future_invalid_tail_ignored(self):
        rows,v=fixture()
        original=assess_correction(v,rows,ASOF)
        rows.append(Minute(START+76*MINUTE_MS,D(-5),D(10)))
        self.assertEqual(original,assess_correction(v,rows,ASOF))

    def test_incomplete_source_rejected(self):
        rows,v=fixture()
        with self.assertRaisesRegex(ValueError,"incomplete"):
            assess_correction(v,rows[:-1],ASOF)

    def test_gap_in_known_prefix_rejected(self):
        rows,v=fixture()
        t=rows[15]
        rows[15]=Minute(t.ms+MINUTE_MS,t.high,t.low)
        with self.assertRaisesRegex(ValueError,"gap"):
            assess_correction(v,rows,ASOF)

    def test_extra_observed_swing_not_compressed(self):
        knots=list(ZIG)
        # Insert a strictly confirmed reversal in wave A, no repicking pivots.
        knots=sorted([*knots,(21,112),(22,109)])
        rows,v=fixture(knots)
        result=assess_correction(v,rows,ASOF)
        self.assertNotEqual(result["inner_counts_ABC"],[4,2,4])
        self.assertFalse(result["zigzag_535_skeleton"])

    def test_double_local_extremum_vetoes_skeleton(self):
        rows,v=fixture()
        t=rows[28]
        rows[28]=Minute(t.ms,D(200),D(1))
        got=assess_correction(v,rows,ASOF)
        self.assertFalse(got["zigzag_535_skeleton"])
        self.assertEqual(got["state"],"AMBIGUOUS_UNORDERED_1M_EXTREMA_ABSTAIN")
        self.assertIn(t.ms,got["ambiguous_dual_extrema_centers_ms"])

    def test_wrong_outer_direction_no_signal(self):
        rows,v=fixture()
        w=v[2]
        v[2]=Witness("high",w.center_ms,w.source_minute_index,
                     w.confirmed_ms,str(rows[w.source_minute_index].high),w.degree)
        result=assess_correction(v,rows,ASOF)
        self.assertEqual(result["state"],"NOT_THREE_DIRECTED_CORRECTION_LEGS")
        self.assertFalse(result["entry_signal"])

    def test_center_mismatch_rejected(self):
        rows,v=fixture()
        w=v[0]
        v[0]=Witness(w.kind,w.center_ms+MINUTE_MS,w.source_minute_index,
                     w.confirmed_ms,w.price,w.degree)
        with self.assertRaisesRegex(ValueError,"unbacked"):
            assess_correction(v,rows,ASOF)

    def test_source_1m_numeric_integrity(self):
        rows,v=fixture()
        row=rows[15]
        rows[15]=Minute(row.ms,D("NaN"),row.low)
        with self.assertRaises(ValueError):
            assess_correction(v,rows,ASOF)
