"""Synthetic causal spring-reclaim tests, no Bybit archive or market producer."""
import unittest
from unittest.mock import patch
import numpy as np
import pandas as pd

from nexus_causal_liquidity_spring_features import (
    build_closed_spring_features,_path_error,
    RESEARCH_ONLY,LIVE_ENABLED,PAPER_ENABLED,AUTO_DEMO,FACTORY_REGISTERED,
)
from nexus_causal_liquidity_spring_review import ConfirmedSpringPivot


def make_frame(n=60):
    rows=[dict(open=106.,high=110.,low=105.,close=106.) for _ in range(n)]
    if n>12: rows[12]=dict(open=106.,high=110.,low=100.,close=106.)
    if n>20: rows[20]=dict(open=110.,high=120.,low=105.,close=110.)
    if n>28: rows[28]=dict(open=100.,high=100.,low=95.,close=98.)
    for i in (29,30,31):
        if n>i: rows[i]=dict(open=98.,high=99.,low=97.,close=98.)
    if n>32: rows[32]=dict(open=98.,high=108.,low=97.,close=105.)
    frame=pd.DataFrame(rows)
    frame["timestamp"]=pd.date_range("2026-01-01T00:15:00Z",periods=n,freq="15min")
    return frame


def features(frame,diagnostics=None,asof=None):
    return build_closed_spring_features(
        frame,last_completed_at=frame["timestamp"].iloc[-1] if asof is None else asof,
        diagnostics=diagnostics)


def fixed_pattern():
    return (
        ConfirmedSpringPivot("low",12,15,100.),
        ConfirmedSpringPivot("high",20,23,120.),
        ConfirmedSpringPivot("low",28,31,95.),
    )


class SpringStreamingSyntheticTests(unittest.TestCase):
    def test_causal_first_reclaim_only_at_index32(self):
        r=features(make_frame())
        self.assertEqual(np.flatnonzero(r["spring_first_support_reclaim_event"]).tolist(),[32])
        self.assertTrue(r["lagged_spring_active"].iloc[32])
        self.assertTrue(r["spring_stress_cost_feasible"].iloc[32])
        self.assertEqual(r["spring_l0_index"].iloc[32],12)
        self.assertEqual(r["spring_l2_index"].iloc[32],28)
        self.assertEqual(r["spring_trigger_index"].iloc[32],32.)

    def test_setup_has_exact_three_right_confirmations(self):
        messages=[]
        r=features(make_frame(),messages)
        stored=[v for v in messages if v["action"]=="setup_stored_for_next_bar"]
        self.assertEqual(len(stored),1)
        self.assertEqual(stored[0]["decision_index"],31)
        self.assertEqual(stored[0]["earliest_decision_index"],32)
        self.assertFalse(r["lagged_spring_active"].iloc[:32].any())

    def test_prefix_without_confirmation_has_no_event(self):
        r=features(make_frame(31))
        self.assertFalse(r["spring_first_support_reclaim_event"].any())

    def test_prefix_with_confirmation_without_next_bar_has_no_event(self):
        r=features(make_frame(32))
        self.assertFalse(r["spring_first_support_reclaim_event"].any())

    def test_future_tail_cannot_change_existing_decisions(self):
        a=make_frame(45)
        b=make_frame(66)
        b.loc[58,["open","high","low","close"]]=[200.,220.,180.,190.]
        first=features(a)
        other=features(b)
        for name,value in first.items():
            with self.subTest(column=name):
                np.testing.assert_array_equal(value.to_numpy(),
                                              other[name].iloc[:len(a)].to_numpy())

    def test_event_consumed_even_when_cost_gate_denies(self):
        f=make_frame()
        f.loc[33,["open","high","low","close"]]=[98.,99.,97.,98.]
        f.loc[34,["open","high","low","close"]]=[98.,108.,97.,105.]
        with patch("nexus_causal_liquidity_spring_features.stress_cost_screen",
                   return_value={"feasible":False,"flat_cost":200.,"target_net":-4.}):
            r=features(f)
        self.assertEqual(np.flatnonzero(r["spring_first_support_reclaim_event"]).tolist(),[32])
        self.assertFalse(r["spring_stress_cost_feasible"].iloc[32])

    def test_same_bar_low_breach_overrides_reclaim(self):
        f=make_frame()
        f.loc[32,"low"]=94.
        r=features(f)
        self.assertTrue(r["spring_invalidated"].iloc[32])
        self.assertFalse(r["spring_first_support_reclaim_event"].iloc[32])

    def test_h1_high_overshoot_overrides_reclaim(self):
        f=make_frame()
        f.loc[32,"high"]=121.
        r=features(f)
        self.assertTrue(r["spring_invalidated"].iloc[32])
        self.assertFalse(r["spring_first_support_reclaim_event"].iloc[32])

    def test_expire_at_confirmation_age_17(self):
        f=make_frame(62)
        f.loc[32:49,["open","high","low","close"]]=[98.,99.,97.,98.]
        r=features(f)
        self.assertFalse(r["spring_first_support_reclaim_event"].any())
        self.assertTrue(r["spring_expired"].iloc[48])

    def test_reclaim_before_center_confirm_is_ineligible(self):
        f=make_frame()
        f.loc[30,["open","high","low","close"]]=[98.,105.,97.,102.]
        r=features(f)
        self.assertFalse(r["spring_first_support_reclaim_event"].any())
        self.assertTrue(r["spring_path_rejected"].iloc[31])

    def test_equal_low_neighbor_rejects_L0(self):
        f=make_frame()
        f.loc[11,"low"]=100.
        self.assertFalse(features(f)["spring_first_support_reclaim_event"].any())

    def test_dual_extrema_L2_bar_rejects_pivot(self):
        f=make_frame()
        f.loc[28,"high"]=121.
        self.assertFalse(features(f)["spring_first_support_reclaim_event"].any())

    def test_bad_h1_to_l2_path_explicit(self):
        f=make_frame()
        f.loc[25,"high"]=121.
        self.assertEqual(_path_error(fixed_pattern(),
            f["high"].to_numpy(),f["low"].to_numpy(),
            f["close"].to_numpy(),31),"resistance_exceeded_before_L2")

    def test_bad_l0_to_h1_path_explicit(self):
        f=make_frame()
        f.loc[17,"low"]=99.
        self.assertEqual(_path_error(fixed_pattern(),
            f["high"].to_numpy(),f["low"].to_numpy(),
            f["close"].to_numpy(),31),"old_support_broken_before_H1")

    def test_current_partial_candle_is_not_allowed(self):
        f=make_frame()
        with self.assertRaises(ValueError):features(f,asof=f["timestamp"].iloc[-2])

    def test_unaligned_missing_bar_is_rejected(self):
        f=make_frame()
        f.loc[22:,"timestamp"]+=pd.Timedelta(minutes=15)
        with self.assertRaises(ValueError):features(f)

    def test_naive_timestamp_is_rejected(self):
        f=make_frame()
        f["timestamp"]=f["timestamp"].dt.tz_localize(None)
        with self.assertRaises(ValueError):features(f)

    def test_invalid_OHLC_rejected(self):
        f=make_frame()
        f.loc[27,"high"]=104.
        with self.assertRaises(ValueError):features(f)

    def test_side_effects_never_exposed(self):
        self.assertTrue(RESEARCH_ONLY)
        self.assertFalse(LIVE_ENABLED)
        self.assertFalse(PAPER_ENABLED)
        self.assertFalse(AUTO_DEMO)
        self.assertFalse(FACTORY_REGISTERED)
        r=features(make_frame())
        self.assertNotIn("order",r)
        self.assertNotIn("next_open_fill",r)


if __name__=="__main__":
    unittest.main(verbosity=2)
