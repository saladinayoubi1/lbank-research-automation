"""Synthetic official-Spot-trades day parity, no network or trading."""
import gzip
import unittest
from decimal import Decimal as D
from research.nexus_mr40_bybit_public_spot_archive_day_parity_v1 import (
    START,STEP1,STEP4,parse_archive,aggregate,rebuilt_from_1m,compare,
    assert_valid_trade
)


class TestBybitArchiveParity(unittest.TestCase):
    @staticmethod
    def frame():
        rows=[(START+i*STEP1,i,D("100")+D(i%5)/100,D("0.01")) for i in range(1440)]
        minute,four=aggregate(rows)
        frozen={ts:v[:5] for ts,v in four.items()}
        return rows,frozen

    def test_full_day_all_1440_minutes_and_6_fourhour(self):
        rows,frozen=self.frame()
        data=compare(rows,frozen,{})
        self.assertEqual(data["trade_count"],1440)
        self.assertEqual(data["one_minute_buckets_present"],1440)
        self.assertTrue(data["strict_day_ohlcv_source_parity_pass"])
        self.assertTrue(all(x["minute_rebuilt_matches_trade_4h"] for x in data["per_bar"]))

    def test_missing_one_minute_fails(self):
        rows,frozen=self.frame()
        rows.pop(10)
        self.assertFalse(compare(rows,frozen,{})["strict_day_ohlcv_source_parity_pass"])

    def test_one_price_cent_plus_delta_rejected(self):
        rows,frozen=self.frame()
        frozen[START][3]+=D("0.02")
        data=compare(rows,frozen,{})
        self.assertFalse(data["strict_day_ohlcv_source_parity_pass"])

    def test_base_volume_overpointonepercent_fails(self):
        rows,frozen=self.frame()
        frozen[START][4]+=D("0.03")
        self.assertFalse(compare(rows,frozen,{})["strict_day_ohlcv_source_parity_pass"])

    def test_gzip_crc_and_csv_header_integrity(self):
        raw=b"id,timestamp,price,volume,side,rpi\n1,"+str(START).encode()+b",100,0.001,buy,0\n"
        content,parsed=parse_archive(gzip.compress(raw))
        self.assertEqual(content,raw)
        self.assertEqual(len(parsed),1)
        with self.assertRaises(Exception):
            parse_archive(gzip.compress(raw)[:-5])
        with self.assertRaisesRegex(ValueError,"duplicate_trade_id"):
            parse_archive(gzip.compress(raw+raw.split(b"\n")[1]+b"\n"))

    def test_reject_future_and_nonspot_semantics(self):
        with self.assertRaises(ValueError):
            assert_valid_trade({"id":"1","timestamp":str(START-1),"price":"1","volume":"1","side":"Buy","rpi":"0"})
        with self.assertRaises(ValueError):
            assert_valid_trade({"id":"1","timestamp":str(START),"price":"1","volume":"1","side":"unknown","rpi":"0"})


if __name__=="__main__":
    unittest.main()
