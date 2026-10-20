from __future__ import annotations
import hashlib,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"research"))
import nexus_mean_reversion_40_m2_momentum30_entry_v1 as c
import nexus_mean_reversion_40_m2_retest_v1 as b

def prices(n=320):
    start=b.ms("2026-01-01")
    return [[start+i*b.STEP,"100","101","99","100","1"] for i in range(n)]

class MomentumAdmissionTests(unittest.TestCase):
    def test_exact_baseline_engine_bytes(self):
        self.assertEqual(hashlib.sha256(Path(b.__file__).read_bytes()).hexdigest(),c.ENGINE_SHA)

    def test_equality_is_admitted_with_exactly_180_intervals(self):
        rows=prices();raw=[0]*180+[1]*140
        target,events=c.admit_episodes(rows,raw)
        self.assertEqual(target[180],1);self.assertTrue(events[0]["accepted"])
        self.assertEqual(rows[180][0]-rows[0][0],30*24*3_600_000)

    def test_missing_history_rejects_entire_episode(self):
        rows=prices();raw=[0]*179+[1]*141
        target,events=c.admit_episodes(rows,raw)
        self.assertEqual(sum(target),0);self.assertFalse(events[0]["has_30d_history"])

    def test_negative_entry_has_no_late_entry_on_recovery(self):
        rows=prices();rows[180][4]="90";rows[181][4]="120"
        target,events=c.admit_episodes(rows,[0]*180+[1]*140)
        self.assertEqual(sum(target),0);self.assertEqual(len(events),1)

    def test_accepted_episode_ignores_later_negative_momentum(self):
        rows=prices();rows[181][4]="80"
        target,_=c.admit_episodes(rows,[0]*180+[1]*20+[0]*120)
        self.assertEqual(target[180:200],[1]*20);self.assertEqual(target[200],0)

    def test_rejected_episode_rearms_after_original_flat(self):
        rows=prices();rows[180][4]="90"
        raw=[0]*180+[1]*5+[0]+[1]*5+[0]*129
        target,events=c.admit_episodes(rows,raw)
        self.assertEqual(sum(target[180:185]),0);self.assertEqual(sum(target[186:191]),5)
        self.assertEqual([e["accepted"] for e in events],[False,True])

    def test_warm_start_checks_last_known_decision_as_fresh_admission(self):
        rows=prices();raw=[0]*175+[1]*50+[0]*95
        target,_=c.admit_episodes(rows,raw,180,250)
        self.assertEqual(target[180],1);self.assertEqual(sum(target[:180]),0)

    def test_extra_latency_cannot_use_later_execution_bar_context(self):
        rows=prices();rows[180][4]="90";rows[181][4]="120"
        raw=[0]*180+[1]*140
        target,_=c.admit_episodes(rows,raw,180,318)
        out=b.simulate(rows,target,182,320,10,5,lag=2)
        self.assertEqual(out["metrics"]["fills"],0)

    def test_next_open_execution_and_signal_availability(self):
        rows=prices();raw=[0]*180+[1]*10+[0]*130
        target,_=c.admit_episodes(rows,raw,180,319)
        out=b.simulate(rows,target,181,320,10,5)
        buy=out["fills"][0]
        self.assertEqual(buy["fill_ms"],rows[181][0])
        self.assertEqual(buy["signal_available_ms"],buy["fill_ms"])
        self.assertEqual(out["positions"][0]["holding_hours"],40)

    def test_no_hidden_time_cap(self):
        rows=prices();raw=[0]*180+[1]*80+[0]*60
        target,_=c.admit_episodes(rows,raw)
        out=b.simulate(rows,target,181,320,10,5)
        self.assertEqual(out["positions"][0]["holding_hours"],320)

    def test_terminal_close_keeps_original_reason(self):
        rows=prices();raw=[0]*180+[1]*140
        target,_=c.admit_episodes(rows,raw,180,199)
        out=b.simulate(rows,target,181,200,10,5)
        self.assertEqual(out["positions"][0]["exit_reason"],"terminal_close")

    def test_prefix_and_future_price_independence(self):
        rows=prices();raw=[0]*180+[1]*20+[0]*5+[1]*60+[0]*55
        target,_=c.admit_episodes(rows,raw,180,319)
        for cut in (181,199,210,270):
            self.assertEqual(c.admit_episodes(rows,raw,180,cut)[0][:cut],target[:cut])
        altered=[r[:] for r in rows];altered[290][4]="1"
        self.assertEqual(c.admit_episodes(altered,raw,180,280)[0],c.admit_episodes(rows,raw,180,280)[0])

    def test_independent_decimal_interval_scan_and_cash_ledger(self):
        rows=prices();rows[180][4]="90"
        raw=[0]*180+[1]*20+[0]*5+[1]*60+[0]*55
        target,_=c.admit_episodes(rows,raw,180,319)
        oracle=c.independent_admission(rows,raw,180,319)
        self.assertEqual(target,oracle)
        out=b.simulate(rows,target,181,320,25,15)
        independent=b.independent_accounting(rows,oracle,181,320,25,15)
        self.assertLess(max(abs(x["equity"]-y) for x,y in zip(out["equity_curve"],independent["equity"])),1e-7)
        self.assertEqual(out["metrics"]["fills"],2)

    def test_invalid_targets_and_ranges_rejected(self):
        rows=prices()
        with self.assertRaises(ValueError):c.admit_episodes(rows,[0]*319+[.5])
        with self.assertRaises(ValueError):c.admit_episodes(rows,[0]*320,200,100)

if __name__=="__main__":
    unittest.main()
