"""Offline synthetic validation of public-only cross-venue 4h receipts."""
import json
import unittest
from decimal import Decimal as D
from research.nexus_mr40_public_backup_alignment_v1 import normalized_rows, overlap,STEP


def rows_bitget(count=4):
    return {"code":"00000","data":[[str(i*STEP),"100","105","90","101","12","1200"] for i in range(count)]}


def rows_lbank(count=4):
    return {"result":"true","error_code":0,"data":[[i*STEP//1000,100,105,90,101.5,12] for i in range(count)]}


class BackupSourceTests(unittest.TestCase):
    def test_bitget_spot_rows(self):
        data=normalized_rows(json.dumps(rows_bitget()).encode(),"Bitget")
        self.assertEqual(len(data),4)
        self.assertEqual(data[0]["close"],"101")

    def test_lbank_unix_seconds_to_ms(self):
        data=normalized_rows(json.dumps(rows_lbank()).encode(),"LBank")
        self.assertEqual(len(data),4)
        self.assertEqual(data[STEP]["timestamp_ms"],STEP)

    def test_strictly_closed_candle_and_common(self):
        b=normalized_rows(json.dumps(rows_bitget()).encode(),"Bitget")
        l=normalized_rows(json.dumps(rows_lbank()).encode(),"LBank")
        x=overlap(b,l,4*STEP+121000)
        self.assertEqual(x["matching_closed_bars"],4)
        self.assertTrue(x["read_only_research_backup_source_ready"])
        self.assertFalse(x["bybit_feed_replaced_or_verified"])
        self.assertEqual(x["closed_bar_compare"][-1]["absolute_close_difference_usdt"],"0.5")

    def test_current_unclosed_bar_excluded(self):
        b=normalized_rows(json.dumps(rows_bitget()).encode(),"Bitget")
        l=normalized_rows(json.dumps(rows_lbank()).encode(),"LBank")
        x=overlap(b,l,3*STEP+121000)
        self.assertEqual(x["matching_closed_bars"],3)
        self.assertEqual(x["closed_bar_compare"][-1]["timestamp_ms"],2*STEP)

    def test_gaps_fail_readiness(self):
        b=normalized_rows(json.dumps(rows_bitget()).encode(),"Bitget")
        l=normalized_rows(json.dumps(rows_lbank()).encode(),"LBank")
        del l[STEP]
        x=overlap(b,l,4*STEP+121000)
        self.assertFalse(x["read_only_research_backup_source_ready"])

    def test_invalid_ohlcv_rejected(self):
        rows=rows_bitget()
        rows["data"][0][3]="110"
        with self.assertRaises(ValueError):
            normalized_rows(json.dumps(rows).encode(),"Bitget")

    def test_api_error_rejected(self):
        with self.assertRaises(ValueError):
            normalized_rows(json.dumps({"code":"10001","data":[]}).encode(),"Bitget")
        with self.assertRaises(ValueError):
            normalized_rows(json.dumps({"result":"false","error_code":201,"data":[]}).encode(),"LBank")


if __name__=="__main__":
    unittest.main()
