"""V79 public trade-print milliseconds detect historical exit ordering.

A test-level price touch is not evidence of an executable bid/ask fill.
Synthetic mini gzip fixtures use the same schema as physical Bybit files.
"""
from __future__ import annotations
import csv,gzip,tempfile,unittest
from datetime import datetime,timezone
from decimal import Decimal
from pathlib import Path
from raw_tick_order_v79 import (
    parse_raw_window,UTCmillis,order,D,
    RESEARCH_ONLY,ENTRY_SIGNAL,PAPER_ELIGIBLE,LIVE_ENABLED,
    ENTRY_TIME,
)

T0=UTCmillis(ENTRY_TIME)
def thresholds():
    return {
        "conservative":{"stop":Decimal("95"),"one_r":Decimal("105")},
        "stress":{"stop":Decimal("97"),"one_r":Decimal("103")},
    }
def row(offset_ms,price,side="buy",volume="1",rpi="0"):
    return [str(offset_ms),str(T0+offset_ms),str(price),volume,side,rpi]

class V79PublicTradePrintOrderTests(unittest.TestCase):
    def make_source(self,records,header=None):
        tmp=tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        f=Path(tmp.name)/"physical.csv.gz"
        with gzip.open(f,"wt",encoding="utf8",newline="") as stream:
            writer=csv.writer(stream)
            writer.writerow(header or ["id","timestamp","price","volume","side","rpi"])
            writer.writerows(records)
        return f
    def test_stop_first_not_later_high_fake_profit(self):
        f=self.make_source([
          row(0,"100"),row(1000,"94","sell"),
          row(2000,"106"),row(3000,"99")])
        count,inbar,ohlc,first=parse_raw_window(f,T0,T0+900000,thresholds())
        self.assertEqual((count,inbar),(4,4))
        self.assertEqual(ohlc["high"],Decimal(106))
        self.assertEqual(ohlc["low"],Decimal(94))
        for p in first.values():
            self.assertEqual(order(p["one_r"],p["stop"]),"STOP_TRADE_PRICE_FIRST")
    def test_one_r_first_if_independent_print_is_earlier(self):
        f=self.make_source([row(0,"100"),row(500,"106"),row(900,"94")])
        _,_,_,found=parse_raw_window(f,T0,T0+900000,thresholds())
        for p in found.values():
            self.assertEqual(order(p["one_r"],p["stop"]),"ONE_R_TRADE_PRICE_FIRST")
    def test_same_ms_is_unresolved_not_ordered_by_file(self):
        f=self.make_source([row(0,"100"),row(100,"94"),row(100,"106")])
        _,_,_,found=parse_raw_window(f,T0,T0+900000,thresholds())
        for p in found.values():
            self.assertEqual(order(p["one_r"],p["stop"]),"SAME_MILLISECOND_ORDER_UNRESOLVED")
    def test_when_either_threshold_absent_no_timing_claim(self):
        f=self.make_source([row(0,"100"),row(100,"101")])
        _,_,_,found=parse_raw_window(f,T0,T0+900000,thresholds())
        self.assertEqual(order(found["conservative"]["one_r"],
                               found["conservative"]["stop"]),
                         "ONE_OR_BOTH_THRESHOLDS_NEVER_TOUCHED")
    def test_timestamp_order_must_be_nondecreasing(self):
        f=self.make_source([row(1500,"100"),row(1000,"95")])
        with self.assertRaisesRegex(ValueError,"NOT_CHRONOLOGICALLY_ORDERED"):
            parse_raw_window(f,T0,T0+900000,thresholds())
    def test_wrong_csv_schema_rejected(self):
        f=self.make_source([row(0,"100")],header=["bad","timestamp","price","volume","side","rpi"])
        with self.assertRaisesRegex(ValueError,"SOURCE_GZIP_HEADER_CHANGED"):
            parse_raw_window(f,T0,T0+900000,thresholds())
    def test_bad_side_volume_or_utc_day_rejected(self):
        for bad in ([row(0,"100",side="maker")],
                    [row(0,"100",volume="-2")],
                    [["id",str(T0-86400000),"100","1","buy","0"]]):
            with self.subTest(bad=bad):
                f=self.make_source(bad)
                with self.assertRaises(ValueError):
                    parse_raw_window(f,T0,T0+900000,thresholds())
    def test_no_window_prints_not_fabricated(self):
        f=self.make_source([row(900001,"100")])
        with self.assertRaisesRegex(ValueError,"NO_PHYSICAL_TRADES"):
            parse_raw_window(f,T0,T0+900000,thresholds())
    def test_decimal_prices_refuse_float_nan(self):
        for v in (float("nan"),float("inf"),True,"NaN","0","-1"):
            with self.subTest(value=str(v)):
                with self.assertRaises(ValueError):D(v)
    def test_frozen_historical_window_and_research_only(self):
        self.assertEqual(ENTRY_TIME,"2025-09-11T12:15:00Z")
        self.assertEqual(UTCmillis("2025-09-11T12:30:00Z")-T0,900000)
        self.assertTrue(RESEARCH_ONLY)
        self.assertFalse(ENTRY_SIGNAL or PAPER_ELIGIBLE or LIVE_ENABLED)

if __name__=="__main__":
    unittest.main()
