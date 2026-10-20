"""Independent mathematical and metamorphic checks; synthetic daily bars only."""
import unittest
from dataclasses import replace
from datetime import datetime, timezone
import numpy as np
from research.nexus_ctrend_causal_features_v1 import (
    DAY_MS, DailyPanel, FEATURE_NAMES, SnapshotUnavailable,
    feature_snapshot, latest_closed_period,
)

def stamp(text):
    return int(datetime.fromisoformat(text).replace(tzinfo=timezone.utc).timestamp()*1000)

def panel(days=800,assets=3):
    t=np.arange(days)[:,None]
    j=np.arange(assets)[None,:]
    close=100+.05*t+2*np.sin(t/7+j/5)+.5*np.cos(t/13+j)
    op=close-.2*np.cos(t/4+j)
    times=stamp("2019-01-02")+np.arange(days,dtype=np.int64)*DAY_MS
    return DailyPanel(times,np.broadcast_to(times[:,None],close.shape),
        tuple("SYNTH%02d"%i for i in range(assets)),op,
        np.maximum(op,close)+1,np.minimum(op,close)-1,close,
        1000+200*j+50*np.sin(t/3+j),2e6+1e4*t+1e5*j,
        np.ones(close.shape,dtype=bool),"synthetic:causal-daily-fixture-v1")

class CausalFeatureTests(unittest.TestCase):
    def setUp(self):
        self.p=panel()
        self.decision=stamp("2020-08-05")

    def test_full_snapshot_has_28_features_and_week_local_provenance(self):
        s=feature_snapshot(self.p,self.decision)
        self.assertEqual(s.values.shape,(3,len(FEATURE_NAMES)))
        self.assertEqual(len(FEATURE_NAMES),28)
        self.assertTrue(s.eligible.all())
        self.assertTrue(np.all(s.value_times_ms>s.period_start_ms))
        self.assertTrue(np.all(s.value_times_ms<=s.period_end_ms))
        self.assertTrue(np.all(s.cap_times_ms<=s.decision_time_ms))
        with self.assertRaises(ValueError): s.values[0,0]=0

    def test_sma200_and_bollinger_have_independent_arithmetic_oracles(self):
        s=feature_snapshot(self.p,self.decision)
        i=int(np.flatnonzero(self.p.close_times_ms==s.period_end_ms)[0])
        c=self.p.close[:i+1,0]
        self.assertAlmostEqual(s.values[0,6],sum(c[-200:])/200/c[-1],14)
        mean=sum(c[-20:])/20
        sd=(sum((x-mean)**2 for x in c[-20:])/19)**.5
        self.assertAlmostEqual(s.values[0,24],(mean+2*sd)/c[-1],14)

    def test_valid_future_mutations_and_extension_cannot_change_snapshot(self):
        p=self.p; original=feature_snapshot(p,self.decision)
        fields={}
        future=p.close_times_ms>original.period_end_ms
        for name in ("open","high","low","close","volume","market_caps"):
            a=getattr(p,name).copy();a[future]*=17;fields[name]=a
        altered=feature_snapshot(replace(p,**fields),self.decision)
        np.testing.assert_array_equal(original.values,altered.values)
        self.assertEqual(original.snapshot_sha256,altered.snapshot_sha256)
        stop=int(np.flatnonzero(p.close_times_ms==original.period_end_ms)[0])+1
        clipped=DailyPanel(p.close_times_ms[:stop],p.available_at_ms[:stop],p.asset_ids,
            *(getattr(p,n)[:stop] for n in ("open","high","low","close","volume","market_caps")),
            p.known_eligible[:stop],p.source_id)
        self.assertEqual(feature_snapshot(clipped,self.decision).snapshot_sha256,original.snapshot_sha256)

    def test_delayed_bar_is_not_backfilled_into_old_decision(self):
        p=self.p;_,_,end=latest_closed_period(self.decision)
        i=int(np.flatnonzero(p.close_times_ms==end)[0]);avail=p.available_at_ms.copy()
        avail[i,0]=self.decision+DAY_MS
        delayed=replace(p,available_at_ms=avail)
        before=feature_snapshot(delayed,self.decision)
        self.assertFalse(before.eligible[0])
        self.assertTrue(np.all(before.value_times_ms[0]<end))
        later=feature_snapshot(delayed,self.decision+DAY_MS)
        self.assertTrue(later.eligible[0])
        self.assertTrue(np.all(later.value_times_ms[0]==end))
        self.assertEqual(feature_snapshot(delayed,self.decision).snapshot_sha256,before.snapshot_sha256)

    def test_missing_endpoint_falls_back_only_inside_current_week(self):
        p=self.p;_,start,end=latest_closed_period(self.decision)
        c=p.close.copy();c[p.close_times_ms==end,0]=np.nan
        s=feature_snapshot(replace(p,close=c),self.decision)
        self.assertTrue(s.eligible[0])
        self.assertTrue(np.all(s.value_times_ms[0]==end-DAY_MS))
        c[(p.close_times_ms>start)&(p.close_times_ms<=end),0]=np.nan
        empty=feature_snapshot(replace(p,close=c),self.decision)
        self.assertFalse(empty.eligible[0])
        self.assertTrue(np.isnan(empty.values[0]).all())

    def test_partial_calendar_interval_is_rejected(self):
        p=panel(days=250)
        with self.assertRaises(SnapshotUnavailable):
            feature_snapshot(p,stamp("2020-08-05"))

    def test_year_end_bins_are_known_without_future_rows(self):
        for year,days in ((2019,8),(2020,9)):
            end=stamp(str(year+1)+"-01-01")
            code,start,actual_end=latest_closed_period(end)
            self.assertEqual((code,actual_end), (year*100+52,end))
            self.assertEqual((end-start)//DAY_MS,days)
            code_before,_,end_before=latest_closed_period(end-1)
            self.assertEqual(code_before,year*100+51)
            self.assertLess(end_before,end)

    def test_inputs_are_copied_and_future_invalid_ohlc_is_invisible(self):
        p=self.p;c=p.close.copy();before=feature_snapshot(p,self.decision)
        other=replace(p,close=c);c[:]=1
        self.assertEqual(feature_snapshot(other,self.decision).snapshot_sha256,before.snapshot_sha256)
        high=p.high.copy();high[p.close_times_ms>self.decision]=.01
        self.assertEqual(feature_snapshot(replace(p,high=high),self.decision).snapshot_sha256,before.snapshot_sha256)
        high[0]=.01
        with self.assertRaises(ValueError): feature_snapshot(replace(p,high=high),self.decision)

    def test_extreme_return_is_not_censored_and_200_valid_days_are_required(self):
        p=self.p;_,_,end=latest_closed_period(self.decision)
        i=int(np.flatnonzero(p.close_times_ms==end)[0])
        fields={n:getattr(p,n).copy() for n in ("open","high","low","close")}
        for a in fields.values(): a[i,0]*=20
        s=feature_snapshot(replace(p,**fields),self.decision)
        self.assertTrue(s.eligible[0])
        expected=np.mean(np.r_[p.close[i-199:i,0],fields["close"][i,0]])/fields["close"][i,0]
        self.assertAlmostEqual(s.values[0,6],expected,14)
        short=feature_snapshot(p,stamp("2019-07-10"))
        self.assertFalse(short.eligible.any())

    def test_unsigned_epoch_overflow_and_boolean_clocks_are_rejected(self):
        with self.assertRaises(ValueError):
            replace(self.p,available_at_ms=np.full(self.p.close.shape,2**63,dtype=np.uint64))
        with self.assertRaises(ValueError): feature_snapshot(self.p,True)

if __name__=="__main__": unittest.main()
