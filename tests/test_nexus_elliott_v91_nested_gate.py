"""V91 synthetic nested five-three-five-three-five gate and no-entry QA."""
import copy
import unittest

from research.elliott_v91_impulse_nested_gate import nested_gate_v91 as v91

START=1709251200000
STEP=60000


def fixture(bullish=True,counts=(4,2,4,2,4)):
    centers=[START+20*i*STEP for i in range(6)]
    asof=START+120*STEP
    start_high=not bullish
    legs=[]
    for i,n in enumerate(counts):
        left_kind="high" if start_high==(i%2==0) else "low"
        next_kind="low" if left_kind=="high" else "high"
        pivots=[]
        for j in range(n):
            center=centers[i]+(j+1)*(centers[i+1]-centers[i])//(n+1)
            pivots.append({"kind":next_kind,
                           "center_ms":center,
                           "confirmed_ms":center+2*STEP})
            next_kind="high" if next_kind=="low" else "low"
        legs.append({"left_center_ms":centers[i],
                     "right_center_ms":centers[i+1],
                     "asof_ms":asof,
                     "interior_count":n,
                     "all_interior_strict_pivots":pivots,
                     "ambiguous_unordered_1m_center_ms":[]})
    return {
        "first_observable_ms":asof, "week":"B",
        "v83":{
            "first_observable_ms":asof,
            "vertex_center_ms":centers,
            "vertex_confirmed_ms":[t+4*STEP for t in centers],
            "orientation":"bullish" if bullish else "bearish",
            "motive_geometry_pass":True,
            "entry_signal":False,"paper_eligible":False,
        },
        "v86":{
            "asof_ms":asof,"per_leg_inner_counts":list(counts),
            "legs":legs,"entry_signal":False,"paper_eligible":False,
        },
    }


class V91NestedGateTests(unittest.TestCase):
    def test_bullish_complete_skeleton_still_not_full_elliott(self):
        got=v91.source_nested_anatomy(fixture())
        self.assertEqual(got["state"],
                         "NESTED_53535_SKELETON_ONLY_RECURSION_UNPROVEN")
        self.assertTrue(got["five_three_five_three_five_inner_skeleton_only"])
        self.assertFalse(got["complete_recursive_elliott_proven"])
        self.assertFalse(got["entry_signal"])
        self.assertFalse(got["paper_eligible"])

    def test_bearish_mirrored_skeleton_remains_research_only(self):
        got=v91.source_nested_anatomy(fixture(False))
        self.assertEqual(got["state"],
                         "NESTED_53535_SKELETON_ONLY_RECURSION_UNPROVEN")
        self.assertEqual(v91.research_entry_exit_gate(got)["order_admission"],"DENY")

    def test_missing_w2_internal_pivots_fails_count(self):
        got=v91.source_nested_anatomy(fixture(counts=(4,0,4,2,4)))
        self.assertEqual(got["state"],"NESTED_53535_FIXED_DEGREE_COUNT_MISMATCH")

    def test_different_degree_five_legs_not_retuned(self):
        got=v91.source_nested_anatomy(fixture(counts=(2,2,2,2,2)))
        self.assertEqual(got["expected_counts"],[4,2,4,2,4])
        self.assertFalse(got["five_three_five_three_five_inner_skeleton_only"])

    def test_outer_geometry_fails_even_if_nested_counts_match(self):
        x=fixture(); x["v83"]["motive_geometry_pass"]=False
        got=v91.source_nested_anatomy(x)
        self.assertEqual(got["state"],"ORDINARY_IMPULSE_OUTER_GEOMETRY_FAIL")

    def test_intrabar_unordered_extrema_explicit_abstain(self):
        x=fixture(); x["v86"]["legs"][0]["ambiguous_unordered_1m_center_ms"]=[
            x["v83"]["vertex_center_ms"][0]+STEP]
        got=v91.source_nested_anatomy(x)
        self.assertEqual(got["state"],"UNORDERED_OHLC_WITHIN_NESTED_LEG_ABSTAIN")
        self.assertEqual(got["intraminute_dual_extremum_count"],1)

    def test_child_confirmed_after_asof_refused(self):
        x=fixture(); x["v86"]["legs"][1]["all_interior_strict_pivots"][0][
            "confirmed_ms"]=x["first_observable_ms"]+STEP
        with self.assertRaisesRegex(ValueError,"unconfirmed"):
            v91.source_nested_anatomy(x)

    def test_child_pivot_outside_leg_refused(self):
        x=fixture(); x["v86"]["legs"][0]["all_interior_strict_pivots"][0][
            "center_ms"]=x["v83"]["vertex_center_ms"][1]
        with self.assertRaisesRegex(ValueError,"unconfirmed"):
            v91.source_nested_anatomy(x)

    def test_pivots_must_keep_source_order(self):
        x=fixture()
        pts=x["v86"]["legs"][0]["all_interior_strict_pivots"]
        pts[0],pts[1]=pts[1],pts[0]
        with self.assertRaisesRegex(ValueError,"unconfirmed"):
            v91.source_nested_anatomy(x)

    def test_extra_primitive_not_pruned_or_silently_changed(self):
        x=fixture()
        x["v86"]["per_leg_inner_counts"][0]+=1
        with self.assertRaisesRegex(ValueError,"nested source leg boundaries changed"):
            v91.source_nested_anatomy(x)

    def test_non_alternating_inner_primitives_abstain(self):
        x=fixture()
        x["v86"]["legs"][0]["all_interior_strict_pivots"][0]["kind"]="low"
        got=v91.source_nested_anatomy(x)
        self.assertEqual(got["state"],"NONALTERNATING_SOURCE_INNER_PIVOTS")

    def test_untrusted_research_entry_true_rejected(self):
        x=fixture(); x["v83"]["entry_signal"]=True
        with self.assertRaisesRegex(ValueError,"untrusted executable"):
            v91.source_nested_anatomy(x)

    def test_entry_exit_order_denied_without_real_triggers(self):
        result=v91.research_entry_exit_gate(v91.source_nested_anatomy(fixture()))
        self.assertEqual(result["order_admission"],"DENY")
        self.assertTrue(result["must_not_use_pivot_center_as_entry_time"])
        self.assertEqual(result["earliest_bar_open_after_confirmation_ms"],
                         fixture()["first_observable_ms"])
        for name in ("entry_price","protective_stop","take_profit",
                     "timeout_exit","quantity","net_pnl"):
            self.assertIsNone(result[name])
        self.assertFalse(result["new_entry_signal"])
        self.assertFalse(result["paper_eligible"])
        self.assertFalse(result["live_enabled"])
        self.assertEqual(len(result["missing_requirements"]),7)

    def test_entry_gate_refuses_manually_overridden_eligibility(self):
        structure=v91.source_nested_anatomy(fixture())
        structure["paper_eligible"]=True
        with self.assertRaisesRegex(ValueError,"unsafe executable"):
            v91.research_entry_exit_gate(structure)

    def test_v90_official_record_is_committed_and_immutable(self):
        payload=v91.sealed_v90()
        self.assertEqual(payload["schema"],
                         "nexus.elliott-v90-locked-independent-structural-replication.v1")
        self.assertEqual(len(payload["symbols"]["BTCUSDT"]["five_leg_candidate_details"]),6)
        self.assertEqual(len(payload["symbols"]["ETHUSDT"]["five_leg_candidate_details"]),2)

    def test_observed_eight_entries_all_denied(self):
        payload=v91.sealed_v90()
        states=[]
        for name in ("BTCUSDT","ETHUSDT"):
            for item in payload["symbols"][name]["five_leg_candidate_details"]:
                structure=v91.source_nested_anatomy(item)
                states.append(structure["state"])
                self.assertEqual(
                    v91.research_entry_exit_gate(structure)["order_admission"],
                    "DENY")
        self.assertEqual(len(states),8)
        self.assertEqual(states.count("ORDINARY_IMPULSE_OUTER_GEOMETRY_FAIL"),7)
        self.assertEqual(states.count("UNORDERED_OHLC_WITHIN_NESTED_LEG_ABSTAIN"),1)
