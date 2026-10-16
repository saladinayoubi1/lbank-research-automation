"""V82 synthetic contract and no-lookahead QA; never trades."""
import unittest
from decimal import Decimal
from research.elliott_v82_causal_degree_observer.observer_v82 import (
    Minute, Witness, classify_leg, completed_prefix, numeric, observe,
    primitive, validate_minutes, MINUTE_MS,
)
START = 1709251200000

def make_minutes(n=180):
    return [Minute(START+i*MINUTE_MS,Decimal("10"),Decimal("9")) for i in range(n)]

def witness(kind, center, confirm, degree):
    return Witness(kind,START+center*MINUTE_MS,center,
                   START+confirm*MINUTE_MS,"10",degree)

class V82CausalDegreeObserverTests(unittest.TestCase):
    def test_price_validation(self):
        with self.assertRaises(ValueError): numeric("NaN")
        with self.assertRaises(ValueError): numeric(-1)
        with self.assertRaises(ValueError): numeric(1.05)
        self.assertEqual(numeric("1.05"),Decimal("1.05"))

    def test_gap_or_duplicate_rejected(self):
        rows=make_minutes()
        rows[40]=Minute(rows[39].ms,Decimal(10),Decimal(9))
        with self.assertRaisesRegex(ValueError,"gap"):
            validate_minutes(rows)

    def test_decision_time_strict_utc_grid(self):
        rows=make_minutes()
        with self.assertRaisesRegex(ValueError,"UTC 15m"):
            completed_prefix(rows, START+179*MINUTE_MS)
        self.assertEqual(len(completed_prefix(rows,START+180*MINUTE_MS)),180)

    def test_missing_closed_minute_rejected(self):
        rows=make_minutes()
        with self.assertRaises(ValueError):
            completed_prefix(rows[:-1], START+180*MINUTE_MS)

    def test_future_tail_invariance(self):
        rows=make_minutes(180)
        for i in (68,116,151):
            rows[i]=Minute(rows[i].ms,Decimal("17"),Decimal("9"))
        cutoff=START+180*MINUTE_MS
        before=observe(rows,cutoff)
        tail=[Minute(START+(180+i)*MINUTE_MS,Decimal(2000),Decimal("0.1"))
              for i in range(180)]
        after=observe(rows+tail,cutoff)
        self.assertEqual(before,after)

    def test_nonunique_child_extreme_rejected(self):
        rows=make_minutes(45)
        for idx in (18,19):
            rows[idx]=Minute(rows[idx].ms,Decimal(20),Decimal(9))
        identified,reasons=primitive(rows,3,1,"3m/1m")
        self.assertEqual(len(identified),0)
        self.assertGreater(reasons.get("NONUNIQUE_PHYSICAL_CENTER",0),0)

    def test_child_requires_strict_physical_1m_confirmation(self):
        rows=make_minutes(45)
        rows[18]=Minute(rows[18].ms,Decimal(20),Decimal(9))
        rows[21]=Minute(rows[21].ms,Decimal(19),Decimal(9))
        # Coarse bar 6 is greater than adjacent 3m bars, but 1m
        # width-3 fails on minute 21 high 19 because minute 18 high 20.
        identified,reasons=primitive(rows,3,1,"3m/1m")
        self.assertEqual([x.source_minute_index for x in identified],[18])
        self.assertEqual(reasons.get("NOT_STRICT_1M_PIVOT",0),0)

    def test_five_leg_skeleton_is_not_signal(self):
        left=witness("low",0,3,"15m")
        right=witness("high",100,110,"15m")
        c=[witness(k,i,i+4,"3m") for k,i in
           [("high",15),("low",35),("high",55),("low",75)]]
        got=classify_leg(left,right,c)
        self.assertTrue(got["hypotheses"]["MOTIVE_FIVE_LEG_SKELETON"])
        self.assertFalse(got["complete_recursive_elliott"])
        self.assertFalse(got["entry_signal"])
        self.assertEqual(got["all_child_centers_ms"],[x.center_ms for x in c])

    def test_two_child_corrective_skeleton(self):
        a=witness("high",0,3,"15m")
        b=witness("low",100,110,"15m")
        c=[witness("low",25,30,"3m"),witness("high",60,65,"3m")]
        got=classify_leg(a,b,c)
        self.assertTrue(got["hypotheses"]["CORRECTION_THREE_LEG_SKELETON"])
        self.assertFalse(got["hypotheses"]["MOTIVE_FIVE_LEG_SKELETON"])

    def test_extra_pivots_must_not_be_deleted(self):
        left=witness("low",0,3,"15m")
        right=witness("high",100,110,"15m")
        c=[witness(k,i,i+4,"3m") for k,i in [
             ("high",10),("low",20),("high",30),("low",40),
             ("high",50),("low",60)]]
        got=classify_leg(left,right,c)
        self.assertEqual(got["children_observable_by_then"],6)
        self.assertEqual(got["reason"],"CHILD_COUNT_NOT_THREE_OR_FIVE_LEGS")
        self.assertFalse(any(got["hypotheses"].values()))

    def test_unconfirmed_children_not_backdated(self):
        left=witness("low",0,3,"15m")
        right=witness("high",100,110,"15m")
        children=[witness(k,i,i+10,"3m") for k,i in [
            ("high",20),("low",40),("high",60),("low",90)]]
        children[-1]=witness("low",90,111,"3m")
        got=classify_leg(left,right,children)
        self.assertEqual(got["children_observable_by_then"],3)
        self.assertFalse(any(got["hypotheses"].values()))
        self.assertEqual(got["hypothesis_first_seen_ms"],right.confirmed_ms)

    def test_same_kind_parent_cannot_be_directed_leg(self):
        a=witness("high",0,3,"15m")
        b=witness("high",100,110,"15m")
        got=classify_leg(a,b,[])
        self.assertEqual(got["reason"],"PARENT_SAME_KIND_NOT_A_DIRECTED_LEG")
        self.assertFalse(any(got["hypotheses"].values()))
