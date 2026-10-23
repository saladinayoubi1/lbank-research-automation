"""No-money closed-bar signal -> coordinator replay tests."""
import unittest

from research.nexus_mr40_signal_coordinator_replay_v1 import no_money_replay
from research.nexus_mr40_independent_closed_signal_v1 import STEP


class TestNoMoneyCoordinatorReplay(unittest.TestCase):
    @staticmethod
    def frame():
        closes=[80]*40 + [99+2*(k%2) for k in range(164)]
        closes[200],closes[201],closes[202]=96,95,120
        return [[i*STEP,str(c),str(c+1),str(c-1),str(c),"10"] for i,c in enumerate(closes)]

    def test_one_closed_signal_one_next_open_intent(self):
        x=no_money_replay(self.frame())
        self.assertEqual(x["entry_bars"],[201])
        self.assertEqual(x["exit_bars"],[203])
        self.assertEqual(x["open_kinds"]["ENTRY_NEXT_OPEN"],1)
        self.assertEqual(x["open_kinds"]["NATURAL_EXIT_NEXT_OPEN"],1)
        self.assertFalse(x["end_dummy_unit_held"])

    def test_future_close_cannot_change_past_open_intent(self):
        a=self.frame()
        b=self.frame()
        b[202][4]="70"
        b[202][3]="69"
        ra=no_money_replay(a)
        rb=no_money_replay(b)
        self.assertEqual(ra["entry_bars"],[201])
        self.assertEqual(rb["entry_bars"],[201])

    def test_gap_blocks_no_money_pipeline(self):
        a=self.frame()
        a[202][0]+=STEP
        with self.assertRaisesRegex(ValueError,"missing_4h_bar"):
            no_money_replay(a)

    def test_bad_ohlcv_never_allowed(self):
        a=self.frame()
        a[30][3]="900"
        with self.assertRaisesRegex(ValueError,"invalid_4h"):
            no_money_replay(a)


if __name__=="__main__":
    unittest.main()
