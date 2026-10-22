"""Synthetic one-minute aggregation and no trading side-effect checks."""
import unittest
from decimal import Decimal as D
from research.nexus_mr40_backup_1m_4h_integrity_v1 import (
    evaluate,parse,make_url,STEP1,STEP4)

P={"requirements":{"price_abs_tolerance_usdt":"0.01","base_volume_rel_tolerance":"0.001"}}


def sample():
    ts=STEP4*10
    minute={ts+i*STEP1:(D("100"),D("102"),D("99"),D("101"),D("3"))
            for i in range(240)}
    agg={ts:(D("100"),D("102"),D("99"),D("101"),D("720"))}
    return ts,minute,agg


class TestBackupDataIntegrity(unittest.TestCase):
    def test_exact_240_bar_aggregation_passes(self):
        ts,minutes,agg=sample()
        r=evaluate(minutes,agg,ts,ts+STEP4+120001,P)
        self.assertTrue(r["market_source_gate_pass"])
        self.assertFalse(r["bybit_4h_1m_quality_proven"])

    def test_missing_1m_fails_closed(self):
        ts,minutes,agg=sample()
        del minutes[ts+119*STEP1]
        r=evaluate(minutes,agg,ts,ts+STEP4+120001,P)
        self.assertFalse(r["market_source_gate_pass"])
        self.assertEqual(r["minute_rows_found"],239)

    def test_unclosed_4h_fails_closed(self):
        ts,minutes,agg=sample()
        r=evaluate(minutes,agg,ts,ts+STEP4+119999,P)
        self.assertFalse(r["market_source_gate_pass"])

    def test_price_drift_above_one_cent_fails_closed(self):
        ts,minutes,agg=sample()
        agg[ts]=(D("100"),D("102"),D("99"),D("101.02"),D("720"))
        r=evaluate(minutes,agg,ts,ts+STEP4+120001,P)
        self.assertFalse(r["market_source_gate_pass"])

    def test_volume_drift_above_point_one_percent_fails_closed(self):
        ts,minutes,agg=sample()
        agg[ts]=(D("100"),D("102"),D("99"),D("101"),D("721"))
        r=evaluate(minutes,agg,ts,ts+STEP4+120001,P)
        self.assertFalse(r["market_source_gate_pass"])

    def test_no_private_endpoint(self):
        for venue in ("Bitget","LBank"):
            for tf in ("1m","4h"):
                url=make_url(venue,tf,STEP4*100)
                self.assertTrue(url.startswith("https://"))
                self.assertIn("/market/candles" if venue=="Bitget" else "/kline.do",url)
                self.assertNotIn("apiKey",url)


if __name__=="__main__":
    unittest.main()
