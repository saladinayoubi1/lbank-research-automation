from decimal import Decimal as D
import unittest

import test_nexus_fx_bars_research as fixtures
from nexus_fx_bars_research import BarGrid
from nexus_fx_mtf_research import FrameRequest, build_snapshot
from nexus_fx_quote_research import TickContractError


class MultiFrameTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.BarsTests()
        self.fast = FrameRequest("fast", BarGrid(10, 0, "BID"), 1)
        self.slow = FrameRequest("slow", BarGrid(20, 0, "BID"), 1)

    def test_alignment_between_boundaries(self):
        s = build_snapshot(self.fixture.window(), (self.fast, self.slow), 30)
        self.assertEqual([x.bars[-1].end_ms for x in s.frames], [30, 20])
        self.assertEqual([x.bars[-1].close for x in s.frames], [D(106), D(104)])
        self.assertEqual(s.observed_through_ms, 30)
        self.assertTrue(s.research_only)

    def test_simultaneous_boundary(self):
        s = build_snapshot(self.fixture.window(), (self.fast, self.slow), 20)
        self.assertEqual([x.bars[-1].end_ms for x in s.frames], [20, 20])
        self.assertEqual([x.bars[-1].available_ms for x in s.frames], [20, 20])
        self.assertEqual([x.bars[-1].close for x in s.frames], [D(104), D(104)])

    def test_observed_not_clock_only(self):
        w = self.fixture.window((0, 9, 10, 19, 23, 30))
        with self.assertRaises(TickContractError):
            build_snapshot(w, (self.fast, self.slow), 20)
        s = build_snapshot(w, (self.fast, self.slow), 23)
        self.assertEqual([x.bars[-1].available_ms for x in s.frames], [23, 23])

    def test_future_prefix_independence(self):
        a = self.fixture.window()
        b = self.fixture.window(values=(100, 101, 102, 103, 104, 105, 900, 999))
        self.assertEqual(build_snapshot(a, (self.fast, self.slow), 20),
                         build_snapshot(b, (self.fast, self.slow), 20))

    def test_missing_lower_frame_rejects_all(self):
        w = self.fixture.window((0, 1, 20, 21, 30, 40))
        fast = FrameRequest("fast", self.fast.grid, 4)
        with self.assertRaises(TickContractError):
            build_snapshot(w, (self.slow, fast), 40)

    def test_insufficient_higher_frame_rejects_all(self):
        with self.assertRaises(TickContractError):
            build_snapshot(self.fixture.window(), (self.fast, self.slow), 10)

    def test_explicit_anchor_and_basis(self):
        w = self.fixture.window((0, 5, 9, 15, 20, 25, 30))
        anchored = FrameRequest("anchored", BarGrid(10, 5, "ASK"), 2)
        s = build_snapshot(w, (self.fast, anchored), 30)
        self.assertEqual([x.end_ms for x in s.frames[1].bars], [15, 25])
        self.assertEqual(s.frames[1].bars[0].open, D("101.02"))

    def test_reject_duplicate_and_mutable_requests(self):
        w = self.fixture.window()
        for req in ((self.fast, self.fast), [self.fast], (), (None,), (self.fast,) * 17):
            with self.assertRaises(TickContractError):
                build_snapshot(w, req, 30)

    def test_invalid_request_and_decision(self):
        for args in (("", self.fast.grid, 1), (" bad", self.fast.grid, 1),
                     ("x", self.fast.grid, True), ("x", self.fast.grid, 0),
                     ("x", None, 1)):
            with self.assertRaises(TickContractError):
                FrameRequest(*args)
        for t in (True, 31):
            with self.assertRaises(TickContractError):
                build_snapshot(self.fixture.window(), (self.fast,), t)

    def test_provenance(self):
        w = self.fixture.window()
        s = build_snapshot(w, (self.fast, self.slow), 30)
        self.assertEqual((s.source_id, s.source_revision, s.instrument, s.prefix_sha256),
                         (w.source_id, w.source_revision, w.instrument, w.expected_sha256))


if __name__ == "__main__":
    unittest.main()
