"""Isolated closed-bar synthetic tests, no private exchange connection."""
import unittest
from research.nexus_mr40_independent_closed_signal_v1 import ClosedMR40,STEP


class TestIndependentClosedMR40(unittest.TestCase):
    @staticmethod
    def frame(n=204):
        close=[80]*40+[99+(2*(k%2)) for k in range(n-40)]
        close[200]=96;close[201]=95;close[202]=120
        return [[i*STEP,str(c),str(c+1),str(c-1),str(c),"10"] for i,c in enumerate(close)]

    def test_first_closed_signal_after_momentum(self):
        s=ClosedMR40()
        out=[s.feed(r,confirmed=True,source_verified=True) for r in self.frame()]
        self.assertTrue(out[200].first_entry_close)
        self.assertTrue(out[200].final_target)
        self.assertTrue(out[201].final_target)
        self.assertFalse(out[201].first_entry_close)
        self.assertTrue(out[202].natural_exit_close)
        self.assertFalse(out[202].final_target)
        self.assertFalse(out[200].executable)

    def test_no_lookahead_future_data_mutation(self):
        a=self.frame()
        b=self.frame()
        b[201][4]="500"
        b[201][2]="501"
        a0=ClosedMR40();b0=ClosedMR40()
        ea=eb=None
        for i in range(201):
            ea=a0.feed(a[i],confirmed=True,source_verified=True)
            eb=b0.feed(b[i],confirmed=True,source_verified=True)
        self.assertEqual(ea,eb)
        self.assertTrue(ea.first_entry_close)

    def test_unconfirmed_bar_blocks_and_suspends(self):
        engine=ClosedMR40()
        with self.assertRaisesRegex(ValueError,"unconfirmed"):
            engine.feed(self.frame()[0],confirmed=False,source_verified=True)
        with self.assertRaisesRegex(ValueError,"suspended"):
            engine.feed(self.frame()[0],confirmed=True,source_verified=True)

    def test_unverified_source_blocks(self):
        e=ClosedMR40()
        with self.assertRaisesRegex(ValueError,"unverified"):
            e.feed(self.frame()[0],confirmed=True,source_verified=False)

    def test_missing_4h_interval_fails_closed(self):
        e=ClosedMR40();rs=self.frame()
        e.feed(rs[0],confirmed=True,source_verified=True)
        with self.assertRaisesRegex(ValueError,"missing_or_nonmonotonic"):
            e.feed(rs[2],confirmed=True,source_verified=True)
        self.assertTrue(e.suspended)

    def test_ohlc_bad_fails_closed(self):
        e=ClosedMR40();r=self.frame()[0]
        r[2]="1"
        with self.assertRaisesRegex(ValueError,"invalid_4h"):
            e.feed(r,confirmed=True,source_verified=True)

    def test_no_180_bar_history_no_admission(self):
        e=ClosedMR40()
        for r in self.frame(204)[:180]:
            q=e.feed(r,confirmed=True,source_verified=True)
            self.assertFalse(q.final_target)
            self.assertFalse(q.first_entry_close)

    def test_negative_momentum_veto_consumes_episode(self):
        rows=self.frame()
        # Historical C[20]=80; increase it above C[200]=96 without
        # changing the most recent 40 signal inputs, so momentum vetoes.
        rows[20][1]="110";rows[20][2]="111";rows[20][3]="109";rows[20][4]="110"
        e=ClosedMR40()
        out=[e.feed(r,confirmed=True,source_verified=True) for r in rows]
        self.assertFalse(out[200].episode_admitted)
        self.assertFalse(out[200].first_entry_close)
        self.assertFalse(out[201].final_target)
        self.assertFalse(out[202].natural_exit_close)


if __name__=="__main__":
    unittest.main()
