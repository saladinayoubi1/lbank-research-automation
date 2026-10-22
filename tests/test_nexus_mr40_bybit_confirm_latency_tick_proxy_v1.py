"""Synthetic deterministic first-trade-after-confirmation latency proxy tests."""
import tempfile
import unittest
from decimal import Decimal as D
from pathlib import Path
from research.nexus_mr40_bybit_confirm_latency_tick_proxy_v1 import (
    DAY_MS,FOUR_MS,make_windows,capture_print,summarize,run,LATENCIES
)


class TestMR40LatencyPrintProxy(unittest.TestCase):
    def test_first_trade_and_cutoff_must_be_first_at_or_after(self):
        ws=make_windows("2026-10-20")
        t=ws[0]["utc_fourhour_start_ms"]
        capture_print(ws,t,D("100"),"opening")
        capture_print(ws,t+816,D("100.01"),"too-early")
        capture_print(ws,t+817,D("100.02"),"eligible")
        capture_print(ws,t+1100,D("101"),"later")
        capture_print(ws,t+1500,D("100.03"),"stress")
        self.assertEqual(ws[0]["first_boundary_print"]["trade_id"],"opening")
        self.assertEqual(ws[0]["cutoff_ms_to_first_print"]["817"]["trade_id"],"eligible")
        self.assertEqual(ws[0]["cutoff_ms_to_first_print"]["1500"]["trade_id"],"stress")

    def test_price_sign_convention_buy_and_sell_no_direction_pick(self):
        ws=make_windows("2026-10-20")
        for w in ws:
            t=w["utc_fourhour_start_ms"]
            capture_print(ws,t,D("100"),"first")
            capture_print(ws,t+817,D("100.05"),"up")
            capture_print(ws,t+1500,D("99.95"),"down")
        data,stats=summarize([ws])
        self.assertEqual(len(data),12)
        self.assertTrue(all(x["hypothetical_buy_adverse_if_positive"] for x in data if x["latency_assumption_ms"]==817))
        self.assertTrue(all(x["hypothetical_sell_adverse_if_negative"] for x in data if x["latency_assumption_ms"]==1500))
        self.assertEqual(stats["817"]["samples"],6)
        self.assertEqual(stats["817"]["price_up_count"],6)
        self.assertEqual(stats["1500"]["price_down_count"],6)

    def test_reuse_earlier_price_after_lag_not_allowed(self):
        ws=make_windows("2026-10-20")
        t=ws[0]["utc_fourhour_start_ms"]
        capture_print(ws,t,D("100"),"base")
        capture_print(ws,t+816,D("200"),"before-observed-receipt")
        self.assertIsNone(ws[0]["cutoff_ms_to_first_print"]["817"])

    def test_report_never_overwrites_existing_file(self):
        with tempfile.TemporaryDirectory() as folder:
            base=Path(folder)
            out=base/"previous.json"
            out.write_text("immutable")
            with self.assertRaisesRegex(ValueError,"refuse_overwrite"):
                run(base/"unused.json",base,out)
            self.assertEqual(out.read_text(),"immutable")

    def test_six_exact_fourhour_fixed_buckets(self):
        w=make_windows("2026-10-20")
        self.assertEqual(len(w),6)
        self.assertEqual(w[5]["utc_fourhour_start_ms"]-w[0]["utc_fourhour_start_ms"],5*FOUR_MS)
        self.assertEqual(DAY_MS,6*FOUR_MS)
        self.assertEqual(LATENCIES,(817,1500))


if __name__=="__main__":
    unittest.main()
