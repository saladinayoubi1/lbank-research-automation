"""V98 synthetic A-B-C subwave grammar; no source or profit claims."""
import copy
import unittest
from decimal import Decimal as D

from research.elliott_v82_causal_degree_observer.observer_v82 import Minute, Witness
from research.elliott_v87_correction_witness.correction_v87 import assess_correction
from research.elliott_v95_physical_witness import witness_v95 as v95
from research.elliott_v97_family_geometry import family_v97 as v97
from research.elliott_v98_correction_inner import inner_v98 as v98

BASE=1709251200000
MIN=60000


def scenario(parts):
    # parts contain one complete polyline per A/B/C constituent. Exactly
    # aligned 4-minute interior vertex spacings. No artificial pivot thinning.
    values=[D(str(parts[0][0]))]
    indices=[0]
    for part in parts:
        if D(str(part[0]))!=values[-1]:
            raise ValueError("disconnected synthetic ABC fixture")
        for left,right in zip(part,part[1:]):
            a,b=D(str(left)),D(str(right))
            for k in range(1,5):
                values.append(a+(b-a)*D(k)/D(4))
        indices.append(len(values)-1)
    values.extend([values[-1],values[-1]])
    minutes=[Minute(BASE+i*MIN,price,price) for i,price in enumerate(values)]
    ends=[]
    for i,j in enumerate(indices):
        if i==0:
            kind="low" if parts[0][1]>parts[0][0] else "high"
        else:
            kind="high" if ends[-1].kind=="low" else "low"
        ends.append(Witness(
            kind,BASE+j*MIN,j,BASE+(j+1)*MIN,str(values[j]),
            "SYNTHETIC_ONLY"))
    asof=BASE+len(minutes)*MIN
    old=assess_correction(ends,minutes,asof)
    locked={"first_observable_ms":asof,"original_V82_candidate_type":"CORRECTION",
            "families_diagnosed":{
                name:v97.evaluate(name,tuple(v97.witness_vertex(x) for x in ends),
                                  minutes,asof)
                for name in ("ZIGZAG","FLAT")}}
    return ends,minutes,asof,old,locked


def zigzag_fixture():
    return scenario([
        [100,110,105,125,115,135],
        [135,125,130,120],
        [120,135,130,145,140,155],
    ])


def flat_fixture():
    return scenario([
        [100,106,103,110],
        [110,102,106,100.5],
        [100.5,112,108,118,114,121],
    ])


class V98SyntheticABCValidationTests(unittest.TestCase):
    def test_zigzag_535_lower_wave_shape_but_no_market_proof(self):
        a,m,t,old,locked=zigzag_fixture()
        x=v98.check_correction_candidate(a,m,t,old,locked)
        z=x["independent_ABC_motive_and_correction_geometry"]["ZIGZAG"]
        self.assertEqual(old["inner_counts_ABC"],[4,2,4])
        self.assertTrue(z["necessary_fixed_degree_family_diagnostics_pass"])
        self.assertFalse(x["full_recursive_elliott_certified"])
        self.assertFalse(x["new_entry_signal"])
        self.assertFalse(x["paper_eligible"])

    def test_flat_335_lower_wave_shape_but_no_market_proof(self):
        a,m,t,old,locked=flat_fixture()
        x=v98.check_correction_candidate(a,m,t,old,locked)
        f=x["independent_ABC_motive_and_correction_geometry"]["FLAT"]
        self.assertEqual(old["inner_counts_ABC"],[2,2,4])
        self.assertTrue(f["necessary_fixed_degree_family_diagnostics_pass"])
        self.assertFalse(x["pattern_position_proven"])
        self.assertFalse(x["live_enabled"])

    def test_missing_one_inside_A_refused(self):
        a,m,t,old,locked=zigzag_fixture()
        bad=copy.deepcopy(old)
        bad["observed_inner_pivots_all_legs"][0]["all_interior_pivots"].pop()
        with self.assertRaisesRegex(ValueError,"primitive material differs"):
            v98.check_correction_candidate(a,m,t,bad,locked)

    def test_missing_one_inside_C_refused(self):
        a,m,t,old,locked=zigzag_fixture()
        bad=copy.deepcopy(old)
        bad["observed_inner_pivots_all_legs"][2]["observed_interior_count"]-=1
        with self.assertRaisesRegex(ValueError,"primitive material differs"):
            v98.check_correction_candidate(a,m,t,bad,locked)

    def test_changed_parent_center_refused(self):
        a,m,t,old,locked=zigzag_fixture()
        bad=copy.deepcopy(old);bad["outer_vertex_centers_ms"][1]+=MIN
        with self.assertRaisesRegex(ValueError,"vertex timing changed"):
            v98.check_correction_candidate(a,m,t,bad,locked)

    def test_future_at_right_confirmation_rejected(self):
        a,m,t,old,locked=zigzag_fixture()
        moved=copy.deepcopy(old)
        moved["observed_inner_pivots_all_legs"][0]["all_interior_pivots"][0]["confirmed_ms"]=t+MIN
        with self.assertRaisesRegex(ValueError,"primitive material differs"):
            v98.check_correction_candidate(a,m,t,moved,locked)

    def test_flip_source_makes_stored_pivots_fail(self):
        a,m,t,old,locked=zigzag_fixture()
        q=m[4]
        m[4]=Minute(q.ms,q.high+D(1),q.low+D(1))
        with self.assertRaises(ValueError):
            v98.check_correction_candidate(a,m,t,old,locked)

    def test_frozen_family_assessment_cannot_admit_order(self):
        a,m,t,old,locked=flat_fixture()
        x=v98.check_correction_candidate(a,m,t,old,locked)
        for result in x["independent_ABC_motive_and_correction_geometry"].values():
            self.assertFalse(result["actual_recursive_wave_certificate"])
            self.assertFalse(result["paper_eligible"])
            self.assertFalse(result["entry_signal"])

    def test_no_future_tail_candle_could_influence_decision(self):
        a,m,t,old,locked=zigzag_fixture()
        x=v98.check_correction_candidate(a,m,t,old,locked)
        tail=[Minute(t,D("99999"),D("0.1"))]
        after=v98.check_correction_candidate(a,m+tail,t,old,locked)
        self.assertEqual(after,x)

    def test_source_gap_refuses_stale_or_missing_bars(self):
        a,m,t,old,locked=zigzag_fixture()
        q=m[8]
        m[8]=Minute(q.ms-MIN,q.high,q.low)
        with self.assertRaisesRegex(ValueError,"temporal gap"):
            v98.check_correction_candidate(a,m,t,old,locked)

    def test_forged_original_order_eligibility_is_refused(self):
        a,m,t,old,locked=zigzag_fixture()
        bad=copy.deepcopy(old);bad["entry_signal"]=True
        with self.assertRaisesRegex(ValueError,"upstream ABC admission"):
            v98.check_correction_candidate(a,m,t,bad,locked)

    def test_mismatched_v97_family_source_type_is_refused(self):
        a,m,t,old,locked=zigzag_fixture()
        bad=copy.deepcopy(locked);bad["original_V82_candidate_type"]="IMPULSE"
        with self.assertRaisesRegex(ValueError,"upstream ABC admission"):
            v98.check_correction_candidate(a,m,t,old,bad)

    def test_changed_original_frozen_primitive_count_is_refused(self):
        a,m,t,old,locked=zigzag_fixture()
        bad=copy.deepcopy(old);bad["inner_counts_ABC"][2]-=1
        with self.assertRaisesRegex(ValueError,"counts or ambiguity ledger"):
            v98.check_correction_candidate(a,m,t,bad,locked)

    def test_changed_ambiguous_bar_ledger_is_refused(self):
        a,m,t,old,locked=zigzag_fixture()
        bad=copy.deepcopy(old);bad["ambiguous_dual_extrema_centers_ms"]=[BASE+MIN]
        with self.assertRaisesRegex(ValueError,"counts or ambiguity ledger"):
            v98.check_correction_candidate(a,m,t,bad,locked)

    def test_replay_rejects_physically_changed_endpoint_price(self):
        a,m,t,old,locked=zigzag_fixture()
        q=a[0]
        a[0]=Witness(q.kind,q.center_ms,q.source_minute_index,q.confirmed_ms,"9999",q.degree)
        with self.assertRaisesRegex(ValueError,"not backed"):
            v98.check_correction_candidate(a,m,t,old,locked)

    def test_double_extremum_ambiguity_refuses_inner_leg(self):
        a,m,t,old,locked=zigzag_fixture()
        strict,dual=v95.independent_1m_extrema(m,t)
        # Artificially inject a dual-extremum index, verifying fail-closed
        # primitive acceptance independently of historical V87 receipts.
        x=v98.physical_1m_lower_leg(a[0],a[1],strict,
             [BASE+7*MIN],m,t,"MOTIVE",4)
        self.assertFalse(x["necessary_shape_and_geometry_pass"])
        self.assertIn("INTRA_1M_HIGH_LOW_ORDER_UNKNOWN",x["degree_geometry_reject_reasons"])

    def test_no_family_relabeling_automatically_fixes_missing_count(self):
        a,m,t,old,locked=flat_fixture()
        outcome=v98.check_correction_candidate(a,m,t,old,locked)
        self.assertFalse(outcome["independent_ABC_motive_and_correction_geometry"]
                         ["ZIGZAG"]["necessary_fixed_degree_family_diagnostics_pass"])
        self.assertTrue(outcome["independent_ABC_motive_and_correction_geometry"]
                        ["FLAT"]["necessary_fixed_degree_family_diagnostics_pass"])
        self.assertFalse(outcome["full_recursive_elliott_certified"])

    def test_source_refuses_nonfinite_bar(self):
        a,m,t,old,locked=zigzag_fixture()
        q=m[7];m[7]=Minute(q.ms,D("NaN"),q.low)
        with self.assertRaises(ValueError):
            v98.check_correction_candidate(a,m,t,old,locked)

    def test_fixed_family_counts_and_no_order_path(self):
        self.assertEqual(v98.ZIGZAG_535,(4,2,4))
        self.assertEqual(v98.FLAT_335,(2,2,4))
        self.assertTrue(v98.RESEARCH_ONLY)
        self.assertFalse(v98.ENTRY_SIGNAL)
        self.assertFalse(v98.PAPER_ELIGIBLE)
        self.assertFalse(v98.LIVE_ENABLED)
        self.assertTrue(v98.V52_UNCHANGED)
        self.assertIsNone(v98.ORDER_ADAPTER)
