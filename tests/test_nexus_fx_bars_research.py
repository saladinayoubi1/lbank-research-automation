from decimal import Decimal as D, localcontext
import unittest
from nexus_fx_quote_research import Instrument, Tick, QuoteWindow, TickContractError, quote_digest
from nexus_fx_bars_research import BarGrid, build_closed_bars, contiguous_suffix


class BarsTests(unittest.TestCase):
    def window(self, times=(0,2,9,10,14,20,23,30), values=None):
        if values is None:
            values=tuple(100+i for i in range(len(times)))
        ts=tuple(Tick(t,i,D(v),D(v)+D(".02")) for i,(t,v) in enumerate(zip(times,values)))
        return QuoteWindow(Instrument("XAUUSD",D(".01"),D(1),"USD"),
                           "synthetic","v1",ts[0].time_ms,ts[-1].time_ms,100,
                           quote_digest(ts),ts)

    def test_half_open(self):
        s=build_closed_bars(self.window(),BarGrid(10,0,"BID"),20)
        self.assertEqual(len(s.bars),2)
        self.assertEqual((s.bars[0].open,s.bars[0].close,s.bars[0].count),(D(100),D(102),3))
        self.assertEqual(s.bars[1].open,D(103))

    def test_high_low(self):
        s=build_closed_bars(self.window(values=(103,99,101,100,105,106,107,108)),BarGrid(10,0,"BID"),10)
        self.assertEqual((s.bars[0].high,s.bars[0].low),(D(103),D(99)))

    def test_ask_mid(self):
        w=self.window()
        for basis,offset in (("ASK",D(".02")),("MID",D(".01"))):
            self.assertEqual(build_closed_bars(w,BarGrid(10,0,basis),10).bars[0].open,D(100)+offset)

    def test_no_early_availability(self):
        w=self.window((0,2,9,12,20))
        self.assertFalse(build_closed_bars(w,BarGrid(10,0,"BID"),10).bars)
        self.assertEqual(build_closed_bars(w,BarGrid(10,0,"BID"),12).bars[0].available_ms,12)

    def test_future_prefix_independence(self):
        a=self.window()
        b=self.window(values=(100,101,102,103,104,105,500,600))
        g=BarGrid(10,0,"BID")
        self.assertEqual(build_closed_bars(a,g,20),build_closed_bars(b,g,20))

    def test_partial_first_last(self):
        s=build_closed_bars(self.window((3,9,10,15,20,23)),BarGrid(10,0,"BID"),23)
        self.assertEqual([b.start_ms for b in s.bars],[10])

    def test_anchor(self):
        s=build_closed_bars(self.window((3,5,9,15,20,25)),BarGrid(10,5,"BID"),25)
        self.assertEqual([b.start_ms for b in s.bars],[5,15])

    def test_missing_bucket(self):
        s=build_closed_bars(self.window((0,3,25,30)),BarGrid(10,0,"BID"),30)
        self.assertEqual(s.missing_starts,(10,))
        with self.assertRaises(TickContractError):
            contiguous_suffix(s,2)

    def test_missing_latest(self):
        s=build_closed_bars(self.window((0,3,30)),BarGrid(10,0,"BID"),30)
        with self.assertRaises(TickContractError):
            contiguous_suffix(s,1)

    def test_contiguous(self):
        s=build_closed_bars(self.window(),BarGrid(10,0,"BID"),30)
        self.assertEqual([x.start_ms for x in contiguous_suffix(s,2)],[10,20])

    def test_insufficient(self):
        s=build_closed_bars(self.window(),BarGrid(10,0,"BID"),9)
        with self.assertRaises(TickContractError):
            contiguous_suffix(s,1)

    def test_same_timestamp_sequence(self):
        s=build_closed_bars(self.window((0,0,5,10)),BarGrid(10,0,"BID"),10)
        self.assertEqual((s.bars[0].open,s.bars[0].close),(D(100),D(102)))

    def test_invalid_inputs(self):
        for g in ((0,0,"BID"),(10,10,"BID"),(10,0,"LAST"),(True,0,"BID")):
            with self.assertRaises(TickContractError):
                BarGrid(*g)
        with self.assertRaises(TickContractError):
            build_closed_bars(self.window(),BarGrid(10,0,"BID"),31)

    def test_context_independent(self):
        w=self.window()
        g=BarGrid(10,0,"MID")
        expected=build_closed_bars(w,g,30)
        with localcontext() as c:
            c.prec=2
            self.assertEqual(build_closed_bars(w,g,30),expected)


if __name__=="__main__":
    unittest.main()
