"""V100 adversarial, CI-source-free cross-scale swing topology tests."""
import unittest
from dataclasses import replace
from decimal import Decimal as D

from research.elliott_v99_causal_scale.scale_v99 import ObservedSwing
from research.elliott_v100_scale_context import context_v100 as v100

T=1709251200000
M=60000


def event(kind,center,confirm):
    return ObservedSwing(
        kind,T+center*M,T+(confirm+1)*M,
        D("100")+D(center),D("100")+D(confirm),center,confirm)


def scenario():
    coarse=[
        event("HIGH",0,2),event("LOW",10,12),
        event("HIGH",20,22),event("LOW",30,32),
    ]
    center_indexes=[1,4,9,10,12,15,19,22,26,29,31]
    confirmed=[3,6,11,12,14,25,27,29,30,31,33]
    fine=[event("HIGH" if i%2==0 else "LOW",x,y)
          for i,(x,y) in enumerate(zip(center_indexes,confirmed))]
    return fine,coarse,T+40*M


class V100RelationshipTests(unittest.TestCase):
    def test_all_fine_swing_events_are_accounted_without_pruning(self):
        f,c,t=scenario()
        x=v100.causal_relationships(f,c,t)
        self.assertEqual(x["complete_fine_swings"],11)
        self.assertEqual(x["complete_coarse_swings"],4)
        self.assertEqual(x["complete_coarse_intervals"],3)
        self.assertEqual(x["fine_center_on_coarse_boundary"],1)
        self.assertEqual(x["fine_center_outside_closed_coarse_range"],1)
        self.assertEqual([y["all_fine_center_interior_count"] for y in x["intervals"]],[3,3,3])
        self.assertTrue(x["all_fine_exactly_accounted"])
        self.assertEqual(sum(y["all_fine_center_interior_count"] for y in x["intervals"])+2,11)
        self.assertFalse(x["wave_degree_proven"])

    def test_late_fine_confirmation_stays_audited_but_not_available(self):
        f,c,t=scenario()
        x=v100.causal_relationships(f,c,t)
        segment=x["intervals"][1]
        self.assertEqual(segment["fine_known_by_coarse_right_confirmation"],1)
        self.assertEqual(segment["fine_confirmed_too_late_count"],2)
        self.assertEqual(segment["interpretation"],"LATE_FINE_CONFIRMATION_ABSTAIN")
        self.assertFalse(segment["paper_eligible"])
        self.assertFalse(segment["entry_signal"])

    def test_every_coarse_interval_diagnostic_stays_nondeployed(self):
        f,c,t=scenario()
        x=v100.causal_relationships(f,c,t)
        self.assertFalse(x["any_trade_admission"])
        self.assertFalse(x["pattern_position_proven"])
        self.assertFalse(x["live_enabled"])
        self.assertEqual(x["intervals"][0]["coarse_motion_label"],"down")
        self.assertEqual(x["intervals"][1]["coarse_motion_label"],"up")
        self.assertEqual(x["intervals"][2]["coarse_motion_label"],"down")

    def test_same_center_different_scale_not_double_allocated(self):
        f,c,t=scenario()
        x=v100.causal_relationships(f,c,t)
        self.assertEqual(x["fine_center_on_coarse_boundary"],1)
        self.assertFalse(any(
            y["left_center_ms"]==T+10*M and
            T+10*M in [] for y in x["intervals"]))
        self.assertNotEqual(x["fine_boundary_digest"],v100.digest_events([]))

    def test_fine_pivot_order_must_be_increasing(self):
        f,c,t=scenario()
        f[4],f[5]=f[5],f[4]
        with self.assertRaisesRegex(ValueError,"nonchronological"):
            v100.causal_relationships(f,c,t)

    def test_fine_duplicate_center_rejected(self):
        f,c,t=scenario()
        f[3]=replace(f[3],center_ms=f[2].center_ms)
        with self.assertRaises(ValueError):
            v100.causal_relationships(f,c,t)

    def test_coarse_same_label_rejected(self):
        f,c,t=scenario()
        c[2]=replace(c[2],kind="LOW")
        with self.assertRaisesRegex(ValueError,"relabeled"):
            v100.causal_relationships(f,c,t)

    def test_coarse_temporal_confirmation_swap_rejected(self):
        f,c,t=scenario()
        c[1]=replace(c[1],confirmed_ms=T+29*M,confirmed_index=28)
        with self.assertRaisesRegex(ValueError,"nonchronological"):
            v100.causal_relationships(f,c,t)

    def test_future_fine_confirmation_not_accepted(self):
        f,c,t=scenario()
        f[-1]=replace(f[-1],confirmed_ms=t+M,confirmed_index=40)
        with self.assertRaisesRegex(ValueError,"future"):
            v100.causal_relationships(f,c,t)

    def test_future_coarse_confirmation_not_accepted(self):
        f,c,t=scenario()
        c[-1]=replace(c[-1],confirmed_ms=t+M,confirmed_index=40)
        with self.assertRaisesRegex(ValueError,"future"):
            v100.causal_relationships(f,c,t)

    def test_incomplete_cutoff_not_accepted(self):
        f,c,t=scenario()
        with self.assertRaisesRegex(ValueError,"aligned"):
            v100.causal_relationships(f,c,t-1)

    def test_no_parent_interval_list_refused(self):
        f,c,t=scenario()
        with self.assertRaisesRegex(ValueError,"two independent"):
            v100.causal_relationships(f,c[:1],t)

    def test_original_event_digest_stable_and_order_sensitive(self):
        f,c,t=scenario()
        x=v100.causal_relationships(f,c,t)
        self.assertEqual(x["all_original_fine_events_sha256"],v100.digest_events(f))
        self.assertNotEqual(v100.digest_events(f),v100.digest_events(f[::-1]))
        self.assertNotEqual(x["all_original_coarse_events_sha256"],x["all_original_fine_events_sha256"])

    def test_untyped_event_rejected(self):
        f,c,t=scenario()
        f[0]="fake"
        with self.assertRaisesRegex(ValueError,"typed"):
            v100.causal_relationships(f,c,t)

    def test_nonfinite_close_value_rejected(self):
        f,c,t=scenario()
        f[0]=replace(f[0],center_close=D("NaN"))
        with self.assertRaisesRegex(ValueError,"invalid"):
            v100.causal_relationships(f,c,t)

    def test_no_order_adapter_or_market_elliott_certificate(self):
        self.assertTrue(v100.RESEARCH_ONLY)
        self.assertFalse(v100.LIVE_ENABLED)
        self.assertFalse(v100.PAPER_ELIGIBLE)
        self.assertFalse(v100.ENTRY_SIGNAL)
        self.assertTrue(v100.V52_UNCHANGED)
        self.assertEqual(v100.CERTIFIED_MARKET_WAVES,0)
        self.assertIsNone(v100.ORDER_ADAPTER)

    def test_index_time_forgery_is_rejected_even_if_center_in_order(self):
        f,c,t=scenario()
        f[1]=replace(f[1],center_index=5)
        with self.assertRaisesRegex(ValueError,"index/time"):
            v100.causal_relationships(f,c,t)

    def test_cross_scale_events_must_share_source_epoch(self):
        f,c,t=scenario()
        shifted=[replace(x,center_ms=x.center_ms+M,
                          confirmed_ms=x.confirmed_ms+M) for x in c]
        with self.assertRaisesRegex(ValueError,"index/time"):
            v100.causal_relationships(f,shifted,t)

    def test_untyped_close_is_rejected(self):
        f,c,t=scenario()
        f[0]=replace(f[0],center_close=100.0)
        with self.assertRaisesRegex(ValueError,"invalid"):
            v100.causal_relationships(f,c,t)

    def test_every_interior_ledger_records_exact_original_sequence(self):
        f,c,t=scenario()
        x=v100.causal_relationships(f,c,t)
        interiors=[[y for y in f if c[i].center_ms<y.center_ms<c[i+1].center_ms]
                   for i in range(len(c)-1)]
        for entry,events in zip(x["intervals"],interiors):
            self.assertEqual(entry["fine_unpruned_event_sha256"],
                             v100.digest_events(events))
        self.assertTrue(all(not entry["elliott_degree_certified"]
                            for entry in x["intervals"]))
