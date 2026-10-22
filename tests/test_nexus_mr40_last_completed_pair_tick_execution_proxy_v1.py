"""Historical last independent MR40 entry/exit trade-print causality proxy tests."""
import csv
import gzip
import tempfile
import unittest
from pathlib import Path
from decimal import Decimal as D
from research.nexus_mr40_last_completed_pair_tick_execution_proxy_v1 import (
    LAT,stats_pair,inspect_trade_day,run,date_ms
)


def fake_day(p,date,t,duplicate=False):
    rows=[
        ("A",t,100),
        ("B",t+816,100.01),
        ("C",t+817,100.02),
        ("D",t+1500,100.04),
    ]
    if duplicate:rows[-1]=("A",t+1500,100.04)
    with gzip.open(p,"wt",encoding="utf-8") as f:
        f.write("id,timestamp,price,volume,side,rpi\n")
        for ident,ts,px in rows:
            f.write(f"{ident},{ts},{px},0.1,buy,0\n")


class TestLastCompletedPair(unittest.TestCase):
    def test_cutoff_never_uses_pre_confirm_trade(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/"source.gz"
            t=date_ms("2026-10-14")+4*14_400_000
            fake_day(path,"2026-10-14",t)
            values,n=inspect_trade_day(path,"2026-10-14",t)
            self.assertEqual(n,4)
            self.assertEqual(values[0]["price"],"100")
            self.assertEqual(values[817]["price"],"100.02")
            self.assertEqual(values[1500]["price"],"100.04")
            self.assertEqual(values[817]["delay_from_candle_open_ms"],817)

    def test_wrong_day_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/"source.gz"
            t=date_ms("2026-10-14")+4*14_400_000
            fake_day(path,"2026-10-14",t)
            with self.assertRaisesRegex(ValueError,"outside_expected_utc_day"):
                inspect_trade_day(path,"2026-10-19",t)

    def test_duplicate_archive_id_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/"source.gz"
            t=date_ms("2026-10-14")+4*14_400_000
            fake_day(path,"2026-10-14",t,duplicate=True)
            with self.assertRaisesRegex(ValueError,"duplicate_source_trade_id"):
                inspect_trade_day(path,"2026-10-14",t)

    def test_hypothetical_markout_down_with_worse_buy_and_exit_sell(self):
        entry={0:{"price":"100"},817:{"price":"101"},1500:{"price":"102"}}
        exit={0:{"price":"110"},817:{"price":"109"},1500:{"price":"108"}}
        report=stats_pair(entry,exit)
        self.assertEqual([x["latency_ms"] for x in report],[0,817,1500])
        self.assertEqual(D(report[0]["hypothetical_unfilled_full_500_quote_gross_markout_usdt"]),D("50"))
        self.assertLess(D(report[1]["hypothetical_unfilled_full_500_quote_gross_markout_usdt"]),D("50"))
        self.assertLess(D(report[2]["hypothetical_unfilled_full_500_quote_gross_markout_usdt"]),D(report[1]["hypothetical_unfilled_full_500_quote_gross_markout_usdt"]))
        self.assertTrue(all(not x["signal_trade_executed"] for x in report))

    def test_no_overwrite_when_already_reported(self):
        with tempfile.TemporaryDirectory() as d:
            out=Path(d)/"existing.json"
            out.write_text("old")
            with self.assertRaisesRegex(ValueError,"refuse_overwrite"):
                run(Path(d)/"missing.json",Path(d),Path(d),out)
            self.assertEqual(out.read_text(),"old")


if __name__=="__main__":
    unittest.main()
