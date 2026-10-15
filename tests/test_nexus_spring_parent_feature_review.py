"""Independent synthetic-only parent Spring v12 integration tests."""
from copy import deepcopy
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

import nexus_composite_strategy_research as parent
import nexus_spring_parent_feature_review as integration
from test_nexus_causal_macro_retest_features import aggregate


def minute_spring():
    n,start=1008,256
    rows=[dict(open=106.,high=110.,low=105.,close=106.,volume=1.) for _ in range(n)]
    points={
        12:(106.,110.,100.,106.),
        20:(110.,120.,105.,110.),
        28:(100.,100.,95.,98.),
        29:(98.,99.,97.,98.),
        30:(98.,99.,97.,98.),
        31:(98.,99.,97.,98.),
        32:(98.,108.,97.,105.),
    }
    for i,v in points.items():
        rows[start+i].update(zip(("open","high","low","close"),v))
    m=pd.DataFrame(rows)
    m["timestamp"]=pd.date_range("2026-01-01T00:00:00Z",periods=n,freq="15min")
    return m


class ParentSpringIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.frames=aggregate(minute_spring())
        cls.original=parent.build_features(deepcopy(cls.frames))
        cls.combined=integration.inspect_parent_with_spring(cls.frames)

    def test_full_original_parent_is_unmodified(self):
        pd.testing.assert_frame_equal(
            self.original,self.combined[self.original.columns])
        for name in self.frames:
            pd.testing.assert_frame_equal(self.frames[name],aggregate(minute_spring())[name])

    def test_event_only_at_next_confirmed_candle(self):
        seen=np.flatnonzero(self.combined["spring_first_support_reclaim_event"])
        self.assertEqual(seen.tolist(),[288])
        self.assertEqual(self.combined.loc[288,"spring_confirmed_at"],287.)
        self.assertEqual((self.combined.loc[288,"spring_l0_index"],
                          self.combined.loc[288,"spring_l2_index"]),(268.,284.))
        self.assertFalse(self.combined.loc[:287,"lagged_spring_active"].any())
        self.assertTrue(self.combined.loc[288,"lagged_spring_active"])
        self.assertEqual(self.combined.loc[288,"spring_trigger_index"],288.)

    def test_parent_range_matches_independent_lagged_range(self):
        i=288
        self.assertAlmostEqual(
            self.combined.loc[i,"spring_decision_range"],self.combined.loc[i,"atr"])
        self.assertTrue(self.combined.loc[i,"spring_stress_cost_feasible"])
        self.assertTrue(np.isfinite(self.combined.loc[i,"spring_flat_cost"]))
        self.assertTrue(np.isfinite(self.combined.loc[i,"spring_target_net"]))

    def test_event_time_uses_closed_candle_timestamp(self):
        i=288
        raw=self.frames["minute15"].iloc[i]["timestamp"]
        decision=self.combined.loc[i,"decision_at"]
        self.assertEqual(decision,raw+pd.Timedelta(minutes=15))
        self.assertEqual(self.combined.loc[i,"timestamp"],raw)

    def test_future_15m_hourly_and_4h_tail_mutations_do_not_change_past(self):
        baseline=self.combined.iloc[:289].copy()
        altered=deepcopy(self.frames)
        cutoff=self.combined.loc[288,"decision_at"]
        for name,mins in (("minute15",15),("hour1",60),("hour4",240)):
            mask=altered[name]["timestamp"]+pd.Timedelta(minutes=mins)>cutoff
            for col in ("open","high","low","close"):
                altered[name].loc[mask,col]*=1.25
            altered[name].loc[mask,"volume"]*=4
        again=integration.inspect_parent_with_spring(altered).iloc[:289]
        pd.testing.assert_frame_equal(baseline,again)

    def test_input_frames_unchanged_after_another_inspection(self):
        frames=deepcopy(self.frames)
        _=integration.inspect_parent_with_spring(frames)
        for name in frames:
            pd.testing.assert_frame_equal(frames[name],self.frames[name])

    def test_feature_namespace_collision_fails_closed(self):
        conflict=self.original.copy()
        conflict["spring_l0"]=0.
        with patch("nexus_spring_parent_feature_review.parent.build_features",return_value=conflict):
            with self.assertRaisesRegex(ValueError,"collides"):
                integration.inspect_parent_with_spring(self.frames)

    def test_cost_projection_cannot_be_spoofed(self):
        with patch("nexus_spring_parent_feature_review.stress_cost_screen",
                   return_value={"feasible":False,"flat_cost":-1.}):
            with self.assertRaisesRegex(ValueError,"not parent-compatible"):
                integration.inspect_parent_with_spring(self.frames)

    def test_no_orders_no_factory_no_replay(self):
        self.assertTrue(integration.RESEARCH_ONLY)
        self.assertFalse(integration.LIVE_ENABLED)
        self.assertFalse(integration.DEMO_ENABLED)
        self.assertFalse(integration.FACTORY_REGISTERED)
        self.assertFalse(integration.ORDERS_ENABLED)
        self.assertNotIn("research_causal_liquidity_spring_reclaim_v12",parent.ALL_MECHANISMS)
        self.assertFalse(any(
            c.startswith("spring_") for c in self.original.columns))
        self.assertNotIn("order",self.combined.columns)
        self.assertNotIn("next_open_fill",self.combined.columns)


if __name__=="__main__":
    unittest.main(verbosity=2)
