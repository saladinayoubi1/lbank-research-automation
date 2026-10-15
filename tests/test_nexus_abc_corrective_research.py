"""Research-only ABC adapter, unchanged parent execution and old observer tests."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import sys
import unittest

import numpy as np
import pandas as pd

import nexus_abc_corrective_research as abc
import nexus_composite_strategy_research as engine
import nexus_backtest_observer as observer
from test_nexus_causal_macro_retest_features import aggregate,minute_fixture,signal_frame
from test_nexus_elliott_five_swing_research import hand_frame
from nexus_elliott_five_swing_research import candidate_signal_for as old_elliott_signal

STAGED=Path(r"E:\NEXUS-QA\elliott-backtest-adapter-20261015\source")


def minutes():
    n,start=1008,256
    rows=[dict(open=106.,high=107.,low=105.,close=106.,volume=1.) for _ in range(n)]
    positions={
        12: dict(open=110.,high=120.,low=105.,close=110.,volume=1.),
        20: dict(open=104.,high=106.,low=100.,close=104.,volume=1.),
        28: dict(open=106.,high=110.,low=105.,close=106.,volume=1.),
        36: dict(open=98.,high=100.,low=95.,close=98.,volume=1.),
        40: dict(open=106.,high=113.,low=105.,close=112.,volume=1.),
    }
    for i,row in positions.items():rows[start+i]=row
    m=pd.DataFrame(rows)
    m["timestamp"]=pd.date_range("2026-01-01T00:00:00Z",periods=n,freq="15min")
    return m


def gate_ready(frame):
    f=frame.copy(deep=True)
    index=np.flatnonzero(f["abc_first_close_break_event"].to_numpy())
    assert index.tolist()==[296], index
    f.loc[296,["h4_up","h1_vol_ok"]]=[1.,1.]
    return f


class ABCAdapterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.frames=aggregate(minutes())
        cls.full=abc.build_abc_research_features(cls.frames)

    def test_causality_and_original_parent_feature_equality(self):
        orig=deepcopy(self.frames)
        old=engine.build_features(deepcopy(self.frames))
        pd.testing.assert_frame_equal(old,self.full[old.columns])
        for k in orig:
            pd.testing.assert_frame_equal(orig[k],self.frames[k])
        self.assertEqual(np.flatnonzero(self.full.abc_first_close_break_event).tolist(),[296])
        self.assertEqual(self.full.loc[296,"lagged_abc_confirmed_at"],295)
        self.assertEqual((self.full.loc[296,"lagged_abc_h0_index"],
                          self.full.loc[296,"lagged_abc_lc_index"]), (268,292))
        self.assertEqual(self.full.loc[296,"abc_decision_range"],self.full.loc[296,"atr"])
        self.assertTrue(self.full.loc[296,"abc_stress_cost_feasible"])
        self.assertEqual(self.full.loc[296,"decision_at"],
                         self.frames["minute15"].loc[296,"timestamp"]+pd.Timedelta(minutes=15))

    def test_fixed_signal_context_and_no_automatic_factory(self):
        frame=gate_ready(self.full)
        self.assertEqual(np.flatnonzero(abc.candidate_signal_for(frame)).tolist(),[296])
        self.assertTrue(abc.RESEARCH_ONLY)
        self.assertFalse(abc.LIVE_ENABLED)
        self.assertFalse(abc.AUTO_DEMO)
        self.assertFalse(abc.FACTORY_REGISTERED)
        self.assertNotIn(abc.candidate_config()["mechanism"],engine.ALL_MECHANISMS)
        original=abc.candidate_config();original["risk_variant"]=1
        self.assertEqual(abc.candidate_config()["risk_variant"],0)
        with self.assertRaises(ValueError):abc.candidate_signal_for(frame,original)

    def test_gates_fail_closed_and_missing_required(self):
        for name,val in (
            ("h4_up",0),("h1_vol_ok",0),("lagged_abc_active",0),
            ("abc_first_close_break_event",0),("abc_stress_cost_feasible",0),
            ("atr",np.nan),("atr",0),("atr",np.inf),("open",120),
            ("previous_close",115),("close",np.inf),
        ):
            frame=gate_ready(self.full)
            frame.loc[296,name]=bool(val) if frame[name].dtype == bool else val
            with self.subTest(column=name,value=val):
                self.assertFalse(abc.candidate_signal_for(frame).any())
        with self.assertRaises(ValueError):
            abc.candidate_signal_for(gate_ready(self.full).drop(columns="abc_stress_cost_feasible"))

    def test_trace_next_open_fee_profiles_and_parent_identity(self):
        frame=gate_ready(self.full)
        before=frame.copy(deep=True)
        for fee,slip in ((10,5),(25,15)):
            observed=abc.backtest_abc_candidate(frame,fee_bps=fee,slip_bps=slip)
            original=engine.backtest(frame,abc.candidate_signal_for(frame),fee_bps=fee,slip_bps=slip,risk_variant=0)
            self.assertEqual(json.dumps(observed["metrics"],sort_keys=True),
                             json.dumps(original,sort_keys=True))
            self.assertEqual([e["bar_index"] for e in observed["price_events"]],[296])
            self.assertEqual(observed["price_events"][0]["admission"],"scheduled_next_open")
            self.assertEqual(observed["price_events"][0]["cost_inputs"]["span"],25.)
            self.assertEqual(observed["metrics"]["closed_round_trips"],1)
            self.assertEqual(len(observed["trades"]),1)
            trade=observed["trades"][0]
            self.assertEqual((trade["decision"]["bar_index"],trade["fill"]["bar_index"]),(296,297))
            self.assertEqual(trade["entry_reference"],frame.loc[297,"open"])
            self.assertEqual(trade["decision"]["decision_at"],trade["fill"]["open_at"])
            self.assertEqual(trade["decision"]["setup"]["lagged_abc_lc_index"],292.)
            self.assertEqual(trade["decision"]["setup"]["lagged_abc_h0_index"],268.)
            self.assertAlmostEqual(trade["entry_slipped"],106*(1+slip/10000))
            json.dumps(observed,allow_nan=False)
        pd.testing.assert_frame_equal(frame,before)
        self.assertIsNone(sys.gettrace())

    def test_price_event_cost_veto_logged_not_filled(self):
        frame=gate_ready(self.full)
        frame.loc[296,"abc_stress_cost_feasible"]=False
        result=abc.backtest_abc_candidate(frame,fee_bps=25,slip_bps=15)
        self.assertEqual(result["metrics"]["closed_round_trips"],0)
        self.assertEqual(result["price_events"][0]["admission"],"signal_denied")
        self.assertIn("abc_stress_cost_feasible",result["price_events"][0]["denial_fields"])
        self.assertEqual(result["trades"],[])

    def test_unregistered_cost_and_bad_offset_fail(self):
        with self.assertRaises(ValueError):
            abc.backtest_abc_candidate(self.full,fee_bps=0,slip_bps=0)
        with self.assertRaises(ValueError):
            abc.backtest_abc_candidate(self.full,fee_bps=10,slip_bps=5,index_offset=-1)

    def test_fold_global_index(self):
        frame=gate_ready(self.full).iloc[286:324].reset_index(drop=True)
        observed=abc.backtest_abc_candidate(frame,fee_bps=10,slip_bps=5,index_offset=286)
        self.assertEqual(observed["trades"][0]["decision"]["bar_index"],296)
        self.assertEqual(observed["trades"][0]["fill"]["bar_index"],297)
        self.assertEqual(observed["trades"][0]["decision"]["setup"]["lagged_abc_lc_index"],292.)

    def test_future_tail_change_keeps_past_all_context(self):
        altered=minutes()
        altered.loc[300:,["open","high","low","close"]]*=1.10
        changed=abc.build_abc_research_features(aggregate(altered))
        pd.testing.assert_frame_equal(self.full.iloc[:299],changed.iloc[:299])

    def test_old_macro_observer_byte_identical_and_rejects_unknown(self):
        spec=importlib.util.spec_from_file_location("frozen_abc_previous_observer",
            str(STAGED/"nexus_backtest_observer.py"))
        original=importlib.util.module_from_spec(spec)
        spec.loader.exec_module(original)
        f=signal_frame(minute_fixture())
        config=next(c for c in engine.FRONTIER_CONFIGS if
                    c["mechanism"]=="factory_causal_4h_break_1h_retest_cost_breakout")
        signals=engine.signal_for(f,config)
        for fee,slip in ((10,5),(25,15)):
            kw=dict(fee_bps=fee,slip_bps=slip,risk_variant=0)
            a=original.observe_backtest(engine.backtest,f,signals,**kw)
            b=observer.observe_backtest(engine.backtest,f,signals,**kw)
            self.assertEqual(json.dumps(a,sort_keys=True),json.dumps(b,sort_keys=True))
        e=hand_frame("target")
        es=old_elliott_signal(e)
        for fee,slip in ((10,5),(25,15)):
            kw=dict(fee_bps=fee,slip_bps=slip,risk_variant=0,event_profile="elliott_five_swing")
            a=original.observe_backtest(engine.backtest,e,es,**kw)
            b=observer.observe_backtest(engine.backtest,e,es,**kw)
            self.assertEqual(json.dumps(a,sort_keys=True),json.dumps(b,sort_keys=True))
        with self.assertRaises(ValueError):
            observer.observe_backtest(engine.backtest,f,signals,fee_bps=10,slip_bps=5,
                                     risk_variant=0,event_profile="abc_unknown")
        with self.assertRaises(ValueError):
            observer.observe_backtest(engine.backtest,self.full.drop(columns="abc_first_close_break_event"),
                                      abc.candidate_signal_for(self.full),fee_bps=10,slip_bps=5,
                                      risk_variant=0,event_profile="abc_correction")


if __name__=="__main__":
    unittest.main(verbosity=2)
