from decimal import Decimal as D
import unittest
from nexus_fx_quote_research import Instrument, Tick, QuoteWindow, TickContractError, quote_digest
from nexus_fx_bars_research import BarGrid, build_closed_bars
from nexus_fx_bar_cache_research import ClosedBarCache


def window(rev="v1", offset=0):
    ticks=tuple(Tick(t,i,D(100+i+offset),D(100+i+offset)+D(".02"))
                for i,t in enumerate((0,2,9,10,14,20,23,30)))
    return QuoteWindow(Instrument("XAUUSD",D(".01"),D(1),"USD"),
                       "synthetic",rev,0,30,100,quote_digest(ticks),ticks)


class CacheTests(unittest.TestCase):
    def test_cold_warm_exact(self):
        w=window();c=ClosedBarCache(w);g=BarGrid(10,0,"BID")
        expected=build_closed_bars(w,g,30)
        first=c.get(w,g,30)
        self.assertEqual(first,expected)
        self.assertIs(first,c.get(w,g,30))
        self.assertEqual(c.stats,(1,1,1))

    def test_grid_cutoff_separation(self):
        w=window();c=ClosedBarCache(w)
        for g in (BarGrid(10,0,"BID"),BarGrid(10,0,"ASK"),
                  BarGrid(10,5,"BID"),BarGrid(5,0,"MID")):
            for t in (10,20,30):
                self.assertEqual(c.get(w,g,t),build_closed_bars(w,g,t))
        self.assertEqual(c.stats,(0,12,12))

    def test_window_identity_boundary(self):
        w=window();c=ClosedBarCache(w);g=BarGrid(10,0,"BID")
        c.get(w,g,30)
        for other in (window(),window("v2"),window(offset=100)):
            with self.assertRaises(TickContractError):c.get(other,g,30)
        self.assertEqual(c.stats,(0,1,1))

    def test_lru(self):
        w=window();c=ClosedBarCache(w,capacity=2);g=BarGrid(10,0,"BID")
        a=c.get(w,g,10);b=c.get(w,g,20)
        self.assertIs(a,c.get(w,g,10))
        c.get(w,g,30)
        self.assertIs(a,c.get(w,g,10))
        rebuilt=c.get(w,g,20)
        self.assertEqual(b,rebuilt)
        self.assertIsNot(b,rebuilt)
        self.assertEqual(c.stats,(2,4,2))

    def test_rejected_input_not_cached(self):
        w=window();c=ClosedBarCache(w);g=BarGrid(10,0,"BID")
        for cutoff in (True,-1,31):
            with self.assertRaises(TickContractError):c.get(w,g,cutoff)
        with self.assertRaises(TickContractError):c.get(w,"BID",30)
        self.assertEqual(c.stats,(0,0,0))

    def test_capacity_bounds(self):
        for v in (0,33,True):
            with self.assertRaises(TickContractError):ClosedBarCache(window(),capacity=v)

    def test_missing_bars_preserved(self):
        w=window();c=ClosedBarCache(w);g=BarGrid(1,0,"BID")
        s=c.get(w,g,30)
        self.assertTrue(s.missing_starts)
        self.assertEqual(s,build_closed_bars(w,g,30))


if __name__=="__main__":
    unittest.main()
