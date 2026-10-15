"""Source-bound Spring observer bridge tests, synthetic bars only."""
from copy import deepcopy
import json
import unittest

import numpy as np
import pandas as pd

import nexus_composite_strategy_research as engine
import nexus_spring_observation_bridge as bridge
import nexus_spring_research_signal as spring
from test_nexus_causal_macro_retest_features import aggregate
from test_nexus_spring_parent_feature_review import minute_spring


class SpringSourceBoundObserverSyntheticTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source=aggregate(minute_spring())
        cls.frame,_=spring.inspect_research_signals(cls.source)

    def ready(self):
        f=self.frame.copy(deep=True)
        self.assertEqual(np.flatnonzero(f.spring_first_support_reclaim_event).tolist(),[288])
        f.loc[288,["h4_up","h1_vol_ok"]]=[1.,1.]
        self.assertEqual(np.flatnonzero(spring.research_signals(f)).tolist(),[288])
        return f

    def test_two_cost_profiles_use_exact_original_engine(self):
        f=self.ready()
        before=f.copy(deep=True)
        for fee,slip in ((10,5),(25,15)):
            with self.subTest(fee=fee,slip=slip):
                observed=bridge.observe_spring_candidate(f,fee_bps=fee,slip_bps=slip)
                raw=engine.backtest(f,spring.research_signals(f),fee_bps=fee,slip_bps=slip,risk_variant=0)
                self.assertEqual(json.dumps(observed["metrics"],sort_keys=True),
                                 json.dumps(raw,sort_keys=True))
                self.assertEqual(observed["observation_event_profile"],"liquidity_spring")
                self.assertEqual(observed["original_frozen_observer_profile"],"abc_correction")
                self.assertEqual([x["bar_index"] for x in observed["price_events"]],[288])
                self.assertEqual(observed["price_events"][0]["admission"],"scheduled_next_open")
                self.assertEqual(observed["price_events"][0]["cost_inputs"]["span"],25.)
                self.assertEqual(len(observed["trades"]),1)
                trade=observed["trades"][0]
                self.assertEqual(trade["fill"]["bar_index"],289)
                self.assertEqual(trade["decision"]["bar_index"],288)
                self.assertEqual(trade["decision"]["decision_at"],trade["fill"]["open_at"])
                self.assertEqual(trade["entry_reference"],f.loc[289,"open"])
                self.assertEqual(trade["decision"]["setup"]["spring_l0_index"],268.)
                self.assertEqual(trade["decision"]["setup"]["spring_l2_index"],284.)
                self.assertFalse(any(k.startswith("lagged_abc") for k in trade["decision"]["setup"]))
                json.dumps(observed,allow_nan=False)
        pd.testing.assert_frame_equal(f,before)

    def test_denied_cost_event_consumed_and_recorded_without_trade(self):
        f=self.ready()
        f.loc[288,"spring_stress_cost_feasible"]=False
        o=bridge.observe_spring_candidate(f,fee_bps=25,slip_bps=15)
        self.assertEqual(len(o["trades"]),0)
        self.assertEqual(len(o["price_events"]),1)
        self.assertEqual(o["price_events"][0]["admission"],"signal_denied")
        # Public trace must use the originating Spring gate, not a temporary alias.
        self.assertIn("spring_stress_cost_feasible",o["price_events"][0]["denial_fields"])
        self.assertNotIn("abc_stress_cost_feasible",o["price_events"][0]["denial_fields"])

    def test_h4_gate_denial_is_recorded(self):
        f=self.ready();f.loc[288,"h4_up"]=0
        o=bridge.observe_spring_candidate(f,fee_bps=10,slip_bps=5)
        self.assertEqual(len(o["price_events"]),1)
        self.assertEqual(o["price_events"][0]["admission"],"signal_denied")
        self.assertIn("h4_up",o["price_events"][0]["denial_fields"])
        self.assertFalse(o["trades"])

    def test_wrong_fee_slip_pair_fail_closed(self):
        with self.assertRaises(ValueError):
            bridge.observe_spring_candidate(self.frame,fee_bps=10,slip_bps=15)
        with self.assertRaises(ValueError):
            bridge.observe_spring_candidate(self.frame,fee_bps=25,slip_bps=5)

    def test_bad_fold_index_rejected(self):
        for off in (True,-1,1.5,"10"):
            with self.subTest(off=off),self.assertRaises(ValueError):
                bridge.observe_spring_candidate(self.frame,fee_bps=10,slip_bps=5,index_offset=off)

    def test_global_fold_index_and_source_setup_identity(self):
        original=self.ready()
        frame=original.iloc[275:400].reset_index(drop=True)
        observed=bridge.observe_spring_candidate(frame,fee_bps=10,slip_bps=5,index_offset=275)
        self.assertEqual([x["bar_index"] for x in observed["price_events"]],[288])
        self.assertEqual(observed["trades"][0]["fill"]["bar_index"],289)
        self.assertEqual(observed["trades"][0]["decision"]["setup"]["spring_confirmed_at"],287.)
        self.assertEqual(observed["price_events"][0]["setup"]["spring_sweep_depth_ratio"],0.25)

    def test_untrusted_event_missing_causal_pivot_fails_closed(self):
        f=self.ready()
        for name,value in (("spring_confirmed_at",288.),
                           ("spring_l0",95.),
                           ("spring_l2_index",288.),
                           ("spring_trigger_index",287.),
                           ("spring_sweep_depth_ratio",.9)):
            altered=f.copy(deep=True);altered.loc[288,name]=value
            with self.subTest(name=name),self.assertRaisesRegex(ValueError,"causal geometry"):
                bridge.observe_spring_candidate(altered,fee_bps=10,slip_bps=5)

    def test_absent_or_colliding_observer_fields_fail_closed(self):
        f=self.ready()
        with self.assertRaises(ValueError):
            bridge.observe_spring_candidate(
                f.drop(columns="spring_first_support_reclaim_event"),fee_bps=10,slip_bps=5)
        f["lagged_abc_h0"]=np.nan
        with self.assertRaisesRegex(ValueError,"collision"):
            bridge.observe_spring_candidate(f,fee_bps=10,slip_bps=5)

    def test_authority_and_factory_invariant(self):
        self.assertTrue(bridge.RESEARCH_ONLY)
        self.assertFalse(bridge.LIVE_ENABLED)
        self.assertFalse(bridge.AUTO_DEMO)
        self.assertFalse(bridge.FACTORY_REGISTERED)
        self.assertNotIn(spring.candidate_config()["mechanism"],engine.ALL_MECHANISMS)


if __name__=="__main__":
    unittest.main(verbosity=2)
