"""Exact exploratory AUC audit tests. Unseen edge is NEVER inferred."""
from pathlib import Path
from unittest import TestCase, SkipTest, main
from research import nexus_mr40_exploratory_regime_discrimination_v1 as m


class PortablePermutationTests(TestCase):
    def test_perfect_separation_two_sided_tail(self):
        x=m.exact_auc_test([0,1,2,3],[False,False,True,True])
        self.assertEqual(x["auc_winner_higher"],1)
        self.assertEqual(x["permutations"],6)
        self.assertEqual(x["exact_two_sided_p"],round(2/6,8))

    def test_complete_reverse_does_not_flip_sign(self):
        x=m.exact_auc_test([0,1,2,3],[True,True,False,False])
        self.assertEqual(x["auc_winner_higher"],0)
        self.assertEqual(x["exact_two_sided_p"],round(2/6,8))

    def test_all_values_tied_are_uninformative(self):
        x=m.exact_auc_test([1,1,1,1],[True,False,True,False])
        self.assertEqual(x["auc_winner_higher"],0.5)
        self.assertEqual(x["exact_two_sided_p"],1)

    def test_one_tie_pair_midrank_exact(self):
        x=m.exact_auc_test([1,2,2,3],[False,False,True,True])
        self.assertEqual(x["auc_winner_higher"],0.875)

    def test_cohort_all_same_label_refused(self):
        with self.assertRaisesRegex(ValueError,"bad_binary_cohort"):
            m.exact_auc_test([1,2,3],[True,True,True])

    def test_nonfinite_rejected(self):
        with self.assertRaisesRegex(ValueError,"nonfinite_feature"):
            m.exact_auc_test([1,float("nan"),3],[False,True,True])

    def test_no_permutation_approximation_for_large_n(self):
        with self.assertRaisesRegex(ValueError,"exact_enumeration_limit"):
            m.exact_auc_test(list(range(26)),[i>2 for i in range(26)])


class RealPinnedEvidenceTests(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root=Path(__file__).resolve().parents[1]
        needed=[cls.root/"research"/m.PROTOCOL,cls.root/"results"/m.SOURCE,
                cls.root/"results"/m.OUTPUT]
        if not all(f.is_file() for f in needed):
            raise SkipTest("pinned 47-trade research files only present on Laptop1")

    def test_actual_47_exact_nonpredictive_comparisons(self):
        out=m.inspect(self.root)
        self.assertEqual(len(out["results"]),4)
        self.assertEqual(out["digest"],"3c20c5ed720117f63312e01b98adb53af4c27eefa71d259dbef9ecbf112e9f09")
        self.assertTrue(all(x["multiplicity_corrected_p_4_tests"]>0.05 for x in out["results"]))
        self.assertFalse(out["candidate_filter_authorized"])

    def test_actual_file_SHA_and_no_overwrite(self):
        a=self.root/"results"/m.OUTPUT
        self.assertEqual(m.file_sha(a),"e2ac5e149a177ff970d20bf2705ad2673c11faebe93158083a61f394ce90c17b")


if __name__=="__main__":
    main()
