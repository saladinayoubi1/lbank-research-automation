"""Fixed degree segmentation V50 regression: no P/L-driven wave trimming."""
import unittest
from dataclasses import replace
import numpy as np
import pandas as pd
from nested_elliott_v40 import ConfirmedPivot,check_nested_structure
from test_nested_elliott_v40 import fixture
from propose_degree_v50 import propose_three_minute_child_degree,RESEARCH_ONLY,ENTRY_SIGNAL,LIVE_ENABLED,AUTO_DEMO,PAPER_ELIGIBLE,CHILD_MINUTES

def spaced_fixture():
    original,parents,children,_=fixture()
    originals=[p for leg in children for p in leg[:-1]]+[children[-1][-1]]
    def convert(p):
        idx=10+9*((p.index-10)//7)
        return ConfirmedPivot(p.kind,idx,idx+3,p.price)
    converted=[convert(p) for p in originals]
    indices=[x.index for x in converted]
    prices=[float(x.price) for x in converted]
    n=indices[-1]+12
    values=np.interp(np.arange(n),[0]+indices+[n-1],[prices[0]+1]+prices+[prices[-1]+1])
    bars=pd.DataFrame({"timestamp":pd.date_range("2026-10-01T00:00:00Z",periods=n,freq="min"),
          "open":values,"high":values,"low":values,"close":values})
    cps=tuple(convert(p) for p in parents)
    legs=tuple(tuple(convert(p) for p in leg) for leg in children)
    return bars,cps,legs,bars["timestamp"].iat[-1]+pd.Timedelta(minutes=1)

class V50FixedDegreeTests(unittest.TestCase):
    def setUp(self):
        self.bars,self.parents,self.children,self.close=spaced_fixture()
    def prove(self,bars=None,parents=None,close=None):
        return propose_three_minute_child_degree(
             self.bars if bars is None else bars,
             self.parents if parents is None else parents,
             decision_close_utc=self.close if close is None else close)
    def test_predeclared_ratio_exact(self):
        self.assertEqual(CHILD_MINUTES,3)
        self.assertFalse(ENTRY_SIGNAL or LIVE_ENABLED or AUTO_DEMO or PAPER_ELIGIBLE)
        self.assertTrue(RESEARCH_ONLY)
    def test_structurally_valid_source_fixture(self):
        p=check_nested_structure(self.bars,self.parents,self.children,decision_close_utc=self.close)
        self.assertTrue(p.source_bound,p.reason)
    def test_predeclared_degree_on_synthetic_complete(self):
        r=self.prove()
        self.assertTrue(r.source_bound_one_degree,r.reason)
        self.assertEqual(r.per_leg_selected_counts,(4,2,4,2,4,4,2,4))
        self.assertFalse(r.entry_signal or r.paper_eligible or r.complete_recursive_elliott)
    def test_missing_parent_rejected(self):
        self.assertEqual(self.prove(parents=self.parents[:-1]).reason,"NINE_PARENTS_REQUIRED")
    def test_changed_parent_price_rejected(self):
        p=list(self.parents);p[2]=replace(p[2],price=float(p[2].price)+.25)
        self.assertEqual(self.prove(parents=tuple(p)).reason,"PARENT_NOT_PAST_CONFIRMED_SOURCE_PIVOT")
    def test_future_parent_confirmation_rejected(self):
        p=list(self.parents);p[-1]=replace(p[-1],confirmed_at=len(self.bars)+1)
        self.assertEqual(self.prove(parents=tuple(p)).reason,"PARENT_NOT_PAST_CONFIRMED_SOURCE_PIVOT")
    def test_future_tail_rejected(self):
        self.assertEqual(self.prove(close=self.close-pd.Timedelta(minutes=1)).reason,"SOURCE_DECISION_NOT_EXACT_ASOF")
    def test_missing_source_minute_rejected(self):
        df=self.bars.drop(index=25).reset_index(drop=True)
        self.assertEqual(self.prove(bars=df).reason,"SOURCE_NOT_CONTIGUOUS_1M")
    def test_naive_decision_rejected(self):
        self.assertEqual(self.prove(close=self.close.tz_localize(None)).reason,"DECISION_NOT_UTC_AWARE")
    def test_nonfinite_source_rejected(self):
        df=self.bars.copy();df.loc[27,"high"]=np.nan
        self.assertEqual(self.prove(bars=df).reason,"INVALID_SOURCE_PRICES")
    def test_dual_extrema_rejected(self):
        df=self.bars.copy()
        index=self.parents[2].index
        # Confirm source-unique boundary becomes a tie; parent then cannot be proved.
        df.loc[index+1,["open","high","low","close"]]=float(self.parents[2].price)
        self.assertFalse(self.prove(bars=df).source_bound_one_degree)
    def test_utc_offset_equivalence(self):
        stamp=self.close.tz_convert("Europe/Madrid")
        self.assertEqual(self.prove(close=stamp).source_bound_one_degree,self.prove().source_bound_one_degree)
    def test_naive_source_rejected(self):
        df=self.bars.copy()
        df["timestamp"]=df["timestamp"].dt.tz_localize(None)
        self.assertEqual(self.prove(bars=df).reason,"SOURCE_NOT_UTC_AWARE")
    def test_prefix_invariance_after_new_market_bars(self):
        first=self.prove()
        future=pd.DataFrame({"timestamp":pd.date_range(self.close,periods=18,freq="min")})
        last=float(self.bars["close"].iat[-1])
        vals=last+np.arange(1,19)*0.1
        for col in ("open","high","low","close"):
            future[col]=vals
        extended=pd.concat([self.bars,future],ignore_index=True)
        later=self.prove(bars=extended,close=self.close+pd.Timedelta(minutes=18))
        self.assertEqual(first.source_bound_one_degree,later.source_bound_one_degree)
        self.assertEqual(first.per_leg_selected_counts,later.per_leg_selected_counts)

if __name__=="__main__":unittest.main()
