"""Causal, completed OHLC synthetic tests: no market producer or trading."""
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

from nexus_causal_abc_corrective_features import (
    build_closed_abc_features, _path_error, RESEARCH_ONLY, LIVE_ENABLED, AUTO_DEMO, FACTORY_REGISTERED,
)
from nexus_causal_abc_corrective_review import ConfirmedABCPivot


def make_frames(total=48):
    t=pd.date_range("2026-01-01T00:15:00Z",periods=total,freq="15min")
    rows=[dict(open=106.,high=107.,low=105.,close=106.) for _ in range(total)]
    if total > 12: rows[12]=dict(open=110.,high=120.,low=105.,close=110.)
    if total > 20: rows[20]=dict(open=104.,high=106.,low=100.,close=104.)
    if total > 28: rows[28]=dict(open=106.,high=110.,low=105.,close=106.)
    if total > 36: rows[36]=dict(open=98.,high=100.,low=95.,close=98.)
    if total > 40: rows[40]=dict(open=106.,high=113.,low=105.,close=112.)
    f=pd.DataFrame(rows);f["timestamp"]=t
    return f


def make_features(frame,diagnostics=None,cutoff=None):
    return build_closed_abc_features(frame,last_completed_at=frame["timestamp"].iloc[-1] if cutoff is None else cutoff,
                                     diagnostics=diagnostics)


def confirmed_abc():
    return (ConfirmedABCPivot("high",12,15,120.),
            ConfirmedABCPivot("low",20,23,100.),
            ConfirmedABCPivot("high",28,31,110.),
            ConfirmedABCPivot("low",36,39,95.))


class TestCausalABC(unittest.TestCase):
    def test_first_event_only_at_closed_index_40(self):
        f=make_frames()
        out=make_features(f)
        found=np.flatnonzero(out["abc_first_close_break_event"].to_numpy())
        self.assertEqual(found.tolist(),[40])
        self.assertTrue(out["lagged_abc_active"].iloc[40])
        self.assertTrue(out["abc_stress_cost_feasible"].iloc[40])
        self.assertEqual(out["abc_trigger_index"].iloc[40],40.)

    def test_no_event_before_confirmation_or_before_next_bar(self):
        f=make_frames(40)
        out=make_features(f)
        self.assertFalse(out["abc_first_close_break_event"].any())
        self.assertFalse(out["lagged_abc_active"].iloc[39])
        self.assertFalse(out["lagged_abc_active"].iloc[:39].any())

    def test_stored_pivot_is_ready_only_after_three_right_bars(self):
        f=make_frames()
        events=[]
        make_features(f,events)
        stored=[e for e in events if e["action"]=="setup_stored_for_next_bar"]
        self.assertEqual(len(stored),1)
        self.assertEqual(stored[0]["decision_index"],39)
        self.assertEqual(stored[0]["earliest_decision_index"],40)

    def test_prefix_tail_future_independence(self):
        full=make_frames(70)
        a=make_features(full.iloc[:42].copy())
        future=full.copy()
        future.loc[60,"high"]=190.
        future.loc[60,"close"]=180.
        b=make_features(future)
        for name,series in a.items():
            np.testing.assert_array_equal(series.to_numpy(),b[name].iloc[:42].to_numpy())

    def test_exclude_incomplete_candle(self):
        f=make_frames()
        with self.assertRaises(ValueError):
            make_features(f,cutoff=f["timestamp"].iloc[-2])

    def test_current_candle_cannot_retroactively_create_pivot(self):
        f=make_frames()
        out=make_features(f.iloc[:39].copy())
        self.assertFalse(out["lagged_abc_active"].any())
        self.assertFalse(out["abc_first_close_break_event"].any())

    def test_consume_identity_when_cost_denied(self):
        f=make_frames(57)
        f.loc[41,["open","high","low","close"]]=[106.,107.,105.,106.]
        f.loc[42,["open","high","low","close"]]=[106.,113.,105.,112.]
        with patch("nexus_causal_abc_corrective_features.stress_cost_screen",return_value={
            "feasible":False,"flat_cost":1000.,"target_net":-1.,"denial_reason":"cost"
        }):
            r=make_features(f)
        self.assertEqual(np.flatnonzero(r["abc_first_close_break_event"]).tolist(),[40])
        self.assertFalse(r["abc_stress_cost_feasible"].iloc[40])

    def test_c_low_invalidation_takes_precedence_over_close_cross(self):
        f=make_frames()
        f.loc[40,"low"]=94.
        r=make_features(f)
        self.assertTrue(r["abc_invalidated"].iloc[40])
        self.assertFalse(r["abc_first_close_break_event"].iloc[40])

    def test_H0_overshoot_before_close_cross_invalidates(self):
        f=make_frames()
        f.loc[40,"high"]=121.
        r=make_features(f)
        self.assertTrue(r["abc_invalidated"].iloc[40])
        self.assertFalse(r["abc_first_close_break_event"].iloc[40])

    def test_duplicate_neighbor_high_rejects_H0(self):
        f=make_frames()
        f.loc[11,"high"]=120.
        r=make_features(f)
        self.assertFalse(r["abc_first_close_break_event"].any())

    def test_dual_extrema_bar_rejects_H0(self):
        f=make_frames()
        f.loc[12,"low"]=90.
        r=make_features(f)
        self.assertFalse(r["abc_first_close_break_event"].any())

    def test_early_close_above_hb_before_lc_confirmation_cannot_store(self):
        f=make_frames()
        f.loc[38,["open","high","low","close"]]=[106.,113.,105.,112.]
        r=make_features(f)
        self.assertFalse(r["abc_first_close_break_event"].any())
        self.assertFalse(r["lagged_abc_active"].iloc[40])

    def test_bad_path_B_segment_extremum_rejects(self):
        f=make_frames()
        f.loc[26,"low"]=99.
        p=confirmed_abc()
        self.assertEqual(_path_error(p,f["high"].to_numpy(),f["low"].to_numpy(),
                                     f["close"].to_numpy(),39), "B_segment_path_extremum")

    def test_bad_path_C_segment_extremum_rejects(self):
        f=make_frames()
        f.loc[33,"high"]=111.
        p=confirmed_abc()
        self.assertEqual(_path_error(p,f["high"].to_numpy(),f["low"].to_numpy(),
                                     f["close"].to_numpy(),39), "C_segment_path_extremum")

    def test_nonuniform_gap_cannot_be_used(self):
        f=make_frames()
        f.loc[23:,"timestamp"]+=pd.Timedelta(minutes=15)
        with self.assertRaises(ValueError):
            make_features(f)

    def test_timezone_naive_rejected(self):
        f=make_frames()
        f["timestamp"]=f["timestamp"].dt.tz_localize(None)
        with self.assertRaises(ValueError):
            make_features(f)

    def test_corrupt_ohlc_rejected(self):
        f=make_frames()
        f.loc[15,"high"]=104.
        with self.assertRaises(ValueError):
            make_features(f)

    def test_no_live_no_factory_no_auto_demo(self):
        self.assertTrue(RESEARCH_ONLY)
        self.assertFalse(LIVE_ENABLED)
        self.assertFalse(AUTO_DEMO)
        self.assertFalse(FACTORY_REGISTERED)
        r=make_features(make_frames())
        self.assertNotIn("order",r)
        self.assertNotIn("next_open_fill",r)


if __name__=="__main__":
    unittest.main(verbosity=2)
