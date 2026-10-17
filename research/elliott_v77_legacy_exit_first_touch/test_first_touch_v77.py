"""V77 source-bar first-touch regression cases; synthetic and research-only."""
import unittest
import pandas as pd
from first_touch_v77 import (
    first_touch_path,RESEARCH_ONLY,ENTRY_SIGNAL,PAPER_ELIGIBLE,LIVE_ENABLED)

def bars(final=None,first=None):
    data=[dict(open=100.,high=103.,low=98.,close=101.),
          dict(open=101.,high=105.,low=97.,close=102.),
          final or dict(open=102.,high=112.,low=99.,close=111.)]
    if first is not None:data[0]=first
    return pd.DataFrame(data)

def trade(*,reason="target",exit_reference=110.,stop=95.,target=110.,
          entry_bar=0,exit_bar=2,exposure=3):
    return dict(fill=dict(bar_index=entry_bar),
        exit=dict(bar_index=exit_bar),
        entry_reference=100.,stop=stop,target=target,
        exposure_bars=exposure,exit_reason=reason,
        exit_reference=exit_reference)

class V77FirstTouchedExitTests(unittest.TestCase):
    def test_target_first_touched_on_exit_bar_only(self):
        v=first_touch_path(bars(),trade())
        self.assertEqual(v["first_target_touch_bar"],2)
        self.assertIsNone(v["first_stop_touch_bar"])
        self.assertEqual(v["prior_exit_touch_count"],0)
        self.assertEqual(v["exposure_bars"],3)
        self.assertTrue(v["preexit_favorable_R"]>=0)
    def test_target_earlier_bar_fails_closed(self):
        data=bars()
        data.loc[1,"high"]=111.
        with self.assertRaisesRegex(ValueError,"PRIOR_STOP_OR_TARGET"):
            first_touch_path(data,trade())
    def test_stop_earlier_bar_fails_closed(self):
        data=bars()
        data.loc[0,"low"]=94.
        with self.assertRaisesRegex(ValueError,"PRIOR_STOP_OR_TARGET"):
            first_touch_path(data,trade())
    def test_terminal_both_stop_and_target_uses_stop(self):
        data=bars(final=dict(open=100.,high=112.,low=94.,close=101.))
        t=trade(reason="stop",exit_reference=95.)
        v=first_touch_path(data,t)
        self.assertTrue(v["both_touched_terminal"])
        self.assertEqual(v["exit_reason"],"stop")
        self.assertEqual((v["first_target_touch_bar"],v["first_stop_touch_bar"]),(2,2))
    def test_gapped_open_uses_worse_open_exit(self):
        data=bars(final=dict(open=92.,high=107.,low=91.,close=100.))
        v=first_touch_path(data,trade(reason="stop_open_gap",exit_reference=92.))
        self.assertEqual(v["exit_reason"],"stop_open_gap")
    def test_mislabeled_terminal_target_is_denied(self):
        data=bars(final=dict(open=102.,high=112.,low=99.,close=111.))
        with self.assertRaisesRegex(ValueError,"TERMINAL_PRICE_OR_EXIT_REASON"):
            first_touch_path(data,trade(reason="stop",exit_reference=95.))
    def test_bar_after_64_bar_time_limit_denied(self):
        data=pd.DataFrame([dict(open=100.,high=103.,low=97.,close=101.) for i in range(65)])
        with self.assertRaisesRegex(ValueError,"TIME_EXIT_DELAYED"):
            first_touch_path(data,trade(reason="time_64_bars",exit_reference=101.,
                exit_bar=64,exposure=65))
    def test_invalid_exposure_count_denied(self):
        with self.assertRaisesRegex(ValueError,"INVALID_TRADE_EXPOSURE"):
            first_touch_path(bars(),trade(exposure=2))
    def test_invalid_candle_geometry_denied(self):
        data=bars();data.loc[1,"high"]=96.
        with self.assertRaisesRegex(ValueError,"INVALID_PHYSICAL_BAR"):
            first_touch_path(data,trade())
    def test_never_trade(self):
        self.assertTrue(RESEARCH_ONLY)
        self.assertFalse(ENTRY_SIGNAL or PAPER_ELIGIBLE or LIVE_ENABLED)
if __name__=="__main__":unittest.main()
