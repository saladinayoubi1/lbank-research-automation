"""No-future and prior-30-low-break contract, synthetic market only."""
import unittest
from research.nexus_mr40_structure_break_audit_v1 import new_low_break, fisher_loss_enrichment


class StructureBreakTest(unittest.TestCase):
    def rows(self):
        return [[i*14400000,"100","102","90","100"] for i in range(35)]

    def test_new_lower_close(self):
        rows=self.rows()
        rows[30][4]="89.999"
        self.assertTrue(new_low_break(rows,30))

    def test_equal_previous_low_is_not_break(self):
        rows=self.rows()
        rows[30][4]="90"
        self.assertFalse(new_low_break(rows,30))

    def test_signal_bar_low_not_part_of_prior_30(self):
        rows=self.rows()
        rows[30][3]="1"
        rows[30][4]="89"
        self.assertTrue(new_low_break(rows,30))

    def test_future_mutation_does_not_change_prior_decision(self):
        rows=self.rows()
        rows[30][4]="89"
        before=new_low_break(rows,30)
        rows[31][3]="0.01"
        rows[34][3]="0.01"
        self.assertEqual(new_low_break(rows,30),before)

    def test_prior_window_exactly_30(self):
        rows=self.rows()
        rows[0][3]="1"
        rows[31][4]="89"
        self.assertTrue(new_low_break(rows,31))
        rows[1][3]="50"
        self.assertFalse(new_low_break(rows,31))

    def test_requires_history(self):
        with self.assertRaises(ValueError):
            new_low_break(self.rows(),29)

    def test_fisher_equal_groups(self):
        self.assertEqual(fisher_loss_enrichment(0,0,19,6),1.)
        self.assertEqual(fisher_loss_enrichment(19,6,19,6),1.)
        self.assertGreaterEqual(fisher_loss_enrichment(1,2,18,4),0.)


if __name__=="__main__":
    unittest.main()
