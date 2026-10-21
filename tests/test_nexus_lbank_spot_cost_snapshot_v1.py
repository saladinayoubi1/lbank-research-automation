import copy
from decimal import Decimal
import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("lbank_cost_test", ROOT / "research/nexus_lbank_spot_cost_snapshot_v1.py")
book = importlib.util.module_from_spec(spec)
spec.loader.exec_module(book)


class LBankDepthCostTests(unittest.TestCase):
    def fixture(self):
        return {"result":"true","error_code":0,"ts":100000,
                "data":{"timestamp":100000,"asks":[["101","1"],["103","1"]],
                        "bids":[["99","1"],["97","1"]]}}

    def test_vwap_walks_both_sides_without_double_counting_spread(self):
        levels = book.parse_book(self.fixture(),100000)
        self.assertEqual(book.walk(levels["asks"],Decimal(204),True),Decimal(102))
        self.assertEqual(book.walk(levels["bids"],Decimal(2),False),Decimal(98))
        measured = book.measure(levels,100)
        self.assertEqual(Decimal(measured["full_spread_bps"]),200)
        self.assertEqual(Decimal(measured["buy_shortfall_from_mid_bps"]),100)
        self.assertEqual(Decimal(measured["sell_shortfall_from_mid_bps"]),100)
        self.assertEqual(Decimal(measured["buy_walk_beyond_best_ask_bps"]),0)

    def test_insufficient_depth_never_assumes_a_complete_fill(self):
        levels = book.parse_book(self.fixture(),100000)
        with self.assertRaisesRegex(ValueError,"insufficient_visible_depth"):
            book.walk(levels["asks"],Decimal(205),True)
        with self.assertRaisesRegex(ValueError,"insufficient_visible_depth"):
            book.walk(levels["bids"],Decimal(3),False)

    def test_stale_crossed_and_duplicate_books_are_rejected(self):
        with self.assertRaisesRegex(ValueError,"not_fresh"):
            book.parse_book(self.fixture(),116000)
        crossed = self.fixture()
        crossed["data"]["bids"][0][0] = "102"
        with self.assertRaisesRegex(ValueError,"crossed_book"):
            book.parse_book(crossed,100000)
        duplicate = copy.deepcopy(self.fixture())
        duplicate["data"]["asks"][1][0] = "101"
        with self.assertRaisesRegex(ValueError,"duplicate_depth_price"):
            book.parse_book(duplicate,100000)


if __name__ == "__main__":
    unittest.main()
