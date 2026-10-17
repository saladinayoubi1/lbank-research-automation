"""V62 regression: first-observed parent geometry must survive later compaction.

All pivots are synthetic and intentionally NOT source-bound or signals.
This tests event accounting only; source receipts remain physical test files.
"""
from __future__ import annotations
import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np
import pandas as pd
from nested_elliott_v40 import ConfirmedPivot
from prospective_v52 import VerifiedDay
import scan_verified_v53 as scanner

PRICES=(100,120,110,140,128,155,138,147,130)
FIRST=208
START=pd.Timestamp("2026-10-16T00:00:00Z")

class V62FirstSeenGeometryTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.root=Path(temp.name)
        self.days=[]
        for i in range(5):
            day=START+pd.Timedelta(days=i)
            p=100+i*14.4+np.arange(1440)*.01
            frame=pd.DataFrame({
                "timestamp":pd.date_range(day,periods=1440,freq="min",tz="UTC"),
                "open":p,"high":p+.1,"low":p-.1,"close":p,
                "volume":np.ones(1440),"trade_count":np.ones(1440,dtype=np.int64)
            })
            path=self.root/f"ETH-{i}.parquet"
            frame.to_parquet(path,index=False)
            self.days.append((VerifiedDay("ETHUSDT",day.date().isoformat(),
                1440,1440,7200,1440,"a"*64,
                hashlib.sha256(path.read_bytes()).hexdigest()),path))
        self.parents={
          FIRST+15*j:ConfirmedPivot("low" if j%2==0 else "high",
              FIRST+15*j,FIRST+15*j+3,float(PRICES[j]))
          for j in range(9)
        }
    def scan(self,days=4,inject=None):
        pivots=dict(self.parents)
        if inject:pivots.update(inject)
        with patch.object(scanner,"_confirmed_pivot",
                          side_effect=lambda _hi,_lo,i:pivots.get(i)):
            return scanner.scan_verified_complete_days(
                "ETHUSDT",self.days[:days],
                decision_close_utc=START+pd.Timedelta(days=days))
    def original_fingerprint(self):
        return hashlib.sha256(("ETHUSDT|"+"|".join(
            f"{p.index}:{p.price}" for p in self.parents.values()
        )).encode("utf8")).hexdigest()[:24]
    def test_original_event_fingerprint_remains_after_later_same_kind_replacement(self):
        # Both original (130) and replacement (90) make valid 9-parent
        # geometry, but first observed Oct19 11:00 is the 130 witness.
        old=self.scan()
        injected={345:ConfirmedPivot("low",345,348,90.)}
        replay=self.scan(inject=injected)
        self.assertEqual(old.parent_geometry_candidates,1)
        self.assertEqual(replay.parent_geometry_candidates,1)
        self.assertEqual(old.candidates[0].fingerprint,self.original_fingerprint())
        self.assertEqual(replay.candidates[0].fingerprint,old.candidates[0].fingerprint)
        self.assertEqual(replay.candidates[0].last_parent_confirmation_close_utc,
                         old.candidates[0].last_parent_confirmation_close_utc)
    def test_multiple_last_pivot_replacements_cannot_duplicate_first_event(self):
        replays=self.scan(inject={
            345:ConfirmedPivot("low",345,348,95.),
            359:ConfirmedPivot("low",359,362,87.)
        })
        self.assertEqual(replays.parent_geometry_candidates,1)
        self.assertEqual(len(replays.candidates),1)
        self.assertEqual(replays.candidates[0].fingerprint,self.original_fingerprint())
    def test_earlier_confirmed_candidate_not_retroactive_new_day(self):
        shifted=self.scan(days=5,inject={
            402:ConfirmedPivot("low",402,405,85.)
        })
        self.assertEqual(shifted.parent_geometry_candidates,0)
        self.assertEqual(shifted.previously_scored_geometry_excluded,1)
        self.assertEqual(len(shifted.candidates),0)
    def test_only_later_valid_ninth_extremum_starts_the_event_clock(self):
        # The original 140 low is ABOVE sixth-parent 138 => invalid ABC.
        # A later lower 130 low makes the same eight anchors valid only
        # after that replacement pivot's own right-hand confirmation.
        last=FIRST+15*8
        prior=self.parents[last]
        self.parents[last]=ConfirmedPivot("low",last,last+3,140.)
        none=self.scan()
        self.assertEqual(none.parent_geometry_candidates,0)
        requalified=self.scan(inject={
            345:ConfirmedPivot("low",345,348,130.)
        })
        self.assertEqual(requalified.parent_geometry_candidates,1)
        self.assertEqual(len(requalified.candidates),1)
        self.assertEqual(
            requalified.candidates[0].last_parent_confirmation_close_utc,
            (START+pd.Timedelta(minutes=349*15)).isoformat())
        self.assertNotEqual(
            requalified.candidates[0].fingerprint,
            self.original_fingerprint())
    def test_same_eight_anchors_do_not_emit_again_on_later_daily_close(self):
        before=self.scan(days=4,inject={
            340:ConfirmedPivot("low",340,343,90.)
        })
        later=self.scan(days=5,inject={
            340:ConfirmedPivot("low",340,343,90.),
            402:ConfirmedPivot("low",402,405,80.)
        })
        self.assertEqual(before.parent_geometry_candidates,1)
        self.assertEqual(later.parent_geometry_candidates,0)
        self.assertEqual(later.previously_scored_geometry_excluded,1)
        self.assertEqual(before.candidates[0].fingerprint,self.original_fingerprint())
    def test_no_replacement_preserves_frozen_v54_once_only(self):
        normal=self.scan()
        self.assertEqual(normal.parent_geometry_candidates,1)
        self.assertEqual(normal.candidates[0].fingerprint,self.original_fingerprint())
        self.assertFalse(normal.candidates[0].entry_signal)
        self.assertFalse(normal.candidates[0].paper_eligible)
        self.assertFalse(normal.entry_signal or normal.paper_eligible or normal.live_enabled)

if __name__=="__main__":unittest.main()
