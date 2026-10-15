"""Independent geometry counterexamples and point-in-time visibility checks."""
import unittest
from dataclasses import replace
from nexus_elliott_five_swing_review import ConfirmedPivot, review_five_swing_setup


def pattern(prices=(100, 106, 103, 112, 108, 115, 107)):
    return [ConfirmedPivot(kind, i * 8, i * 8 + 3, price)
            for i, (kind, price) in enumerate(zip(
                ("low", "high", "low", "high", "low", "high", "low"), prices))]


class ElliottStructureReviewTests(unittest.TestCase):
    def test_known_shape_and_partial_classification_boundary(self):
        r = review_five_swing_setup(pattern(), 52)
        self.assertIsNotNone(r)
        self.assertEqual(r["identity"], (0, 40))
        self.assertEqual(r["earliest_decision_index"], 52)
        self.assertFalse(r["complete_elliott_count"])
        self.assertFalse(r["entry_signal"])

    def test_cannot_backdate_confirmation(self):
        for at in range(52):
            self.assertIsNone(review_five_swing_setup(pattern(), at))

    def test_every_prefix_and_unobserved_future_tail_match(self):
        base = pattern()
        future = [ConfirmedPivot("high", 90, 93, "NaN"),
                  ConfirmedPivot("low", 100, 103, -999)]
        for at in range(84):
            prefix = [p for p in base if p.confirmed_at < at]
            self.assertEqual(review_five_swing_setup(base + future, at),
                             review_five_swing_setup(prefix, at))

    def test_second_swing_cannot_erase_origin(self):
        for price in (100, 99):
            p = pattern(); p[2] = replace(p[2], price=price)
            self.assertIsNone(review_five_swing_setup(p, 52))

    def test_fourth_swing_cannot_overlap_first(self):
        for price in (106, 105):
            p = pattern(); p[4] = replace(p[4], price=price)
            self.assertIsNone(review_five_swing_setup(p, 52))

    def test_third_swing_shortest_rejected(self):
        self.assertIsNone(review_five_swing_setup(pattern((100, 108, 105, 111, 109, 118, 108)), 52))

    def test_relative_shortest_rejected_when_absolute_third_not_shortest(self):
        # Absolute third is 10.5 > 10; relative third is 10.5/109 < 10/100.
        self.assertIsNone(review_five_swing_setup(pattern((100, 110, 109, "119.5", 111, 131, 115)), 52))

    def test_absolute_shortest_rejected_when_relative_third_not_shortest(self):
        # Absolute third is 18 < 19; relative third is 18/119 > 19/136.
        self.assertIsNone(review_five_swing_setup(pattern((100, 120, 119, 137, 136, 155, 125)), 52))

    def test_new_parent_correction_cannot_erase_origin(self):
        for price in (100, 99):
            p = pattern(); p[6] = replace(p[6], price=price)
            self.assertIsNone(review_five_swing_setup(p, 52))

    def test_truncated_fifth_outside_review_scope(self):
        p = pattern(); p[5] = replace(p[5], price=111)
        self.assertIsNone(review_five_swing_setup(p, 52))

    def test_retracement_outside_fixed_engineering_band(self):
        for price in (114, 101):
            p = pattern(); p[6] = replace(p[6], price=price)
            self.assertIsNone(review_five_swing_setup(p, 52))

    def test_expiry_boundary(self):
        self.assertIsNotNone(review_five_swing_setup(pattern(), 83))
        self.assertIsNone(review_five_swing_setup(pattern(), 84))

    def test_malformed_confirmation_order_and_alternation_rejected(self):
        for index, change in [(3, {"confirmed_at": 28}), (4, {"kind": "high"}),
                              (1, {"index": 0, "confirmed_at": 3})]:
            p = pattern(); p[index] = replace(p[index], **change)
            self.assertIsNone(review_five_swing_setup(p, 52))

    def test_nonfinite_nonpositive_and_nonnumeric_prices_rejected(self):
        for price in ("NaN", "Infinity", 0, -1, "bad"):
            p = pattern(); p[4] = replace(p[4], price=price)
            self.assertIsNone(review_five_swing_setup(p, 52))

    def test_invalid_decision_index_rejected(self):
        for at in (-1, True, 52.0):
            with self.assertRaises(ValueError): review_five_swing_setup(pattern(), at)

    def test_span_bound_and_latest_known_shape(self):
        p = [replace(x, index=x.index * 5, confirmed_at=x.index * 5 + 3) for x in pattern()]
        self.assertIsNone(review_five_swing_setup(p, 244))
        old = [ConfirmedPivot("high", 0, 3, 150)]
        shifted = [replace(x, index=x.index + 8, confirmed_at=x.confirmed_at + 8) for x in pattern()]
        self.assertEqual(review_five_swing_setup(old + shifted, 60),
                         review_five_swing_setup(shifted, 60))


if __name__ == "__main__":
    unittest.main()
