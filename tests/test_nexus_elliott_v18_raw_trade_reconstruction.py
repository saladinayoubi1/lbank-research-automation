"""V18 source comparison arithmetic tests; no Bybit HTTP or cached file use."""
import sys
import unittest
from decimal import Decimal
from pathlib import Path

PROBE=Path(__file__).resolve().parents[1]/"docs"/"evidence"/"elliott-v18-overlap-20261015"
sys.path.insert(0,str(PROBE))
from reconstruct_from_cached_trades import field_diff


def row(*, opening="10",close="10",volume="31.857317"):
    return {"open":Decimal(opening),"high":Decimal("11"),"low":Decimal("9"),
            "close":Decimal(close),"volume":Decimal(volume)}


class RawTradeSourceForensicTests(unittest.TestCase):
    def test_parquet_binary_rounding_is_not_false_volume_corruption(self):
        a={900000:row(volume="31.857317")}
        b={900000:row(volume="31.857317000000002")}
        diff=field_diff(a,b)
        self.assertEqual(sum(v["count"] for v in diff.values()),0)

    def test_close_ordering_change_is_not_silently_masked(self):
        a={900000:row(close="62946.7")}
        b={900000:row(close="62945.1")}
        d=field_diff(a,b)
        self.assertEqual(d["close"]["count"],1)
        self.assertEqual(d["volume"]["count"],0)

    def test_open_price_material_drift_is_not_silently_masked(self):
        a={900000:row(opening="62950.6")}
        b={900000:row(opening="62951.8")}
        d=field_diff(a,b)
        self.assertEqual(d["open"]["count"],1)


if __name__=="__main__":
    unittest.main()
