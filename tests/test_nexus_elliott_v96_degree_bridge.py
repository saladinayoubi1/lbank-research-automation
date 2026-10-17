"""V96 degree bridge regression with fully synthetic wave endpoints only.

The passing synthetic tree is NEVER proof of market Elliott authenticity.
Network and original physical July archives are not needed for CI.
"""
import copy
import unittest
from unittest.mock import patch

from research.elliott_v96_degree_bridge import bridge_v96 as v96

T=1709251200000
M=60000


def fixture(orientation="bullish"):
    centers=[T+i*20*M for i in range(6)]
    asof=centers[-1]+5*M
    legs=[]
    all_counts=[]
    for i,needed in enumerate(v96.EXPECTED_1M_COUNTS):
        up=((orientation=="bullish")== (i%2==0))
        initial_kind="high" if up else "low"
        opposite="low" if up else "high"
        points=[]
        for j in range(needed):
            t=centers[i]+(j+1)*2*M
            points.append({
                "center_ms":t,
                "confirmed_ms":t+2*M,
                "kind":initial_kind if j%2==0 else opposite,
                "price":str(102+j),
                "source_minute_index":i*20+j*2,
            })
        legs.append({
            "left_center_ms":centers[i],
            "right_center_ms":centers[i+1],
            "asof_ms":asof,
            "all_interior_strict_pivots":points,
            "ambiguous_unordered_1m_center_ms":[],
            "interior_count":needed,
        })
        all_counts.append(needed)
    return {
        "week":"B",
        "first_observable_ms":asof,
        "v83":{
            "orientation":orientation,
            "first_observable_ms":asof,
            "vertex_center_ms":centers,
            "vertex_confirmed_ms":[t+3*M for t in centers],
            "motive_geometry_pass":True,
        },
        "v86":{
            "asof_ms":asof,
            "legs":legs,
            "per_leg_inner_counts":all_counts,
        },
    }


def with_synthetic_source_attestation(candidate):
    # This isolated grammar test deliberately replaces market verification.
    # It must never claim source authenticity or enable paper trading.
    with patch.object(v96.v95,"attest_candidate",return_value={
        "physical_1m_primitives_verified":True,
        "new_entry_signal":False,
    }):
        return v96.bridge_attested_candidate(candidate,[])


class V96FixedDegreeBridgeTests(unittest.TestCase):
    def test_bullish_synthetic_full_shape_never_trades(self):
        outcome=with_synthetic_source_attestation(fixture())
        self.assertTrue(outcome["necessary_fixed_degree_53535_shape_pass"])
        self.assertEqual(outcome["hard_blockers"],[])
        self.assertEqual(outcome["v93_syntactic_graph_result"]["status"],
                         "SYNTACTIC_RECURSIVE_SHAPE_ONLY")
        self.assertFalse(outcome["v93_syntactic_graph_result"]["independently_proven_market_wave"])
        self.assertFalse(outcome["higher_degree_recursive_market_proof"])
        self.assertFalse(outcome["paper_eligible"])
        self.assertFalse(outcome["entry_signal"])

    def test_bearish_synthetic_mirrored_shape(self):
        outcome=with_synthetic_source_attestation(fixture("bearish"))
        self.assertTrue(outcome["necessary_fixed_degree_53535_shape_pass"])
        self.assertFalse(outcome["live_enabled"])

    def test_one_missing_primitive_not_silently_inferred(self):
        x=fixture()
        x["v86"]["legs"][2]["all_interior_strict_pivots"].pop()
        x["v86"]["per_leg_inner_counts"][2]-=1
        got=with_synthetic_source_attestation(x)
        self.assertFalse(got["necessary_fixed_degree_53535_shape_pass"])
        self.assertTrue(any("LEG3_STRICT_UNPRUNED" in r for r in got["hard_blockers"]))
        self.assertIsNone(got["v93_syntactic_graph_result"])

    def test_extra_favorable_pivot_rejected_not_pruned(self):
        x=fixture()
        x["v86"]["legs"][1]["all_interior_strict_pivots"].insert(
            1,{"kind":"low","center_ms":T+24*M,"confirmed_ms":T+26*M})
        got=with_synthetic_source_attestation(x)
        self.assertTrue(any("LEG2_STRICT_UNPRUNED" in r for r in got["hard_blockers"]))

    def test_ambiguous_same_minute_abstains(self):
        x=fixture()
        x["v86"]["legs"][4]["ambiguous_unordered_1m_center_ms"]=[T+81*M]
        got=with_synthetic_source_attestation(x)
        self.assertTrue(any("INTRA_MINUTE_HIGH_LOW_ORDER_UNKNOWN" in r
                            for r in got["hard_blockers"]))
        self.assertFalse(got["necessary_fixed_degree_53535_shape_pass"])

    def test_wrong_pivot_kind_cannot_pass(self):
        x=fixture()
        x["v86"]["legs"][0]["all_interior_strict_pivots"][0]["kind"]="low"
        got=with_synthetic_source_attestation(x)
        self.assertTrue(any("NONALTERNATING_TERMINAL_POLARITY" in r
                            for r in got["hard_blockers"]))

    def test_future_confirmed_pivot_rejected(self):
        x=fixture()
        x["v86"]["legs"][1]["all_interior_strict_pivots"][0]["confirmed_ms"]=(
            x["first_observable_ms"]+M)
        got=with_synthetic_source_attestation(x)
        self.assertTrue(any("FUTURE_OR_INVALID_TERMINAL_CONFIRMATION" in r
                            for r in got["hard_blockers"]))

    def test_nonmonotonic_inner_vertices_rejected(self):
        x=fixture()
        pts=x["v86"]["legs"][0]["all_interior_strict_pivots"]
        pts[0],pts[1]=pts[1],pts[0]
        got=with_synthetic_source_attestation(x)
        self.assertTrue(any("TERMINAL_NONMONOTONIC_OR_OVERLAPPING" in r
                            for r in got["hard_blockers"]))

    def test_failed_outer_geometry_vetoes_clean_primitive_graph(self):
        x=fixture()
        x["v83"]["motive_geometry_pass"]=False
        got=with_synthetic_source_attestation(x)
        self.assertEqual(got["hard_blockers"],[
            "V83_CONVENTIONAL_OUTER_IMPULSE_HARD_GEOMETRY_FAIL"
        ])
        self.assertFalse(got["necessary_fixed_degree_53535_shape_pass"])

    def test_missing_source_attestation_refused(self):
        with patch.object(v96.v95,"attest_candidate",return_value={
            "physical_1m_primitives_verified":False,
            "new_entry_signal":False,
        }):
            with self.assertRaisesRegex(ValueError,"not source-attested"):
                v96.bridge_attested_candidate(fixture(),[])

    def test_unexpected_entry_source_attestation_refused(self):
        with patch.object(v96.v95,"attest_candidate",return_value={
            "physical_1m_primitives_verified":True,
            "new_entry_signal":True,
        }):
            with self.assertRaisesRegex(ValueError,"not source-attested"):
                v96.bridge_attested_candidate(fixture(),[])

    def test_safety_constants_and_full_required_counts(self):
        self.assertEqual(v96.EXPECTED_1M_COUNTS,(4,2,4,2,4))
        self.assertTrue(v96.RESEARCH_ONLY)
        self.assertFalse(v96.PAPER_ELIGIBLE)
        self.assertFalse(v96.LIVE_ENABLED)
        self.assertFalse(v96.ENTRY_SIGNAL)
        self.assertTrue(v96.V52_UNCHANGED)
        self.assertIsNone(v96.ORDER_ADAPTER)
