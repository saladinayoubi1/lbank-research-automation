"""V73 parent H1/H4 source as-of adversarial tests.

Synthetic fixtures only; physical source archive is tested separately.
"""
import unittest
import numpy as np
import pandas as pd
from parent_asof_v73 import audit_asof_one,RESEARCH_ONLY,ENTRY_SIGNAL,PAPER_ELIGIBLE,LIVE_ENABLED

def source(minutes=60,n=165):
    t=pd.date_range("2024-01-01T00:00:00Z",periods=n,freq=f"{minutes}min")
    base=100+np.arange(n)*0.1
    return pd.DataFrame({"timestamp":t,"open":base,"high":base+1,
                         "low":base-1,"close":base+0.2,"volume":np.full(n,10.)})

def faithful_asof(source,interval_ms,decisions,fields,label):
    dt=pd.to_datetime(source["timestamp"],utc=True)+pd.Timedelta(milliseconds=interval_ms)
    frame=pd.DataFrame({"available_at":dt})
    for k,v in fields.items():frame[label+k]=v.to_numpy()
    return pd.merge_asof(decisions[["decision_at"]].sort_values("decision_at"),
                         frame,left_on="decision_at",right_on="available_at",
                         direction="backward",allow_exact_matches=True).drop(
                             columns=["decision_at","available_at"])

def at(source,minutes=60,idx=110,delta=15):
    return source["timestamp"].iat[idx]+pd.Timedelta(minutes=minutes+delta)

class V73ParentAsOfTests(unittest.TestCase):
    def test_1h_completed_only(self):
        df=source()
        r=audit_asof_one(df,at(df),60,faithful_asof)
        self.assertTrue(r["original_asof_equals_independent_oracle"])
        self.assertTrue(r["future_parent_not_yet_closed_at_decision"])
    def test_4h_completed_only(self):
        df=source(240)
        r=audit_asof_one(df,at(df,240),240,faithful_asof)
        self.assertTrue(r["future_8_parent_bar_append_and_extreme_mutation_invariant"])
        self.assertEqual(r["timeframe_minutes"],240)
    def test_exact_parent_closing_boundary_is_allowed(self):
        df=source()
        r=audit_asof_one(df,at(df,delta=0),60,faithful_asof)
        self.assertEqual(r["latest_completed_parent_close_utc"],
            (df["timestamp"].iat[110]+pd.Timedelta(hours=1)).isoformat())
    def test_forged_asof_using_latest_future_bar_rejected(self):
        df=source()
        def forged(src,ms,dec,fields,label):
            report=faithful_asof(src,ms,dec,fields,label)
            report.iloc[0,0]=999.0
            return report
        with self.assertRaisesRegex(ValueError,"FUTURE_CONTEXT_LEAK"):
            audit_asof_one(df,at(df),60,forged)
    def test_future_only_ohlc_tampering_detected(self):
        df=source()
        def covert(src,ms,dec,fields,label):
            r=faithful_asof(src,ms,dec,fields,label)
            # Corrupt as-of output only if a future high was manipulated.
            if float(src["high"].max())>170:
                r.iloc[0,0]=999.0
            return r
        with self.assertRaisesRegex(ValueError,"FUTURE_CONTEXT_LEAK"):
            audit_asof_one(df,at(df),60,covert)
    def test_missing_hourly_source_bar_fails(self):
        df=source().drop(index=51).reset_index(drop=True)
        with self.assertRaisesRegex(ValueError,"PARENT_PHYSICAL_TIMEGRID"):
            audit_asof_one(df,at(df),60,faithful_asof)
    def test_naive_decision_rejected(self):
        with self.assertRaisesRegex(ValueError,"NAIVE"):
            audit_asof_one(source(),"2024-01-05 15:15:00",60,faithful_asof)
    def test_unregistered_interval_rejected(self):
        with self.assertRaisesRegex(ValueError,"TIMEFRAME_NOT_REGISTERED"):
            audit_asof_one(source(),"2024-01-05T15:15:00Z",30,faithful_asof)
    def test_insufficient_parent_history_rejected(self):
        df=source()
        with self.assertRaisesRegex(ValueError,"INSUFFICIENT_CAUSAL"):
            audit_asof_one(df,at(df,idx=15),60,faithful_asof)
    def test_nonexecuting_flags(self):
        self.assertTrue(RESEARCH_ONLY)
        self.assertFalse(ENTRY_SIGNAL or PAPER_ELIGIBLE or LIVE_ENABLED)
if __name__=="__main__":unittest.main()
