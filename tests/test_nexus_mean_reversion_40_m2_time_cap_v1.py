from __future__ import annotations
import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"research"))
import nexus_mean_reversion_40_m2_time_cap_v1 as c
import nexus_mean_reversion_40_m2_retest_v1 as b
def prices(n):
    start=b.ms("2026-01-01")
    return [[start+i*b.STEP,"100","102","98","100","1"] for i in range(n)]
class TimeCapTests(unittest.TestCase):
    def test_exactly_forty_active_targets_then_expiry(self):
        out,event=c.cap40([0]*3+[1]*80)
        self.assertEqual(out[3:43],[1]*40);self.assertEqual(out[43:],[0]*40)
        self.assertTrue(event[43]);self.assertEqual(sum(event),1)
    def test_no_reentry_during_same_oversold_episode(self):
        out,event=c.cap40([1]*150)
        self.assertEqual(sum(out),40);self.assertEqual(sum(event),1)
    def test_mean_exit_rearms_next_oversold_episode(self):
        out,event=c.cap40([1]*60+[0]+[1]*60)
        self.assertEqual(sum(out[:60]),40);self.assertEqual(out[60],0)
        self.assertEqual(sum(out[61:]),40);self.assertEqual(sum(event),2)
    def test_mean_exit_takes_priority_on_expiry_boundary(self):
        out,event=c.cap40([1]*40+[0]*3)
        self.assertEqual(sum(event),0);self.assertEqual(out[40],0)
    def test_expiry_signal_sells_at_next_open_after_160_hours(self):
        rows=prices(120);target,event=c.cap40([0]*3+[1]*117)
        result=c.annotate_exits(b.simulate(rows,target,0,120,10,5),event,1)
        t=result["positions"][0];f=result["fills"][-1]
        self.assertEqual(t["holding_hours"],160)
        self.assertEqual(t["exit_reason"],"time_cap_closed_bar_signal")
        self.assertEqual(f["fill_ms"],rows[44][0])
        self.assertEqual(f["signal_available_ms"],f["fill_ms"])
        self.assertEqual(result["metrics"]["time_cap_exits"],1)
    def test_extra_latency_still_limits_actual_episode_length(self):
        rows=prices(120);target,event=c.cap40([0]*3+[1]*117)
        result=c.annotate_exits(b.simulate(rows,target,0,120,10,5,lag=2),event,2)
        self.assertEqual(result["positions"][0]["holding_hours"],160)
        self.assertEqual(result["fills"][-1]["bar_index"],45)
    def test_forced_end_is_not_relabelled_as_time_exit(self):
        rows=prices(20);target,event=c.cap40([0]*3+[1]*17)
        result=c.annotate_exits(b.simulate(rows,target,0,20,10,5),event,1)
        self.assertEqual(result["positions"][0]["exit_reason"],"terminal_close")
        self.assertEqual(result["metrics"]["terminal_exits"],1)
        self.assertEqual(result["metrics"]["time_cap_exits"],0)
    def test_prefix_causality(self):
        raw=[0]*4+[1]*70+[0]*3+[1]*80
        for cut in (20,43,44,75,100):
            self.assertEqual(c.cap40(raw)[0][:cut],c.cap40(raw[:cut])[0])
    def test_nonbinary_targets_rejected(self):
        with self.assertRaises(ValueError):c.cap40([0,1,.5])
    def test_accounting_and_no_phantom_orders_after_expiry(self):
        rows=prices(120);target,event=c.cap40([0]*3+[1]*117)
        out=b.simulate(rows,target,0,120,10,5)
        independent=b.independent_accounting(rows,target,0,120,10,5)
        self.assertEqual(out["metrics"]["fills"],2)
        self.assertLess(max(abs(x["equity"]-y) for x,y in zip(out["equity_curve"],independent["equity"])),1e-7)
if __name__=="__main__":unittest.main()
