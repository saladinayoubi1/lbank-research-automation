"""V102 offline synthetic Bybit V5 page/receipt QA. ZERO HTTP requests."""
import copy
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from research.elliott_v102_bybit_intake import intake_v102 as v102

MIN=60000


def mock_payload(page, *, symbol=None, category="spot", timeshift=0):
    rows=[]
    for i in range(page.count):
        ms=page.start_ms+i*MIN+timeshift
        rows.append([str(ms),"100","110","90","101","10","1000"])
    obj={"retCode":0,"retMsg":"OK","result":{
        "category":category,"symbol":symbol or page.symbol,
        "list":list(reversed(rows))},
        "time":v102.locked_range()[1]+MIN}
    return obj


def encoded(obj):
    return json.dumps(obj,separators=(",",":")).encode()


class V102OfflineBybitIntakeTests(unittest.TestCase):
    def page(self):
        return v102.pages("BTCUSDT")[-1]

    def test_planned_42_requests_only_frozen_universe(self):
        x=v102.plan()
        self.assertEqual(x["total_pages"],42)
        self.assertEqual(x["expected_total_1m_candles"],40320)
        self.assertEqual(list(x["symbols"]),["BTCUSDT","ETHUSDT"])
        for symbol in v102.v101.PAIRS:
            pages=v102.pages(symbol)
            self.assertEqual(len(pages),21)
            self.assertEqual(pages[-1].count,160)
            self.assertEqual(pages[-1].last_start_ms+MIN,v102.locked_range()[1])
            self.assertEqual(sum(p.count for p in pages),20160)
            self.assertEqual(pages[0].start_ms,v102.locked_range()[0])
            self.assertTrue(all(p.count<=1000 for p in pages))
            self.assertTrue(all(a.last_start_ms+MIN==b.start_ms
                                for a,b in zip(pages,pages[1:])))
            self.assertTrue(all(v102.request_params(p)["category"]=="spot"
                                for p in pages))
            self.assertTrue(all(v102.request_params(p)["interval"]=="1"
                                for p in pages))
        self.assertTrue(x["no_network_in_v102"])
        self.assertTrue(x["no_market_data_opened"])

    def test_normal_reverse_sorted_final_160_bar_page(self):
        p=self.page()
        raw=encoded(mock_payload(p))
        bars,receipt=v102.parse_page(raw,p,v102.locked_range()[1]+MIN)
        self.assertEqual(len(bars),160)
        self.assertEqual(bars[0].ms,p.start_ms)
        self.assertEqual(bars[-1].ms,p.last_start_ms)
        self.assertEqual(str(bars[0].close),"101")
        self.assertTrue(receipt["page_order_and_ohlc_verified"])
        self.assertFalse(receipt["response_cryptographically_signed"])
        self.assertEqual(receipt["response_raw_sha256"],v102.sha(raw))

    def test_wrong_exchange_product_or_symbol_refused(self):
        p=self.page()
        for args in ({"category":"linear"},{"symbol":"ETHUSDT"}):
            with self.subTest(args=args):
                with self.assertRaisesRegex(ValueError,"wrong category/symbol"):
                    v102.parse_page(encoded(mock_payload(p,**args)),p,
                                    v102.locked_range()[1]+MIN)

    def test_wrong_api_retcode_refused(self):
        p=self.page()
        obj=mock_payload(p);obj["retCode"]=10001
        with self.assertRaisesRegex(ValueError,"exchange error"):
            v102.parse_page(encoded(obj),p,v102.locked_range()[1]+MIN)

    def test_boolean_status_is_not_integer_success(self):
        p=self.page()
        obj=mock_payload(p);obj["retCode"]=False
        with self.assertRaisesRegex(ValueError,"exchange error"):
            v102.parse_page(encoded(obj),p,v102.locked_range()[1]+MIN)

    def test_missing_candle_page_refused(self):
        p=self.page()
        obj=mock_payload(p);obj["result"]["list"].pop()
        with self.assertRaisesRegex(ValueError,"incomplete"):
            v102.parse_page(encoded(obj),p,v102.locked_range()[1]+MIN)

    def test_out_of_order_candles_refused(self):
        p=self.page()
        obj=mock_payload(p)
        x=obj["result"]["list"];x[0],x[1]=x[1],x[0]
        with self.assertRaisesRegex(ValueError,"out-of-order"):
            v102.parse_page(encoded(obj),p,v102.locked_range()[1]+MIN)

    def test_duplicate_candle_refused(self):
        p=self.page()
        obj=mock_payload(p)
        obj["result"]["list"][1]=obj["result"]["list"][0].copy()
        with self.assertRaisesRegex(ValueError,"duplicated"):
            v102.parse_page(encoded(obj),p,v102.locked_range()[1]+MIN)

    def test_wrong_time_shift_refused(self):
        p=self.page()
        with self.assertRaisesRegex(ValueError,"out-of-order"):
            v102.parse_page(encoded(mock_payload(p,timeshift=MIN)),p,
                            v102.locked_range()[1]+MIN)

    def test_unclosed_future_page_rejected(self):
        p=self.page()
        with self.assertRaisesRegex(ValueError,"unconfirmed"):
            v102.parse_page(encoded(mock_payload(p)),p,p.last_start_ms)

    def test_bad_ohlc_refused(self):
        p=self.page()
        obj=mock_payload(p);obj["result"]["list"][0][3]="120"
        with self.assertRaisesRegex(ValueError,"OHLC"):
            v102.parse_page(encoded(obj),p,v102.locked_range()[1]+MIN)

    def test_nan_or_negative_price_refused(self):
        p=self.page()
        for broken in ("NaN","-4"):
            with self.subTest(broken=broken):
                obj=mock_payload(p);obj["result"]["list"][0][4]=broken
                with self.assertRaises(ValueError):
                    v102.parse_page(encoded(obj),p,v102.locked_range()[1]+MIN)

    def test_missing_source_columns_refused(self):
        p=self.page()
        obj=mock_payload(p);obj["result"]["list"][0].pop()
        with self.assertRaisesRegex(ValueError,"seven"):
            v102.parse_page(encoded(obj),p,v102.locked_range()[1]+MIN)

    def test_duplicate_json_keys_refused(self):
        p=self.page()
        raw=encoded(mock_payload(p)).replace(b'"retCode":0,',
                b'"retCode":0,"retCode":0,',1)
        with self.assertRaisesRegex(ValueError,"duplicate"):
            v102.parse_page(raw,p,v102.locked_range()[1]+MIN)

    def test_raw_page_too_large_refused(self):
        p=self.page()
        with self.assertRaisesRegex(ValueError,"oversized"):
            v102.parse_page(b" "*400001,p,v102.locked_range()[1]+MIN)

    def test_symbol_not_registered_rejected(self):
        with self.assertRaisesRegex(ValueError,"frozen"):
            v102.pages("XRPUSDT")

    def test_no_unsigned_claim_to_cryptographic_source_authenticity(self):
        p=self.page()
        rows,receipt=v102.parse_page(encoded(mock_payload(p)),p,
                                    v102.locked_range()[1]+MIN)
        self.assertFalse(receipt["independent_transport_source_authentication"])
        self.assertEqual(v102.ORDER_ADAPTER,None)
        self.assertFalse(v102.LIVE_ENABLED)
        self.assertFalse(v102.PAPER_ELIGIBLE)
        self.assertFalse(v102.ENTRY_SIGNAL)
        self.assertTrue(v102.NO_NETWORK_FETCH)

    def test_freeze_plan_no_changes_allowed(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/"V102_FROZEN_REQUEST_PLAN.json"
            a=v102.freeze_plan(path)
            self.assertEqual(path.read_bytes(),v102.plan_bytes())
            self.assertEqual(a["planned_requests"],42)
            self.assertEqual(a["data_rows_fetched"],0)
            self.assertEqual(a,v102.freeze_plan(path))
            path.write_bytes(b"tampered")
            with self.assertRaisesRegex(ValueError,"differs"):
                v102.freeze_plan(path)

    def test_no_future_source_acceptance_before_end(self):
        with self.assertRaisesRegex(ValueError,"has not ended"):
            v102.accept_complete_future_archive({})

    def test_complete_fake_archive_has_invariants_but_not_source_signature(self):
        all_pages={}
        received=v102.locked_range()[1]+MIN
        for symbol in v102.v101.PAIRS:
            for page in v102.pages(symbol):
                all_pages[(symbol,page.index)]=(encoded(mock_payload(page)),received)
        with patch.object(v102,"datetime",wraps=datetime) as clock:
            clock.now.return_value=datetime(2026,12,1,tzinfo=timezone.utc)
            output=v102.accept_complete_future_archive(all_pages)
        self.assertTrue(output["all_original_pages_complete"])
        self.assertFalse(output["source_signature_verified"])
        self.assertEqual(output["elliott_certificates"],0)
        self.assertFalse(output["entry_signal"])
        self.assertFalse(output["paper_eligible"])
        self.assertEqual(output["orders"],0)
        self.assertEqual(len(output["symbols"]),2)
        for sym in v102.v101.PAIRS:
            x=output["symbols"][sym]
            self.assertEqual(x["physical_complete_1m_rows"],20160)
            self.assertEqual(len(x["all_page_receipts"]),21)
            self.assertFalse(x["source_claim_authenticated_by_provider_signature"])
            self.assertTrue(x["physical_ohlc_time_integrity"])

    def test_stale_or_missing_synthetic_archive_abstains(self):
        source={}
        with patch.object(v102,"datetime",wraps=datetime) as clock:
            clock.now.return_value=datetime(2026,12,1,tzinfo=timezone.utc)
            with self.assertRaisesRegex(ValueError,"incomplete"):
                v102.accept_complete_future_archive(source)

    def test_unknown_extra_page_rejected(self):
        with patch.object(v102,"datetime",wraps=datetime) as clock:
            clock.now.return_value=datetime(2026,12,1,tzinfo=timezone.utc)
            with self.assertRaisesRegex(ValueError,"unexpected extra"):
                v102.accept_complete_future_archive({("BTCUSDT",500):(b"{}",0)})
