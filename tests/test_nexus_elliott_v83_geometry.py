"""V83 synthetic source-time and impulse-shape checks; research only."""
import unittest
from decimal import Decimal as D
from research.elliott_v82_causal_degree_observer.observer_v82 import Minute, Witness
from research.elliott_v83_impulse_geometry.geometry_v83 import check_candidate

START = 1709251200000
STEP = 60000
CENTERS = (10, 20, 30, 40, 50, 60)
DECISION = START + 80 * STEP

def fixture(prices=(100, 110, 105, 125, 118, 132), bearish=False):
    if bearish:
        prices = tuple(400 - x for x in prices)
    rows = []
    for i in range(80):
        j = min(max((i - 10) // 10, 0), 4)
        portion = D(min(max(i - CENTERS[j], 0), 10)) / D(10)
        price = D(prices[j]) + (D(prices[j+1]) - D(prices[j])) * portion
        rows.append(Minute(START + i*STEP, price + D("0.01"), price - D("0.01")))
    pivots = []
    for i, (center, price) in enumerate(zip(CENTERS, prices)):
        is_high = (i % 2 == 1) if not bearish else (i % 2 == 0)
        m = rows[center]
        rows[center] = Minute(m.ms, D(price) if is_high else m.high,
                             m.low if is_high else D(price))
        pivots.append(Witness("high" if is_high else "low", m.ms, center,
                              m.ms + 4*STEP, str(price), "synthetic"))
    return rows, pivots

class V83GeometryTests(unittest.TestCase):
    def evaluate(self, prices=(100,110,105,125,118,132), bearish=False):
        rows, pivots = fixture(prices, bearish=bearish)
        return check_candidate(pivots[0], pivots[-1], pivots[1:-1], rows, DECISION)

    def test_valid_bull_and_bear_are_not_trades(self):
        for bearish in (False, True):
            with self.subTest(bearish=bearish):
                result = self.evaluate(bearish=bearish)
                self.assertTrue(result["motive_geometry_pass"])
                self.assertFalse(result["complete_recursive_elliott"])
                self.assertFalse(result["entry_signal"])
                self.assertFalse(result["paper_eligible"])
                self.assertIsNone(result["pnl"])

    def test_hard_geometric_invalidations(self):
        cases = (
            ((100,110,99,125,118,132), "WAVE2_BREACHES_ORIGIN"),
            ((100,110,105,109,111,132), "WAVE3_NOT_BEYOND_WAVE1"),
            ((100,110,105,125,109,132), "WAVE4_OVERLAPS_WAVE1_NONDIAGONAL"),
            ((100,110,106,112,111,129), "WAVE3_IS_SHORTEST"),
            ((100,110,105,125,118,122), "WAVE5_TRUNCATED_OR_NOT_EXTREME"),
        )
        for prices, expected in cases:
            with self.subTest(reason=expected):
                result = self.evaluate(prices)
                self.assertFalse(result["motive_geometry_pass"])
                self.assertIn(expected, result["rule_failures"])

    def test_unverified_extra_child_fails_closed(self):
        rows, p = fixture()
        result = check_candidate(p[0], p[-1], [*p[1:-1], p[2]], rows, DECISION)
        self.assertEqual(result["state"], "NOT_FIVE_LEG_SKELETON")
        self.assertFalse(result["motive_geometry_pass"])

    def test_source_price_mismatch_fails_closed(self):
        rows, p = fixture()
        w = p[1]
        bad = Witness(w.kind, w.center_ms, w.source_minute_index,
                      w.confirmed_ms, "999", w.degree)
        with self.assertRaisesRegex(ValueError, "source price mismatch"):
            check_candidate(p[0], p[-1], [bad, *p[2:-1]], rows, DECISION)

    def test_future_pivot_confirmation_fails_closed(self):
        rows, p = fixture()
        w = p[1]
        future = Witness(w.kind, w.center_ms, w.source_minute_index,
                         DECISION + STEP, w.price, w.degree)
        with self.assertRaisesRegex(ValueError, "future"):
            check_candidate(p[0], p[-1], [future, *p[2:-1]], rows, DECISION)

    def test_missing_closed_minute_source_rejected(self):
        rows, p = fixture()
        with self.assertRaisesRegex(ValueError, "unavailable"):
            check_candidate(p[0], p[-1], p[1:-1], rows[:-1], DECISION)

    def test_raw_source_gap_rejected(self):
        rows, p = fixture()
        x = rows[45]
        rows[45] = Minute(x.ms + STEP, x.high, x.low)
        with self.assertRaisesRegex(ValueError, "gap"):
            check_candidate(p[0], p[-1], p[1:-1], rows, DECISION)

    def test_intraleg_wick_breach_rejected(self):
        rows, p = fixture()
        candle = rows[16]
        rows[16] = Minute(candle.ms, D(150), candle.low)
        result = check_candidate(p[0], p[-1], p[1:-1], rows, DECISION)
        self.assertFalse(result["motive_geometry_pass"])
        self.assertIn("LEG1_INTERVENING_HIGH_EXCEEDS_ENDPOINT",
                      result["physical_failures"])

    def test_valid_future_tail_invariance(self):
        rows, p = fixture()
        first = check_candidate(p[0], p[-1], p[1:-1], rows, DECISION)
        tail = [Minute(DECISION + i*STEP, D(900), D(1)) for i in range(25)]
        second = check_candidate(p[0], p[-1], p[1:-1], rows + tail, DECISION)
        self.assertEqual(first, second)

    def test_unavailable_future_tail_not_required(self):
        rows, p = fixture()
        first = check_candidate(p[0], p[-1], p[1:-1], rows, DECISION)
        # A future incomplete bar must not alter a historical as-of decision.
        rows.append(Minute(DECISION + STEP, D(1), D(2)))
        second = check_candidate(p[0], p[-1], p[1:-1], rows, DECISION)
        self.assertEqual(first, second)

    def test_misordered_child_centers_rejected(self):
        rows, p = fixture()
        with self.assertRaisesRegex(ValueError, "not increasing"):
            check_candidate(p[0], p[-1], p[1:-1][::-1], rows, DECISION)
