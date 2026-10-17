"""V54 regression: warm-up and already-scored Elliott waves cannot leak into a new daily score.

Synthetic pivot injection tests the scan's timing gate only. Fake pivots are
deliberately not presented as real or source-bound, and never authorize trades.
"""
import hashlib
import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch
import numpy as np
import pandas as pd
from nested_elliott_v40 import ConfirmedPivot
import scan_verified_v53 as scanner
from prospective_v52 import VerifiedDay

PRICES=(100,120,110,140,128,155,138,147,130)

class V54DailyExclusivityTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root=Path(tmp.name)
        self.days=[]
    def _grow(self,days):
        for i in range(len(self.days),days):
            d=pd.Timestamp("2026-10-16T00:00:00Z")+pd.Timedelta(days=i)
            idx=np.arange(1440,dtype=float)
            price=100+i*14.4+idx*.01
            df=pd.DataFrame({"timestamp":pd.date_range(d,periods=1440,freq="min",tz="UTC"),
                "open":price,"high":price+.1,"low":price-.1,"close":price,
                "volume":np.ones(1440),"trade_count":np.ones(1440,dtype=np.int64)})
            f=self.root/f"ETHUSDT-{i}.parquet"
            df.to_parquet(f,index=False)
            self.days.append((VerifiedDay("ETHUSDT",d.date().isoformat(),1440,1440,7200,1440,
                                           "a"*64,hashlib.sha256(f.read_bytes()).hexdigest()),f))
    def _with_fake_parents(self,first,last_day):
        # Nine alternating parents, all geometrically valid but intentionally
        # not price-bound; timing exclusion must happen before source admission.
        parents={
          first+15*j:ConfirmedPivot("low" if j%2==0 else "high",
                 first+15*j,first+15*j+3,PRICES[j])
          for j in range(9)}
        self._grow(last_day)
        with patch.object(scanner,"_confirmed_pivot",side_effect=lambda _h,_l,i:parents.get(i)):
            return scanner.scan_verified_complete_days(
                 "ETHUSDT",self.days[:last_day],
                 decision_close_utc=(pd.Timestamp("2026-10-16T00:00:00Z")+
                                     pd.Timedelta(days=last_day)))
    def test_warmup_geometry_at_oct18_boundary_excluded(self):
        r=self._with_fake_parents(first=15,last_day=2)
        self.assertEqual(r.nine_parent_group_count,1)
        self.assertEqual(r.warmup_geometry_excluded,1)
        self.assertEqual(r.parent_geometry_candidates,0)
        self.assertEqual(r.bounded_child_candidates,0)
        self.assertEqual(len(r.candidates),0)
    def test_warmup_not_retroactively_scored_oct20(self):
        r=self._with_fake_parents(first=15,last_day=4)
        self.assertEqual(r.warmup_geometry_excluded,1)
        self.assertEqual(r.parent_geometry_candidates,0)
        self.assertEqual(len(r.candidates),0)
    def test_post_start_geometry_scored_once_by_parent_confirmation(self):
        # Final parent center = index 328, confirmed at 331:
        # Oct 19 11:00 UTC, within scored Oct19 daily interval.
        first=208
        newly=self._with_fake_parents(first,last_day=4)
        self.assertEqual(newly.parent_geometry_candidates,1)
        self.assertEqual(newly.warmup_geometry_excluded,0)
        self.assertEqual(newly.previously_scored_geometry_excluded,0)
        self.assertEqual(len(newly.candidates),1)
        self.assertFalse(newly.candidates[0].parent_source_bound)
        self.assertFalse(newly.candidates[0].entry_signal)
        old=self._with_fake_parents(first,last_day=5)
        self.assertEqual(old.parent_geometry_candidates,0)
        self.assertEqual(old.previously_scored_geometry_excluded,1)
        self.assertEqual(len(old.candidates),0)

if __name__=="__main__":
    import unittest
    unittest.main()
