"""V97 family geometries: physically backed synthetic fixtures, no markets."""
import unittest
from decimal import Decimal as D

from research.elliott_v82_causal_degree_observer.observer_v82 import Minute
from research.elliott_v97_family_geometry import family_v97 as v97

T=1709251200000
M=60000


def fixture(levels):
    """Monotone per-leg physical source; exactly observed vertex wick."""
    values=[D(str(x)) for x in levels]
    timeline=[]
    verts=[]
    for i,(left,right) in enumerate(zip(values,values[1:])):
        for k in range(10):
            timeline.append(left+(right-left)*D(k)/D(10))
    timeline.extend((values[-1],values[-1],values[-1]))
    minutes=[Minute(T+i*M,p,p) for i,p in enumerate(timeline)]
    for i,p in enumerate(values):
        kind="low" if i%2==0 else "high"
        if values[1]<values[0]:
            kind="high" if i%2==0 else "low"
        verts.append(v97.PhysicalVertex(kind,T+i*10*M,T+(i*10+1)*M,p))
    return tuple(verts),minutes,T+len(minutes)*M


def diagnostic(family,levels):
    v,m,t=fixture(levels)
    return v97.evaluate(family,v,m,t)


class Family97Tests(unittest.TestCase):
    def test_clean_impulse_is_still_syntactic_only(self):
        x=diagnostic("IMPULSE",[100,110,105,125,115,135])
        self.assertTrue(x["restricted_geometry_pass"])
        self.assertFalse(x["wave_degree_or_recursive_elliott_proven"])
        self.assertFalse(x["paper_eligible"])
        self.assertFalse(x["entry_signal"])
        self.assertIsNone(x["net_pnl"])

    def test_mirrored_bearish_impulse_syntactic_only(self):
        x=diagnostic("IMPULSE",[200,190,195,178,188,170])
        self.assertTrue(x["restricted_geometry_pass"])
        self.assertFalse(x["live_enabled"])

    def test_wave2_origin_breach(self):
        x=diagnostic("IMPULSE",[100,110,99,126,115,136])
        self.assertIn("WAVE2_INVALID_ORIGIN_BREACH",x["rejections"])

    def test_wave3_is_shortest(self):
        x=diagnostic("IMPULSE",[100,115,110,121,118,137])
        self.assertIn("WAVE3_IS_SHORTEST",x["rejections"])

    def test_wave4_overlap_non_diagonal(self):
        x=diagnostic("IMPULSE",[100,110,105,125,109,135])
        self.assertIn("WAVE4_OVERLAP_NONDIAGONAL",x["rejections"])

    def test_truncated_wave5_excluded_in_restricted_subset(self):
        x=diagnostic("IMPULSE",[100,110,105,125,114,123])
        self.assertIn("WAVE5_NOT_NEW_EXTREME_RESTRICTED_SUBSET",x["rejections"])

    def test_zigzag_no_B_origin_breach_subset(self):
        x=diagnostic("ZIGZAG",[100,110,106,120])
        self.assertTrue(x["restricted_geometry_pass"])
        self.assertFalse(x["pattern_position_proven"])

    def test_zigzag_B_breaches_origin_reject(self):
        x=diagnostic("ZIGZAG",[100,110,99,120])
        self.assertIn("ZIGZAG_B_AT_OR_PAST_A_ORIGIN",x["rejections"])

    def test_zigzag_C_must_exceed_A_end_restricted(self):
        x=diagnostic("ZIGZAG",[100,110,106,108])
        self.assertIn("ZIGZAG_C_NOT_BEYOND_A_END_RESTRICTED_SUBSET",x["rejections"])

    def test_flat_B_retracement_ninety_percent(self):
        x=diagnostic("FLAT",[100,110,100.5,121])
        self.assertTrue(x["restricted_geometry_pass"])
        self.assertFalse(x["wave_degree_or_recursive_elliott_proven"])

    def test_flat_shallow_B_reject(self):
        x=diagnostic("FLAT",[100,110,106,120])
        self.assertIn("FLAT_B_RETRACE_LESS_THAN_90_PERCENT",x["rejections"])

    def test_flat_C_not_beyond_A_reject(self):
        x=diagnostic("FLAT",[100,110,100.5,109])
        self.assertIn("FLAT_C_NOT_BEYOND_A_END_RESTRICTED_SUBSET",x["rejections"])

    def test_families_can_both_pass_ambiguous_no_automatic_choice(self):
        v,m,t=fixture([100,110,100.5,121])
        a=v97.evaluate("ZIGZAG",v,m,t)
        b=v97.evaluate("FLAT",v,m,t)
        self.assertTrue(a["restricted_geometry_pass"])
        self.assertTrue(b["restricted_geometry_pass"])
        self.assertFalse(a["entry_signal"])
        self.assertFalse(b["entry_signal"])

    def test_vertex_unbacked_price_rejected(self):
        v,m,t=fixture([100,110,105,125,115,135])
        s=list(v)
        s[1]=v97.PhysicalVertex("high",s[1].center_ms,s[1].confirmed_ms,D(111))
        with self.assertRaisesRegex(ValueError,"not backed"):
            v97.evaluate("IMPULSE",tuple(s),m,t)

    def test_future_confirmation_rejected(self):
        v,m,t=fixture([100,110,106,120])
        s=list(v)
        s[0]=v97.PhysicalVertex("low",s[0].center_ms,t+M,s[0].price)
        with self.assertRaisesRegex(ValueError,"unconfirmed"):
            v97.evaluate("ZIGZAG",tuple(s),m,t)

    def test_future_bar_does_not_change_closed_result(self):
        v,m,t=fixture([100,110,106,120])
        older=v97.evaluate("ZIGZAG",v,m,t)
        future=[Minute(t,D(999),D(1))]
        self.assertEqual(older,v97.evaluate("ZIGZAG",v,m+future,t))

    def test_gapped_source_rejected(self):
        v,m,t=fixture([100,110,106,120])
        m[3]=Minute(m[2].ms,m[3].high,m[3].low)
        with self.assertRaises(ValueError):
            v97.evaluate("ZIGZAG",v,m,t)

    def test_wick_envelope_violation_rejected(self):
        v,m,t=fixture([100,110,106,120])
        q=m[4]
        m[4]=Minute(q.ms,D(115),q.low)
        x=v97.evaluate("ZIGZAG",v,m,t)
        self.assertIn("LEG1_WICK_HIGH_BEYOND_END",x["rejections"])

    def test_non_alternating_vertex_kind_rejected(self):
        v,m,t=fixture([100,110,106,120])
        s=list(v)
        s[2]=v97.PhysicalVertex("high",s[2].center_ms,s[2].confirmed_ms,s[2].price)
        with self.assertRaises(ValueError):
            v97.evaluate("ZIGZAG",tuple(s),m,t)

    def test_unknown_family_fails_closed(self):
        v,m,t=fixture([100,110,106,120])
        with self.assertRaisesRegex(ValueError,"unknown"):
            v97.evaluate("TRIANGLE",v,m,t)

    def test_no_connector_and_no_live(self):
        self.assertIsNone(v97.ORDER_CONNECTOR)
        self.assertTrue(v97.RESEARCH_ONLY)
        self.assertFalse(v97.LIVE_ENABLED)
        self.assertFalse(v97.PAPER_ELIGIBLE)
        self.assertTrue(v97.V52_UNCHANGED)
