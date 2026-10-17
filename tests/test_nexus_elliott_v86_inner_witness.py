"""V86 isolated, no-I/O causal/ambiguity tests; never emits trades."""
import unittest
from decimal import Decimal

from research.elliott_v82_causal_degree_observer.observer_v82 import Minute,MINUTE_MS
from research.elliott_v86_diagonal_inner_witness.inner_witness_v86 import (
    visible_prefix,strict_1m_pivots,grade_one_leg,
)

START=1709251200000

def sample(n=45):
    return [Minute(START+i*MINUTE_MS,Decimal("10"),Decimal("9"))
            for i in range(n)]

def pivot(kind,index,confirmation=None):
    return {
        "kind":kind,"center_ms":START+index*MINUTE_MS,
        "confirmed_ms":START+(confirmation if confirmation is not None else index+2)*MINUTE_MS,
    }

class V86InnerWitnessTests(unittest.TestCase):
    def test_future_invalid_tail_invariant(self):
        rows=sample()
        rows[10]=Minute(rows[10].ms,Decimal("20"),Decimal("9"))
        decision=START+30*MINUTE_MS
        first=strict_1m_pivots(rows,decision)
        rows.append(Minute(START+46*MINUTE_MS,Decimal("0"),Decimal("999")))
        self.assertEqual(first,strict_1m_pivots(rows,decision))

    def test_in_prefix_gap_rejected(self):
        rows=sample()
        x=rows[8]
        rows[8]=Minute(x.ms+MINUTE_MS,x.high,x.low)
        with self.assertRaisesRegex(ValueError,"gap"):
            visible_prefix(rows,START+30*MINUTE_MS)

    def test_incomplete_closed_prefix_rejected(self):
        with self.assertRaisesRegex(ValueError,"incomplete"):
            visible_prefix(sample(30),START+31*MINUTE_MS)

    def test_right_hand_confirmation_time(self):
        rows=sample()
        rows[10]=Minute(rows[10].ms,Decimal("20"),Decimal("9"))
        points,_=strict_1m_pivots(rows,START+12*MINUTE_MS)
        self.assertEqual(len(points),1)
        self.assertEqual(points[0]["center_ms"],START+10*MINUTE_MS)
        self.assertEqual(points[0]["confirmed_ms"],START+12*MINUTE_MS)

    def test_unfinished_right_neighbor_excluded(self):
        rows=sample()
        rows[10]=Minute(rows[10].ms,Decimal("20"),Decimal("9"))
        points,_=strict_1m_pivots(rows,START+11*MINUTE_MS)
        self.assertEqual(points,[])

    def test_simultaneous_high_and_low_are_ambiguous(self):
        rows=sample()
        rows[10]=Minute(rows[10].ms,Decimal("20"),Decimal("2"))
        pts,reasons=strict_1m_pivots(rows,START+20*MINUTE_MS)
        self.assertEqual(pts,[])
        self.assertEqual(reasons["dual_center_ms"],[START+10*MINUTE_MS])
        self.assertEqual(reasons["DUAL_EXTREMUM_UNORDERED_OHLC"],1)

    def test_three_leg_skeleton_not_abc_proof(self):
        a=pivot("high",2)
        b=pivot("low",25)
        inn=[pivot("low",10),pivot("high",18)]
        got=grade_one_leg(a,b,inn,START+35*MINUTE_MS)
        self.assertTrue(got["exact_two_alternating"])
        self.assertFalse(got["abc_geometry_proven"])
        self.assertFalse(got["diagonal_proven"])
        self.assertFalse(got["entry_signal"])

    def test_extra_primitive_is_not_removed(self):
        inn=[pivot("low",7),pivot("high",12),pivot("low",20)]
        got=grade_one_leg(pivot("high",2),pivot("low",25),inn,START+35*MINUTE_MS)
        self.assertEqual(got["interior_count"],3)
        self.assertFalse(got["exact_two_alternating"])
        self.assertEqual(len(got["all_interior_strict_pivots"]),3)

    def test_wrong_polarity_rejected(self):
        inn=[pivot("high",10),pivot("low",18)]
        got=grade_one_leg(pivot("high",2),pivot("low",25),inn,START+35*MINUTE_MS)
        self.assertFalse(got["exact_two_alternating"])
        self.assertEqual(got["reason"],"INNER_POLARITY_NOT_ALTERNATING")

    def test_dual_inside_affected_leg_vetoes_skeleton(self):
        inn=[pivot("low",10),pivot("high",18)]
        ambiguous=START+14*MINUTE_MS
        got=grade_one_leg(pivot("high",2),pivot("low",25),inn,
                          START+35*MINUTE_MS,[ambiguous])
        self.assertFalse(got["exact_two_alternating"])
        self.assertEqual(got["ambiguous_unordered_1m_center_ms"],[ambiguous])
        self.assertEqual(got["reason"],"DUAL_EXTREMUM_UNORDERED_OHLC_INSIDE_LEG")

    def test_dual_outside_leg_does_not_change_result(self):
        inn=[pivot("low",10),pivot("high",18)]
        outside=START+29*MINUTE_MS
        got=grade_one_leg(pivot("high",2),pivot("low",25),inn,
                          START+35*MINUTE_MS,[outside])
        self.assertTrue(got["exact_two_alternating"])

    def test_future_child_rejected(self):
        inn=[pivot("low",10,40),pivot("high",18)]
        with self.assertRaisesRegex(ValueError,"future"):
            grade_one_leg(pivot("high",2),pivot("low",25),inn,
                          START+35*MINUTE_MS)

    def test_future_parent_confirmation_rejected(self):
        with self.assertRaisesRegex(ValueError,"future parent"):
            grade_one_leg(pivot("high",2),pivot("low",25,40),[],
                          START+35*MINUTE_MS)

    def test_misordered_parent_rejected(self):
        with self.assertRaisesRegex(ValueError,"must increase"):
            grade_one_leg(pivot("high",25),pivot("low",2),[],
                          START+35*MINUTE_MS)
