"""Semantic Butterfly causality/geometry and additive engine contracts."""
from copy import deepcopy
from dataclasses import replace
import ast
import hashlib
import json
from pathlib import Path
import unittest

import numpy as np
import pandas as pd

import nexus_composite_strategy_research as research
from nexus_causal_butterfly_features import (
    ConfirmedPivot, bullish_butterfly_geometry, build_lagged_butterfly_features,
    _confirmed_pivot,
)

ROOT = Path(__file__).resolve().parents[1]
IDENT = "factory_causal_bullish_butterfly"


def geometry_points(prices=(100.0,120.0,104.28,112.5,94.6)):
    return [ConfirmedPivot(kind,i*6,i*6+3,p) for i,(kind,p) in
            enumerate(zip(("low","high","low","high","low"),prices))]


def pattern_frame():
    n = 55
    knots = [0,6,12,18,24,30,36,42,54]
    prices = [108,100,120,104.28,112.5,94.6,103,101,102]
    close = np.interp(np.arange(n),knots,prices)
    return pd.DataFrame({"timestamp":pd.date_range("2024-01-01",periods=n,freq="15min",tz="UTC"),
      "open":close-0.04,"high":close+0.1,"low":close-0.1,"close":close,"volume":np.ones(n)})


def features(frame):
    return pd.DataFrame(build_lagged_butterfly_features(frame))


class ButterflyGeometryTests(unittest.TestCase):
    def test_exact_known_geometry_has_hand_calculated_ratios(self):
        got = bullish_butterfly_geometry(geometry_points())
        self.assertIsNotNone(got)
        for key,value in {"ab_over_xa":0.786,"ad_over_xa":1.27,
                          "bc_over_ab":8.22/15.72,"cd_over_bc":17.9/8.22,
                          "cd_over_ab":17.9/15.72,"rebound_price":96.6}.items():
            self.assertAlmostEqual(got[key],value,places=11)

    def test_price_scale_does_not_change_ratios(self):
        one = bullish_butterfly_geometry(geometry_points())
        two = bullish_butterfly_geometry(geometry_points(tuple(p*1000 for p in (100,120,104.28,112.5,94.6))))
        for key in ("ab_over_xa","ad_over_xa","bc_over_ab","cd_over_bc","cd_over_ab"):
            self.assertAlmostEqual(one[key],two[key],places=12)

    def test_gartley_depth_is_not_a_butterfly(self):
        self.assertIsNone(bullish_butterfly_geometry(geometry_points((100,120,104.28,112.5,104.6))))

    def test_non_fibonacci_and_degenerate_legs_rejected(self):
        for prices in ((100,120,110,112.5,94.6),(100,120,104.28,121,94.6),
                       (100,120,104.28,112.5,91),(100,100,100,100,100)):
            with self.subTest(prices=prices):
                self.assertIsNone(bullish_butterfly_geometry(geometry_points(prices)))

    def test_inclusive_ad_boundaries_and_outside_rejected(self):
        for d in (95.2,94.0):
            self.assertIsNotNone(bullish_butterfly_geometry(geometry_points((100,120,104.28,112.5,d))))
        for d in (95.2001,93.9999):
            self.assertIsNone(bullish_butterfly_geometry(geometry_points((100,120,104.28,112.5,d))))

    def test_pivot_count_kind_order_confirmation_and_span_rejected(self):
        variants=[]
        points=geometry_points()
        variants.append(points[:4])
        v=points.copy();v[2]=replace(v[2],kind="high");variants.append(v)
        v=points.copy();v[2]=replace(v[2],index=1);variants.append(v)
        v=points.copy();v[3]=replace(v[3],confirmed_at=v[3].index+2);variants.append(v)
        v=points.copy();v[-1]=replace(v[-1],index=193,confirmed_at=196);variants.append(v)
        for v in variants:
            self.assertIsNone(bullish_butterfly_geometry(v))

    def test_nonfinite_and_nonpositive_prices_rejected(self):
        for bad in (np.nan,np.inf,0,-1):
            p=list((100,120,104.28,112.5,94.6));p[2]=bad
            self.assertIsNone(bullish_butterfly_geometry(geometry_points(tuple(p))))


class ButterflyCausalityTests(unittest.TestCase):
    def test_event_requires_right_confirmation_plus_context_lag(self):
        got=features(pattern_frame())
        self.assertEqual(np.flatnonzero(got["lagged_bullish_butterfly_event"]),[34])
        self.assertEqual(got.loc[34,"lagged_butterfly_d_index"],30)
        self.assertEqual(got.loc[34,"lagged_butterfly_confirmed_at"],33)
        self.assertTrue(got.loc[:33,"lagged_butterfly_rebound_price"].isna().all())

    def test_every_valid_prefix_exactly_matches_emitted_history(self):
        frame=pattern_frame();whole=features(frame)
        for end in range(len(frame)+1):
            with self.subTest(end=end):
                pd.testing.assert_frame_equal(features(frame.iloc[:end]),whole.iloc[:end])

    def test_future_extreme_candles_cannot_repaint_past_pattern(self):
        old=pattern_frame();changed=old.copy()
        for column in ("open","high","low","close"):
            changed.loc[35:,column]*=3
        pd.testing.assert_frame_equal(features(old).iloc[:35],features(changed).iloc[:35])

    def test_current_decision_bar_cannot_change_lagged_context(self):
        old=pattern_frame();changed=old.copy()
        for column in ("open","high","low","close"):
            changed.loc[34:,column]*=2
        pd.testing.assert_frame_equal(features(old).iloc[:35],features(changed).iloc[:35])

    def test_a_pattern_is_one_event_not_a_repeated_hold_signal(self):
        got=features(pattern_frame())
        self.assertEqual(int(got["lagged_bullish_butterfly_event"].sum()),1)
        self.assertTrue(got.loc[35:,"lagged_butterfly_rebound_price"].isna().all())

    def test_same_kind_replacement_never_rewrites_history(self):
        old=pattern_frame().iloc[:35].copy()
        later=pattern_frame()
        later.loc[40:,"low"]=90
        later.loc[41,"low"]=88
        pd.testing.assert_frame_equal(features(old),features(later).iloc[:35])

    def test_flat_tied_and_dual_extrema_have_no_inferred_order(self):
        flat=pd.DataFrame({"timestamp":pd.date_range("2024-01-01",periods=30,freq="15min",tz="UTC"),
                           "open":100.,"high":100.,"low":100.,"close":100.})
        self.assertEqual(features(flat)["lagged_bullish_butterfly_event"].sum(),0)
        hi=np.ones(7)*101;lo=np.ones(7)*99;hi[3]=110;lo[3]=90
        self.assertIsNone(_confirmed_pivot(hi,lo,6))
        hi=np.ones(7)*101;lo=np.ones(7)*99;hi[3]=110;hi[4]=110
        self.assertIsNone(_confirmed_pivot(hi,lo,6))

    def test_empty_short_history_preserves_input_index(self):
        frame=pattern_frame();frame.index=pd.Index(range(100,155),name="row")
        for n in (0,1,6):
            got=features(frame.iloc[:n])
            self.assertEqual(len(got),n)
            self.assertEqual(got["lagged_bullish_butterfly_event"].sum(),0)
            self.assertTrue(got.index.equals(frame.index[:n]))

    def test_equivalent_timezones_give_identical_events(self):
        frame=pattern_frame();expected=features(frame)
        for zone in ("Asia/Tehran","Europe/London","America/New_York"):
            changed=frame.copy();changed["timestamp"]=changed["timestamp"].dt.tz_convert(zone)
            pd.testing.assert_frame_equal(expected,features(changed))

    def test_missing_duplicate_reversed_and_off_grid_times_fail_closed(self):
        frame=pattern_frame()
        variants=[frame.drop(columns="high"),frame.iloc[::-1],frame.drop(index=20)]
        duplicate=frame.copy();duplicate.loc[20,"timestamp"]=duplicate.loc[19,"timestamp"];variants.append(duplicate)
        off=frame.copy();off["timestamp"]+=pd.Timedelta(minutes=1);variants.append(off)
        null=frame.copy();null.loc[20,"timestamp"]=pd.NaT;variants.append(null)
        for v in variants:
            with self.assertRaises(ValueError):
                features(v)

    def test_invalid_market_values_fail_closed(self):
        frame=pattern_frame()
        for col,bad in (("high",1),("low",1000),("close",np.nan),("open",np.inf),("low",-1)):
            changed=frame.copy();changed.loc[20,col]=bad
            with self.assertRaises(ValueError):
                features(changed)


class ButterflyIntegrationTests(unittest.TestCase):
    def test_all_previous_contracts_and_order_remain_exact(self):
        prior=json.loads((ROOT/"tests/fixtures/butterfly_v8_prior_inventory.json").read_text())
        current={k:v for k,v in research.FACTORY_SPECS.items() if k not in (IDENT, "factory_causal_elliott_wave12_breakout", "factory_causal_4h_break_1h_retest_cost_breakout")}
        self.assertEqual(list(current),prior["factory_ids"])
        self.assertEqual({k:research.digest(v) for k,v in current.items()},prior["factory_spec_digests"])
        self.assertEqual([m for m in research.ALL_MECHANISMS if m not in (IDENT,"factory_causal_elliott_wave12_breakout", "factory_causal_4h_break_1h_retest_cost_breakout")],prior["all_mechanisms"])
        configs=[c for c in research.FRONTIER_CONFIGS if c["mechanism"] not in (IDENT,"factory_causal_elliott_wave12_breakout", "factory_causal_4h_break_1h_retest_cost_breakout")]
        self.assertEqual(research.digest(configs),prior["frontier_configs_digest"])
        self.assertEqual((len(current),len(prior["all_mechanisms"])),(92,119))
        source=(ROOT/"nexus_composite_strategy_research.py").read_text()
        node=next(x for x in ast.parse(source).body if isinstance(x,ast.FunctionDef) and x.name=="backtest")
        self.assertEqual(hashlib.sha256(ast.get_source_segment(source,node).encode()).hexdigest(),prior["backtest_function_sha256"])

    def test_terminal_prior_ledger_routes_only_butterfly_risk_zero(self):
        ledger=json.loads((ROOT/"tests/fixtures/butterfly_v8_terminal_ledger.json").read_text())
        before=deepcopy(ledger);choices=research._frontier_configs_to_screen(ledger)
        self.assertEqual([c["mechanism"] for c in choices],[IDENT])
        self.assertEqual(choices[0]["risk_variant"],0)
        self.assertEqual(ledger,before)
        self.assertEqual(research.research_mode(ledger),"frontier_tournament")

    def test_every_prior_tier_still_precedes_new_candidate(self):
        terminal=json.loads((ROOT/"tests/fixtures/butterfly_v8_terminal_ledger.json").read_text())
        for name in research.FRONTIER_MECHANISMS:
            if name in (IDENT,"factory_causal_elliott_wave12_breakout", "factory_causal_4h_break_1h_retest_cost_breakout"):continue
            with self.subTest(mechanism=name):
                ledger=deepcopy(terminal)
                ledger["mechanisms_evaluated"]=[x for x in ledger["mechanisms_evaluated"] if x!=name]
                ledger["frontier_screened_mechanisms"]=[x for x in ledger["frontier_screened_mechanisms"] if x!=name]
                self.assertEqual([x["mechanism"] for x in research._frontier_configs_to_screen(ledger)],[name])

    def test_entry_requires_separate_closed_response_and_atr(self):
        frame=pattern_frame();frame["previous_close"]=frame["close"].shift(1)
        frame["h1_vol_ok"]=1.;frame["atr"]=1.
        for col,values in build_lagged_butterfly_features(frame).items():frame[col]=values
        cfg=next(x for x in research.FRONTIER_CONFIGS if x["mechanism"]==IDENT)
        self.assertEqual(np.flatnonzero(research.signal_for(frame,cfg)),[34])
        for col,value in (("h1_vol_ok",0),("atr",np.nan),("lagged_butterfly_rebound_price",200),
                          ("lagged_bullish_butterfly_event",0)):
            changed=frame.copy();changed.loc[34,col]=value
            self.assertFalse(research.signal_for(changed,cfg).any())
        with self.assertRaises(research.CompositeResearchError):
            research.signal_for(frame,{**cfg,"risk_variant":1})

    def test_pipeline_feature_wiring_is_exact(self):
        close=100+np.sin(np.arange(1000)/9)*3
        minute=pd.DataFrame({"timestamp":pd.date_range("2024-01-01",periods=1000,freq="15min",tz="UTC"),
                            "open":close,"high":close+.2,"low":close-.2,"close":close,"volume":1.})
        indexed=minute.set_index("timestamp")
        agg={"open":"first","high":"max","low":"min","close":"last","volume":"sum"}
        frames={"minute15":minute,"hour1":indexed.resample("1h").agg(agg).reset_index(),
                "hour4":indexed.resample("4h").agg(agg).reset_index()}
        got=research.build_features(frames)
        for col,values in build_lagged_butterfly_features(minute).items():
            np.testing.assert_allclose(got[col],values,equal_nan=True)

    def test_existing_execution_uses_next_open_not_signal_bar_extremes(self):
        frame=pd.DataFrame({"decision_at":pd.date_range("2024-01-01",periods=4,freq="15min",tz="UTC"),
          "open":[50,100,100,103],"high":[1000,100.4,104,104],"low":[1,99.7,100,102],
          "close":[50,100,103,103],"atr":[1.,1.,1.,1.]})
        out=research.backtest(frame,np.array([True,False,False,False]),fee_bps=0,slip_bps=0,risk_variant=0)
        self.assertEqual(out["closed_round_trips"],1)
        self.assertAlmostEqual(out["net_pnl_usdt"],20,places=6)

    def test_research_authority_and_no_activity_count_filter(self):
        cfg=json.loads((ROOT/"research/mechanism_factory_v8.json").read_text())
        self.assertTrue(cfg["no_minimum_trade_count_gate"])
        self.assertFalse(cfg["live_trading_authority"])
        self.assertFalse(cfg["auto_demo_promotion"])
        self.assertEqual(len(cfg["candidates"]),1)
        self.assertEqual(research.SIM_CASH,10000)


if __name__=="__main__":
    unittest.main()

