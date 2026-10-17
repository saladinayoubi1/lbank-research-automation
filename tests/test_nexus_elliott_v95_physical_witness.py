"""V95 synthetic physical-minute adversarial cases; CI needs no laptop archive."""
import copy
import unittest
from decimal import Decimal as D

from research.elliott_v82_causal_degree_observer.observer_v82 import Minute
from research.elliott_v86_diagonal_inner_witness.inner_witness_v86 import strict_1m_pivots
from research.elliott_v95_physical_witness import witness_v95 as v95

START=1719792000000
MINUTE=60000


def source():
    highs=[10,15,12,11,16,9,10]
    lows=[8,7,6,7,5,6,7]
    return [Minute(START+i*MINUTE,D(hi),D(lo)) for i,(hi,lo) in
            enumerate(zip(highs,lows))]


def synthetic_candidate():
    minutes=[]
    for i in range(61):
        minutes.append(Minute(START+i*MINUTE,D(110+i%3),D(90-i%2)))
    asof=START+61*MINUTE
    centers=[START+i*MINUTE for i in (5,15,25,35,45,55)]
    original,duals=v95.independent_1m_extrema(minutes,asof)
    prices=[]
    legs=[]
    for i,center in enumerate(centers):
        minute=minutes[(center-START)//MINUTE]
        prices.append(str(minute.low if i%2==0 else minute.high))
    for a,b in zip(centers,centers[1:]):
        selected=[p for p in original if a<p["center_ms"]<b]
        ambiguity=[t for t in duals if a<t<b]
        legs.append({"left_center_ms":a,
                     "right_center_ms":b,
                     "asof_ms":asof,
                     "all_interior_strict_pivots":selected,
                     "ambiguous_unordered_1m_center_ms":ambiguity,
                     "interior_count":len(selected)})
    candidate={
        "week":"B",
        "first_observable_ms":asof,
        "v83":{
            "first_observable_ms":asof,
            "orientation":"bullish",
            "vertex_center_ms":centers,
            "vertex_confirmed_ms":[c+3*MINUTE for c in centers],
            "price_vertices":prices,
            "entry_signal":False,
        },
        "v86":{
            "asof_ms":asof,
            "entry_signal":False,
            "observed_full_prefix_1m_strict_points":len(original),
            "global_dual_extremum_abstentions":{"dual_center_ms":duals},
            "per_leg_inner_counts":[p["interior_count"] for p in legs],
            "legs":legs,
        },
    }
    return candidate,minutes


class V95PhysicalSourceWitnessTests(unittest.TestCase):
    def test_independent_known_local_extrema_and_ambiguity(self):
        mins=source()
        found,ambiguous=v95.independent_1m_extrema(mins,START+7*MINUTE)
        self.assertEqual([x["kind"] for x in found],["high","low"])
        self.assertEqual([x["center_ms"] for x in found],
                         [START+MINUTE,START+2*MINUTE])
        self.assertEqual(ambiguous,[START+4*MINUTE])
        self.assertEqual(found[0]["confirmed_ms"],START+3*MINUTE)

    def test_strict_observer_agrees_on_unmodified_synthetic_source(self):
        mins=source()
        a,b=v95.independent_1m_extrema(mins,START+7*MINUTE)
        c,d=strict_1m_pivots(mins,START+7*MINUTE)
        self.assertEqual(a,c)
        self.assertEqual(b,d["dual_center_ms"])

    def test_future_tail_does_not_modify_closed_prefix(self):
        mins=source()
        before=v95.independent_1m_extrema(mins,START+7*MINUTE)
        future=[Minute(START+7*MINUTE,D(999),D(1)),
                Minute(START+8*MINUTE,D(800),D("0.5"))]
        after=v95.independent_1m_extrema(mins+future,START+7*MINUTE)
        self.assertEqual(before,after)

    def test_right_edge_requires_right_closed_bar(self):
        mins=source()
        a,_=v95.independent_1m_extrema(mins,START+3*MINUTE)
        self.assertEqual(a,[{
            "kind":"high","center_ms":START+MINUTE,
            "confirmed_ms":START+3*MINUTE,
            "price":"15","source_minute_index":1}])
        newer,_=v95.independent_1m_extrema(mins,START+4*MINUTE)
        self.assertEqual([x["kind"] for x in newer],["high","low"])
        self.assertEqual(newer[1]["center_ms"],START+2*MINUTE)
        self.assertEqual(newer[1]["confirmed_ms"],START+4*MINUTE)

    def test_non_aligned_decision_refused(self):
        with self.assertRaisesRegex(ValueError,"aligned"):
            v95.independent_1m_extrema(source(),START+7*MINUTE-1)

    def test_future_requested_refused(self):
        with self.assertRaisesRegex(ValueError,"complete closed source"):
            v95.independent_1m_extrema(source(),START+8*MINUTE)

    def test_gap_and_duplicate_source_refused(self):
        x=source()
        x[3]=Minute(START+2*MINUTE,D(11),D(7))
        with self.assertRaisesRegex(ValueError,"temporal gap"):
            v95.independent_1m_extrema(x,START+7*MINUTE)

    def test_nan_and_negative_source_refused(self):
        x=source()
        x[3]=Minute(x[3].ms,D("NaN"),x[3].low)
        with self.assertRaisesRegex(ValueError,"invalid source"):
            v95.independent_1m_extrema(x,START+7*MINUTE)
        x=source()
        x[3]=Minute(x[3].ms,x[3].high,D("-5"))
        with self.assertRaisesRegex(ValueError,"invalid source"):
            v95.independent_1m_extrema(x,START+7*MINUTE)

    def test_source_attests_synthetic_terminals_not_wave(self):
        candidate,mins=synthetic_candidate()
        outcome=v95.attest_candidate(candidate,mins)
        self.assertTrue(outcome["physical_1m_primitives_verified"])
        self.assertEqual(len(outcome["leg_observations"]),5)
        self.assertFalse(outcome["independent_recursive_wave_certificate"])
        self.assertFalse(outcome["new_entry_signal"])
        self.assertFalse(outcome["paper_eligible"])
        self.assertIsNone(outcome["pnl"])

    def test_altered_stored_pivot_cannot_pass(self):
        c,mins=synthetic_candidate()
        self.assertTrue(c["v86"]["legs"][0]["all_interior_strict_pivots"])
        c["v86"]["legs"][0]["all_interior_strict_pivots"][0]["price"]="9999"
        with self.assertRaisesRegex(ValueError,"terminal witness differs"):
            v95.attest_candidate(c,mins)

    def test_favorable_point_pruning_cannot_pass(self):
        c,mins=synthetic_candidate()
        c["v86"]["legs"][0]["all_interior_strict_pivots"]=[]
        with self.assertRaisesRegex(ValueError,"terminal witness differs"):
            v95.attest_candidate(c,mins)

    def test_rewrite_of_stored_dual_high_low_abstention_refused(self):
        c,mins=synthetic_candidate()
        original=c["v86"]["global_dual_extremum_abstentions"]["dual_center_ms"]
        c["v86"]["global_dual_extremum_abstentions"]["dual_center_ms"]=[]
        if original:
            with self.assertRaisesRegex(ValueError,"global physical"):
                v95.attest_candidate(c,mins)
        else:
            c["v86"]["global_dual_extremum_abstentions"]["dual_center_ms"]=[START+MINUTE]
            with self.assertRaisesRegex(ValueError,"global physical"):
                v95.attest_candidate(c,mins)

    def test_fake_endpoint_price_refused(self):
        c,mins=synthetic_candidate()
        c["v83"]["price_vertices"][0]="50000"
        with self.assertRaisesRegex(ValueError,"endpoint price"):
            v95.attest_candidate(c,mins)

    def test_future_endpoint_confirmation_refused(self):
        c,mins=synthetic_candidate()
        c["v83"]["vertex_confirmed_ms"][0]=c["first_observable_ms"]+MINUTE
        with self.assertRaisesRegex(ValueError,"future or absent"):
            v95.attest_candidate(c,mins)

    def test_forged_paper_signal_refused(self):
        c,mins=synthetic_candidate()
        c["v86"]["entry_signal"]=True
        with self.assertRaisesRegex(ValueError,"forged entry"):
            v95.attest_candidate(c,mins)

    def test_future_child_timing_refused_by_global_replay(self):
        c,mins=synthetic_candidate()
        c["v86"]["legs"][0]["all_interior_strict_pivots"][0]["confirmed_ms"]+=MINUTE
        with self.assertRaisesRegex(ValueError,"terminal witness differs"):
            v95.attest_candidate(c,mins)

    def test_no_trade_connectors_and_source_free_ci_import(self):
        self.assertTrue(v95.RESEARCH_ONLY)
        self.assertFalse(v95.ENTRY_SIGNAL)
        self.assertFalse(v95.PAPER_ELIGIBLE)
        self.assertFalse(v95.LIVE_ENABLED)
        self.assertTrue(v95.V52_UNCHANGED)
        self.assertTrue(v95.PHYSICAL_TERMINAL_IS_NOT_FULL_RECURSION)
