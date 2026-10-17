"""Synthetic, offline V40 Elliott bounded child-degree proof regressions."""
import sys
import unittest
from dataclasses import replace
from pathlib import Path
import numpy as np
import pandas as pd
sys.path.insert(0,str(Path(__file__).resolve().parent))
from nested_elliott_v40 import (
 ConfirmedPivot,EXPECTED,check_nested_structure,RESEARCH_ONLY,
 LIVE_ENABLED,PAPER_ELIGIBLE,ENTRY_SIGNAL,COMPLETE_RECURSIVE_CLASSIFIER)

def fixture():
    prices=[100.0,120.0,110.0,140.0,128.0,155.0,138.0,147.0,130.0]
    pivots=[];legs=[]
    index=10
    current=ConfirmedPivot("low",index,index+3,prices[0])
    pivots.append(current)
    anchors=[(0,101.0),(index,prices[0])]
    for i,num in enumerate(EXPECTED):
        begin=prices[i];end=prices[i+1]
        delta=end-begin
        if num==5:
            values=[begin,begin+.4*delta,begin+.2*delta,begin+.75*delta,begin+.6*delta,end]
        else:
            values=[begin,begin+.65*delta,begin+.4*delta,end]
        group=[current]
        for j,value in enumerate(values[1:],1):
            index+=7
            kind="low" if (i+j)%2==0 else "high"
            p=ConfirmedPivot(kind,index,index+3,float(round(value,8)))
            group.append(p)
            anchors.append((index,p.price))
        current=group[-1]
        pivots.append(current)
        legs.append(tuple(group))
    anchors.append((index+10,prices[-1]+1.0))
    n=index+11
    series=np.interp(np.arange(n),[a for a,b in anchors],[b for a,b in anchors])
    ts=pd.date_range("2026-10-01T00:00:00Z",periods=n,freq="min")
    data=pd.DataFrame({"timestamp":ts,"open":series,"high":series,
         "low":series,"close":series})
    close=ts[-1]+pd.Timedelta(minutes=1)
    return data,tuple(pivots),tuple(legs),close

class V40NestedResearchTests(unittest.TestCase):
    def setUp(self):
        self.data,self.parent,self.legs,self.close=fixture()
    def check(self,data=None,parent=None,legs=None,close=None):
        return check_nested_structure(
            data if data is not None else self.data,
            parent if parent is not None else self.parent,
            legs if legs is not None else self.legs,
            decision_close_utc=close if close is not None else self.close)
    def test_complete_synthetic_bounded_proof(self):
        r=self.check()
        self.assertTrue(r.source_bound,r.reason)
        self.assertTrue(r.one_child_degree_validated)
        self.assertFalse(r.complete_recursive_elliott)
        self.assertFalse(r.entry_signal)
        self.assertFalse(r.paper_eligible)
    def test_contract_research_only(self):
        self.assertTrue(RESEARCH_ONLY)
        self.assertFalse(LIVE_ENABLED or PAPER_ELIGIBLE or ENTRY_SIGNAL or COMPLETE_RECURSIVE_CLASSIFIER)
    def test_missing_abc(self):
        r=self.check(parent=self.parent[:-1],legs=self.legs[:-1])
        self.assertFalse(r.source_bound)
        self.assertEqual(r.reason,"PARENT_OR_ABC_OR_LEGS_MISSING")
    def test_missing_middle_subwave(self):
        legs=list(self.legs);legs[2]=legs[2][:-2]+(legs[2][-1],)
        r=self.check(legs=legs)
        self.assertIn("SUBWAVE_COUNT",r.reason)
    def test_wrong_abc_endpoint(self):
        legs=list(self.legs)
        legs[-1]=tuple(list(legs[-1][:-1])+[self.parent[-2]])
        r=self.check(legs=legs)
        self.assertIn("ENDPOINT_MISMATCH",r.reason)
    def test_disordered_children(self):
        legs=list(self.legs)
        l=list(legs[0]);l[2],l[3]=l[3],l[2];legs[0]=tuple(l)
        r=self.check(legs=legs)
        self.assertIn("CHILD_CHRONOLOGY",r.reason)
    def test_future_confirmation_is_rejected(self):
        parent=list(self.parent);last=parent[-1]
        parent[-1]=replace(last,confirmed_at=last.confirmed_at+20)
        r=self.check(parent=parent)
        self.assertIn("SOURCE_PIVOT_REJECTED",r.reason)
    def test_claimed_price_not_at_source(self):
        parent=list(self.parent);parent[0]=replace(parent[0],price=99.0)
        r=self.check(parent=parent)
        self.assertIn("SOURCE_PIVOT_REJECTED",r.reason)
    def test_missing_utc_source_minute(self):
        df=self.data.drop(index=[20]).reset_index(drop=True)
        with self.assertRaisesRegex(ValueError,"grid"):
            self.check(data=df)
    def test_naive_time_rejected(self):
        df=self.data.copy()
        df["timestamp"]=df["timestamp"].dt.tz_localize(None)
        with self.assertRaisesRegex(ValueError,"timezone"):
            self.check(data=df)
    def test_incomplete_decision_close_rejected(self):
        with self.assertRaisesRegex(ValueError,"future or incomplete"):
            self.check(close=self.close-pd.Timedelta(minutes=1))
    def test_forming_future_tail_rejected(self):
        df=self.data.iloc[:-1].reset_index(drop=True)
        with self.assertRaisesRegex(ValueError,"future or incomplete"):
            self.check(data=df)
    def test_ambiguous_source_extrema_rejected(self):
        df=self.data.copy()
        idx=self.parent[3].index
        # Same high at neighbor removes strict local confirmation.
        df.loc[idx+1,["open","high","low","close"]]=self.parent[3].price
        r=self.check(data=df)
        self.assertIn("SOURCE_PIVOT_REJECTED",r.reason)
    def test_nonfinite_source_rejected(self):
        df=self.data.copy();df.loc[15,"close"]=np.nan
        with self.assertRaisesRegex(ValueError,"invalid OHLC"):
            self.check(data=df)
    def test_parent_wrong_kind_rejected(self):
        parent=list(self.parent);parent[0]=replace(parent[0],kind="high")
        r=self.check(parent=parent)
        self.assertEqual(r.reason,"PARENT_POLARITY_INVALID")
    def test_child_wrong_kind_rejected(self):
        legs=list(self.legs);l=list(legs[2]);l[1]=replace(l[1],kind="low")
        legs[2]=tuple(l)
        r=self.check(legs=legs)
        self.assertIn("CHILD_POLARITY",r.reason)

if __name__=="__main__":
    unittest.main()
