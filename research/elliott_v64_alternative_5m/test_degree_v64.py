"""V64 five-minute child hypothesis: synthetic, source-bound, NO trading.

This is an independent exploratory alternative to frozen V52 3m wave count.
Positive synthetic tests prove implementation capability, not market efficacy.
"""
import unittest
from dataclasses import replace
import numpy as np
import pandas as pd
from test_degree_v50 import spaced_fixture
from propose_degree_v64 import (
    propose_five_minute_child_degree,
    PARENT_MINUTES,CHILD_MINUTES,RESEARCH_ONLY,ENTRY_SIGNAL,
    PAPER_ELIGIBLE,AUTO_DEMO,LIVE_ENABLED,COMPLETE_RECURSIVE_CLASSIFIER
)

class V64AlternateDegreeResearchTests(unittest.TestCase):
    def setUp(self):
        self.source,self.parents,_,self.close=spaced_fixture()
    def check(self,source=None,parents=None,close=None):
        return propose_five_minute_child_degree(
           self.source if source is None else source,
           self.parents if parents is None else parents,
           decision_close_utc=self.close if close is None else close)
    def test_independent_hypothesis_not_trading_mode(self):
        self.assertEqual(PARENT_MINUTES,15)
        self.assertEqual(CHILD_MINUTES,5)
        self.assertTrue(RESEARCH_ONLY)
        self.assertFalse(ENTRY_SIGNAL or PAPER_ELIGIBLE or AUTO_DEMO or
                         LIVE_ENABLED or COMPLETE_RECURSIVE_CLASSIFIER)
    def test_synthetic_genuine_5m_can_validate_known_child_geometry(self):
        result=self.check()
        self.assertTrue(result.source_bound_one_degree,result.reason)
        self.assertEqual(result.per_leg_raw_counts,(4,2,4,2,4,4,2,4))
        self.assertEqual(result.per_leg_selected_counts,(4,2,4,2,4,4,2,4))
        self.assertFalse(result.entry_signal or result.paper_eligible or result.complete_recursive_elliott)
    def test_future_1m_not_allowed(self):
        r=self.check(close=self.close-pd.Timedelta(minutes=1))
        self.assertEqual(r.reason,"SOURCE_DECISION_NOT_EXACT_ASOF")
    def test_missing_1m_source_not_filled(self):
        altered=self.source.drop(index=25).reset_index(drop=True)
        self.assertEqual(self.check(source=altered).reason,"SOURCE_NOT_CONTIGUOUS_1M")
    def test_parent_price_modified_rejected(self):
        changed=list(self.parents)
        changed[2]=replace(changed[2],price=float(changed[2].price)+0.25)
        self.assertEqual(self.check(parents=tuple(changed)).reason,
                         "PARENT_NOT_PAST_CONFIRMED_SOURCE_PIVOT")
    def test_parent_right_hand_confirmed_after_decision_denied(self):
        changed=list(self.parents)
        changed[-1]=replace(changed[-1],confirmed_at=len(self.source)+1)
        self.assertEqual(self.check(parents=tuple(changed)).reason,
                         "PARENT_NOT_PAST_CONFIRMED_SOURCE_PIVOT")
    def test_malformed_utc_denied(self):
        self.assertEqual(self.check(close=self.close.tz_localize(None)).reason,
                         "DECISION_NOT_UTC_AWARE")
    def test_malformed_origin_and_off_grid_denied(self):
        shifted=self.source.copy()
        shifted["timestamp"]=shifted["timestamp"]+pd.Timedelta(minutes=1)
        self.assertEqual(self.check(source=shifted,close=self.close+pd.Timedelta(minutes=1)).reason,
                         "SOURCE_NOT_UTC_ALIGNED_FOR_5M")
    def test_not_complete_recursive_even_on_positive_fixture(self):
        passed=self.check()
        self.assertTrue(passed.source_bound_one_degree)
        self.assertFalse(passed.complete_recursive_elliott)
    def test_strict_1m_parent_tie_rejected(self):
        df=self.source.copy()
        idx=self.parents[2].index
        df.loc[idx+1,["open","high","low","close"]]=float(self.parents[2].price)
        self.assertFalse(self.check(source=df).source_bound_one_degree)
    def test_immutable_prefix_evidence_after_more_market_minutes(self):
        baseline=self.check()
        future=pd.DataFrame({"timestamp":pd.date_range(self.close,periods=25,freq="min")})
        last=float(self.source["close"].iat[-1])
        vals=last+np.arange(1,26)*0.02
        for col in ("open","high","low","close"):future[col]=vals
        later=self.check(
            source=pd.concat([self.source,future],ignore_index=True),
            close=self.close+pd.Timedelta(minutes=25))
        self.assertEqual(later.source_bound_one_degree,baseline.source_bound_one_degree)
        self.assertEqual(later.per_leg_selected_counts,baseline.per_leg_selected_counts)
if __name__=="__main__":unittest.main()
