"""Synthetic prevention of volume lookahead and false order-flow claims."""
import unittest
from research.nexus_mr40_entry_volume_audit_v1 import features_asof,exact_rank


class MR40VolumeAuditTests(unittest.TestCase):
    def rows(self):
        return [[i*14400000,"100","105","90","95","10"] for i in range(40)]

    def test_two_preregistered_descriptors(self):
        rows=self.rows()
        rows[31]=[31*14400000,"100","102","90","94","20"]
        f=features_asof(rows,31)
        self.assertAlmostEqual(f["relative_base_volume_30"],2)
        self.assertAlmostEqual(f["signed_candle_volume_proxy"],-1)

    def test_future_candle_mutation_does_not_change_volume(self):
        rows=self.rows()
        f=features_asof(rows,31)
        rows[32]=[32*14400000,"2","900","1","500","10000000"]
        self.assertEqual(f,features_asof(rows,31))

    def test_30_bar_previous_window_excludes_bar0_at_j31(self):
        rows=self.rows()
        rows[0][5]="100000"
        self.assertAlmostEqual(features_asof(rows,31)["relative_base_volume_30"],1)

    def test_volume_from_closed_signal_only(self):
        rows=self.rows()
        before=features_asof(rows,31)
        rows[31][5]="100"
        after=features_asof(rows,31)
        self.assertNotEqual(before,after)

    def test_invalid_market_data_fails_closed(self):
        rows=self.rows()
        rows[12][5]="0"
        with self.assertRaises(ValueError):features_asof(rows,31)

    def test_exact_tie_permutation(self):
        r=exact_rank([1.0]*19,[1.0]*6)
        self.assertTrue(r["feature_ties_present"])
        self.assertEqual(r["winner_higher_auc"],.5)
        self.assertEqual(r["exact_two_sided_p"],1.)
        self.assertEqual(r["all_permutations"],177100)

    def test_full_separation_statistic(self):
        r=exact_rank([2.0]*18,[1.0]*4)
        self.assertEqual(r["winner_higher_auc"],1)
        self.assertLess(r["exact_two_sided_p"],.0125)


if __name__=="__main__":
    unittest.main()
