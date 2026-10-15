"""V49 fixed, no-pruning causal minute-child proposal regression tests."""
import unittest
from dataclasses import replace
import numpy as np
import pandas as pd
from test_nested_elliott_v40 import fixture
from propose_nested_v49 import propose_children_fixed,RESEARCH_ONLY,LIVE_ENABLED,PAPER_ELIGIBLE,ENTRY_SIGNAL

class V49FixedWitnessTests(unittest.TestCase):
    def setUp(self):
        self.df,self.parents,self.children,self.close=fixture()
    def run_proposal(self,df=None,parents=None,close=None):
        return propose_children_fixed(
         self.df if df is None else df,
         self.parents if parents is None else parents,
         decision_close_utc=self.close if close is None else close)
    def test_complete_predeclared_synthetic_witness(self):
        x=self.run_proposal()
        self.assertTrue(x.accepted,x.reason)
        self.assertTrue(x.validated_bounded_one_degree)
        self.assertEqual(x.raw_child_extrema_per_leg,(4,2,4,2,4,4,2,4))
        self.assertFalse(x.entry_signal or x.paper_eligible or x.recursively_complete)
    def test_research_flags(self):
        self.assertTrue(RESEARCH_ONLY)
        self.assertFalse(LIVE_ENABLED or PAPER_ELIGIBLE or ENTRY_SIGNAL)
    def test_parent_cardinality_rejected(self):
        self.assertEqual(self.run_proposal(parents=self.parents[:-1]).reason,"NINE_PARENT_ANCHORS_REQUIRED")
    def test_parent_price_not_source(self):
        p=list(self.parents)
        p[2]=replace(p[2],price=float(p[2].price)+1.0)
        self.assertFalse(self.run_proposal(parents=tuple(p)).accepted)
    def test_parent_future_confirm_rejected(self):
        p=list(self.parents)
        p[-1]=replace(p[-1],confirmed_at=len(self.df)+10)
        self.assertEqual(self.run_proposal(parents=tuple(p)).reason,"PARENT_CONFIRMATION_IN_FUTURE")
    def test_missing_source_minute_rejected(self):
        df=self.df.drop(index=25).reset_index(drop=True)
        self.assertEqual(self.run_proposal(df=df).reason,"MISSING_OR_OFFGRID_SOURCE")
    def test_naive_decision_rejected(self):
        x=self.run_proposal(close=self.close.tz_localize(None))
        self.assertEqual(x.reason,"INVALID_DECISION")
    def test_future_tail_rejected(self):
        # A forming/future record must not be visible at an earlier decision.
        x=self.run_proposal(close=self.close-pd.Timedelta(minutes=1))
        self.assertEqual(x.reason,"INCOMPLETE_OR_FUTURE_SOURCE")
    def test_mutated_parent_polarity_rejected(self):
        p=list(self.parents)
        p[0]=replace(p[0],kind="high")
        self.assertEqual(self.run_proposal(parents=tuple(p)).reason,"PARENT_NOT_STRICT_SOURCE_BOUND")
    def test_nonfinite_ohlc_rejected(self):
        df=self.df.copy();df.loc[12,"high"]=np.nan
        self.assertEqual(self.run_proposal(df=df).reason,"INVALID_OHLC")
    def test_inverted_ohlc_rejected(self):
        df=self.df.copy();df.loc[12,"high"]=df.loc[12,"low"]-0.1
        self.assertEqual(self.run_proposal(df=df).reason,"INVALID_OHLC_BOUNDS")
    def test_parent_duplicate_center_rejected(self):
        p=list(self.parents);p[1]=replace(p[1],index=p[0].index)
        self.assertEqual(self.run_proposal(parents=tuple(p)).reason,"PARENT_CHRONOLOGY")

if __name__=="__main__":unittest.main()
