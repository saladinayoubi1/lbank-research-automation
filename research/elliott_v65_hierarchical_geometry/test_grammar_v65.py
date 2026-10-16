"""V65 research-only nested A-B-C hierarchy regressions."""
import unittest
from dataclasses import replace
from grammar_v65 import Vertex,assess_seven_moves,RESEARCH_ONLY,ENTRY_SIGNAL,LIVE_ENABLED

def v(values):
    return tuple(Vertex(i+10,"low" if i%2==0 else "high",str(x))
                 for i,x in enumerate(values))
ETH=(2492.76,2496.32,2495.33,2498.50,2496.03,2497.78,2496.65,2498.71)

class V65NestedCorrectionTests(unittest.TestCase):
    def test_eth_historical_two_correction_positions_rejected(self):
        x=assess_seven_moves(v(ETH))
        self.assertEqual(x.valid_expansion_count,0)
        self.assertEqual(x.state,"NO_ADMISSIBLE_5_PLUS_ABC_GEOMETRY")
        self.assertEqual(len(x.expansions),2)
        self.assertTrue(x.expansions[1].five_leg_impulse_geometry)
        self.assertFalse(x.expansions[1].countertrend_abc_zigzag_geometry)
        self.assertFalse(x.source_authenticated or x.entry_signal)
    def test_synthetic_second_wave_nested_zigzag_valid_geometry_only(self):
        x=assess_seven_moves(v((100,120,110,115,105,140,125,150)))
        self.assertEqual(x.valid_expansion_count,1)
        self.assertTrue(x.expansions[0].accepted)
        self.assertFalse(x.recursively_complete or x.forward_validated)
    def test_synthetic_fourth_wave_nested_zigzag_valid_geometry_only(self):
        x=assess_seven_moves(v((100,110,105,125,115,120,112,135)))
        self.assertEqual(x.valid_expansion_count,1)
        self.assertTrue(x.expansions[1].accepted)
    def test_cannot_drop_extra_pivots(self):
        with self.assertRaisesRegex(ValueError,"eight"):
            assess_seven_moves(v(ETH)[:-1])
    def test_duplicate_or_out_of_order_center_rejected(self):
        xs=list(v(ETH));xs[2]=replace(xs[2],minute_index=xs[1].minute_index)
        with self.assertRaisesRegex(ValueError,"duplicate"):
            assess_seven_moves(xs)
    def test_wrong_kind_rejected(self):
        xs=list(v(ETH));xs[2]=replace(xs[2],kind="high")
        with self.assertRaisesRegex(ValueError,"alternating"):
            assess_seven_moves(xs)
    def test_no_execution(self):
        self.assertTrue(RESEARCH_ONLY)
        self.assertFalse(ENTRY_SIGNAL or LIVE_ENABLED)
if __name__=="__main__":unittest.main()
