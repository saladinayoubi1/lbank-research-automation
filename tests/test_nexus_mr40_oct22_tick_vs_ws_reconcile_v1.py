"""No-network locked Bybit Spot Oct22 tick-vs-live-4h source contract tests."""
from __future__ import annotations
import copy
import json
import tempfile
import unittest
from decimal import Decimal as D
from pathlib import Path
from datetime import datetime
from unittest.mock import patch

from research.nexus_mr40_oct22_tick_vs_ws_reconcile_v1 import (
    DAY_BEGIN,DAY_END,FIXED_BAR_START,LAST_BRIDGE_BAR,
    pinned_protocol, reject_before_day_end, reconcile,verified_bridge,verified_raw_ws,
    execute, canonical, persist_trusted_pair_no_overwrite,
)


def fixed_day_rows():
    prices=[
        ["82300","82400","81300","81700","300"],
        ["81700","82100","81400","81800","400"],
        ["81800","82150","81200","81500","500"],
        ["81500","82000","81000","81677.3","1000"],
        ["81677.3","81761.2","80927.9","81488.6","2951.920267"],
        ["81488.6","82000","81000","81600","950"]
    ]
    return [[DAY_BEGIN+i*14400000,*values] for i,values in enumerate(prices)]


def ws_fixed():
    return {"ohlcv":["81677.3","81761.2","80927.9","81488.6","2951.920267"]}


def protocol():
    return {
        "schema":"nexus.mr40.bybit_oct22_tick_ws_4h_reconciliation.protocol.v1",
        "archive":{"url":"https://public.bybit.com/spot/BTCUSDT/BTCUSDT_2026-10-22.csv.gz",
                   "timestamp_day_start_ms":DAY_BEGIN,"timestamp_day_end_exclusive_ms":DAY_END},
        "predefined_tolerances":{"absolute_max_per_OHLC_usdt":"0.01",
                                  "max_relative_base_volume_error":"0.001"},
        "historical_prefix":{"bridge_evidence_digest":"f118d0affe21995f4bfa01c1b5261eb7e963d1c1d46bfb094debf28a35c3114e",
                             "previous_12_rows_digest":"a3fe422736b0dd27342b711765e721608cb88f7ec49ef22b723d09b64acaf5a6"},
        "live_capture":{"raw_source_sha256":"7704589ec16144ee9852fb4c8d0aeea49287346891c27f5149825e0311445a7e",
                        "source_gate_digest":"d52988afdce73267a9a8489e516cbce20cd58707b96bf907fc79fcfe4904f30f",
                        "fixed_open_ms":FIXED_BAR_START},
        "safety":{"orders":0,"promote":False}
    }


class TestPinnedOct22Reconcile(unittest.TestCase):
    def test_exact_observed_same_venue_ohlcv_matches(self):
        r=reconcile(fixed_day_rows(),ws_fixed(),LAST_BRIDGE_BAR)
        self.assertTrue(r["source_same_venue_reconciliation_pass"])
        self.assertEqual(r["price_OHLC_abs_diff_usdt"],["0.0","0.0","0.0","0.0"])
        self.assertEqual(r["base_volume_relative_diff"],"0")

    def test_max_price_tolerance_inclusive(self):
        b=fixed_day_rows()
        b[4][4]="81488.61"
        self.assertTrue(reconcile(b,ws_fixed(),LAST_BRIDGE_BAR)["price_comparison_pass"])

    def test_price_exceeds_one_cent_stays_fail(self):
        b=fixed_day_rows()
        b[4][4]="81488.62"
        x=reconcile(b,ws_fixed(),LAST_BRIDGE_BAR)
        self.assertFalse(x["price_comparison_pass"])
        self.assertFalse(x["source_same_venue_reconciliation_pass"])

    def test_base_volume_more_than_point_one_percent_stays_fail(self):
        b=fixed_day_rows()
        b[4][5]=str(D("2951.920267")*D("1.002"))
        x=reconcile(b,ws_fixed(),LAST_BRIDGE_BAR)
        self.assertFalse(x["volume_comparison_pass"])
        self.assertFalse(x["source_same_venue_reconciliation_pass"])

    def test_missing_intermediate_candle_fails_not_filled_from_websocket(self):
        b=fixed_day_rows()
        del b[2]
        with self.assertRaisesRegex(ValueError,"six_complete"):
            reconcile(b,ws_fixed(),LAST_BRIDGE_BAR)

    def test_shifted_bar_gap_rejected_even_if_six_rows(self):
        b=fixed_day_rows()
        b[2][0]+=14400000
        with self.assertRaisesRegex(ValueError,"missing_or_out_of_order"):
            reconcile(b,ws_fixed(),LAST_BRIDGE_BAR)

    def test_unpinned_day_cannot_be_substituted(self):
        q=protocol()
        q["archive"]["url"]=q["archive"]["url"].replace("2026-10-22","2026-10-21")
        with self.assertRaisesRegex(ValueError,"protocol_drift"):
            pinned_protocol(q)

    def test_unpinned_price_tolerance_cannot_be_relaxed(self):
        q=protocol()
        q["predefined_tolerances"]["absolute_max_per_OHLC_usdt"]="1.0"
        with self.assertRaisesRegex(ValueError,"protocol_drift"):
            pinned_protocol(q)

    def test_late_archive_never_read_before_full_utc_day(self):
        with self.assertRaisesRegex(ValueError,"not_yet_completed_no_network"):
            reject_before_day_end(DAY_END-1)
        reject_before_day_end(DAY_END)

    def test_existing_output_prevents_any_archive_access(self):
        with tempfile.TemporaryDirectory() as dir:
            base=Path(dir)
            report=base/"existing.json"
            report.write_text("old_result")
            with patch("research.nexus_mr40_oct22_tick_vs_ws_reconcile_v1.urllib.request.urlopen",
                       side_effect=AssertionError("network_access_forbidden")):
                with self.assertRaisesRegex(ValueError,"refuse_overwrite"):
                    execute(base/"lock.json",base/"bridge.json",base/"ws.json",
                            base/"gate.json",base/"archive.gz",report)
            self.assertEqual(report.read_text(),"old_result")

    def test_archive_source_is_not_replaced_by_mismatched_WS(self):
        x=ws_fixed()
        x["ohlcv"]=["82000","82100","80927.9","81488.6","2951.920267"]
        r=reconcile(fixed_day_rows(),x,LAST_BRIDGE_BAR)
        self.assertFalse(r["source_same_venue_reconciliation_pass"])

    def test_wrong_prefix_cannot_move_start_of_day(self):
        with self.assertRaisesRegex(ValueError,"missing_or_out_of_order"):
            reconcile(fixed_day_rows(),ws_fixed(),LAST_BRIDGE_BAR-14400000)


    def test_archive_receipt_follows_full_GET_not_premature_request_start(self):
        """A source is not truly accessible until all archive bytes arrive.

        Source and time are mocked. This is NOT real Oct22 archive data.
        """
        import hashlib
        from unittest.mock import MagicMock
        from research.nexus_mr40_oct22_tick_vs_ws_reconcile_v1 import URL
        fake_raw=b"f"*110000
        fake_csv=b"fixture_csv_for_time_test"
        day_rows=fixed_day_rows()
        def mkresp(status,headers,data=b""):
            resp=MagicMock()
            resp.status=status;resp.headers=headers;resp.read.return_value=data
            resp.__enter__.return_value=resp
            resp.__exit__.return_value=False
            return resp
        http_head=mkresp(200,{"Content-Length":str(len(fake_raw)),"Last-Modified":"test"})
        http_get=mkresp(200,{},fake_raw)
        def fake_get(request,*args,**kwargs):
            if request.get_method()=="HEAD":return http_head
            if request.get_method()=="GET":return http_get
            raise AssertionError("unknown HTTP operation")
        future=int(DAY_END/1000)+7200
        with tempfile.TemporaryDirectory() as folder:
            base=Path(folder)
            (base/"protocol.json").write_text(json.dumps(protocol()))
            with patch("research.nexus_mr40_oct22_tick_vs_ws_reconcile_v1.load_pinned_files",
                       return_value=(protocol(),LAST_BRIDGE_BAR,ws_fixed(),{"snapshots":49})),patch(
                "research.nexus_mr40_oct22_tick_vs_ws_reconcile_v1.time.time",
                side_effect=[future,future+7]),patch(
                "research.nexus_mr40_oct22_tick_vs_ws_reconcile_v1.urllib.request.urlopen",
                side_effect=fake_get) as requests,patch(
                "research.nexus_mr40_oct22_tick_vs_ws_reconcile_v1.gzip.decompress",
                return_value=fake_csv),patch(
                "research.nexus_mr40_oct22_tick_vs_ws_reconcile_v1.rollup",
                return_value=(day_rows,{"minutes_verified":1440,
                                        "four_hour_candles_verified":6,
                                        "exact_1m_to_4h":True})):
                execute(base/"protocol.json",base/"bridge.json",
                        base/"raw.json",base/"gate.json",base/"archive.gz",
                        base/"audit.json")
            report=json.loads((base/"audit.json").read_text())
            receipt=report["official_trade_archive"]
            self.assertEqual(receipt["url"],URL)
            self.assertTrue(receipt["data_availability_clock_is_post_full_GET"])
            self.assertEqual(int(datetime.fromisoformat(receipt["request_started_utc"]).timestamp()),future)
            self.assertEqual(int(datetime.fromisoformat(receipt["received_utc"]).timestamp()),future+7)
            self.assertEqual((base/"archive.gz").read_bytes(),fake_raw)
            self.assertEqual(requests.call_count,2)
            self.assertFalse(report["paper_changed"])
            self.assertEqual(report["orders_sent"],0)

    def test_nonmonotone_post_GET_receipt_clock_blocks_evidence(self):
        from unittest.mock import MagicMock
        fake_raw=b"x"*110000
        def mkresp(status,headers,data=b""):
            resp=MagicMock();resp.status=status;resp.headers=headers
            resp.read.return_value=data
            resp.__enter__.return_value=resp
            resp.__exit__.return_value=False
            return resp
        with tempfile.TemporaryDirectory() as folder:
            base=Path(folder)
            with patch("research.nexus_mr40_oct22_tick_vs_ws_reconcile_v1.load_pinned_files",
                       return_value=(protocol(),LAST_BRIDGE_BAR,ws_fixed(),{})),patch(
                "research.nexus_mr40_oct22_tick_vs_ws_reconcile_v1.time.time",
                side_effect=[DAY_END/1000+100,DAY_END/1000+99]),patch(
                "research.nexus_mr40_oct22_tick_vs_ws_reconcile_v1.urllib.request.urlopen",
                side_effect=[mkresp(200,{"Content-Length":"110000"}),
                             mkresp(200,{},fake_raw)]):
                with self.assertRaisesRegex(ValueError,"receipt_before_request_started"):
                    execute(base/"p",base/"bridge",base/"raw",base/"gate",
                            base/"archive.gz",base/"audit.json")
            self.assertFalse((base/"archive.gz").exists())
            self.assertFalse((base/"audit.json").exists())


    @staticmethod
    def fail_closed_mismatch_fixture(mutator):
        """A mocked full official public day with deterministic disagreement.

        Not an actual Bybit archive; assert normal trusted source location
        is never populated if even one locked Spot 4h OHLCV metric fails.
        """
        from unittest.mock import MagicMock
        fake_gz=b"M"*110000
        rows=fixed_day_rows()
        mutator(rows)
        def response(status,headers,blob):
            r=MagicMock()
            r.status=status
            r.headers=headers
            r.read.return_value=blob
            r.__enter__.return_value=r
            r.__exit__.return_value=False
            return r
        with tempfile.TemporaryDirectory() as td:
            d=Path(td)
            (d/"locked.json").write_text(json.dumps(protocol()))
            with patch("research.nexus_mr40_oct22_tick_vs_ws_reconcile_v1.load_pinned_files",
                       return_value=(protocol(),LAST_BRIDGE_BAR,ws_fixed(),{"snapshots":49})),patch(
                "research.nexus_mr40_oct22_tick_vs_ws_reconcile_v1.time.time",
                side_effect=[DAY_END/1000+3600,DAY_END/1000+3601]),patch(
                "research.nexus_mr40_oct22_tick_vs_ws_reconcile_v1.urllib.request.urlopen",
                side_effect=[
                    response(200,{"Content-Length":str(len(fake_gz)),"Last-Modified":"fixture"},b""),
                    response(200,{},fake_gz)
                ]) as transport,patch(
                "research.nexus_mr40_oct22_tick_vs_ws_reconcile_v1.gzip.decompress",
                return_value=b"valid_mock_day"),patch(
                "research.nexus_mr40_oct22_tick_vs_ws_reconcile_v1.rollup",
                return_value=(rows,{"minutes_verified":1440,
                                    "four_hour_candles_verified":6,
                                    "exact_1m_to_4h":True})):
                with unittest.TestCase().assertRaisesRegex(
                    ValueError,"parity_failed_no_trusted_artifacts_written"):
                    execute(d/"locked.json",d/"bridge.json",
                            d/"source_raw.json",d/"source_gate.json",
                            d/"trusted_archive.csv.gz",d/"approved_report.json")
            assert transport.call_count==2
            assert not (d/"trusted_archive.csv.gz").exists()
            assert not (d/"approved_report.json").exists()

    def test_rejected_4h_spot_close_mismatch_never_persists_trusted_archive(self):
        def alter(rows):
            rows[4][4]="81488.62"   # 0.02 USDT > 0.01 fixed tolerance
        self.fail_closed_mismatch_fixture(alter)

    def test_rejected_4h_spot_volume_mismatch_never_persists_trusted_archive(self):
        def alter(rows):
            rows[4][5]=str(D("2951.920267")*D("1.002"))
        self.fail_closed_mismatch_fixture(alter)


    def test_trusted_pair_exclusive_write_success(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            archive=root/"sources"/"Bybit_BTCUSDT_Spot_2026-10-22.csv.gz"
            proof=root/"receipts"/"result.json"
            persist_trusted_pair_no_overwrite(archive,b"synthetic_gz_bytes",proof,'{"pass":true}\n')
            self.assertEqual(archive.read_bytes(),b"synthetic_gz_bytes")
            self.assertEqual(proof.read_text(),'{\"pass\":true}\n')

    def test_partial_second_report_write_rolls_back_both_new_files(self):
        """Simulate disk-full AFTER exclusive report creation and partial write."""
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            archive=root/"archive.gz"
            proof=root/"result.json"
            original_open=Path.open
            class BrokenReportWriter:
                def __init__(self,underlying): self.f=underlying
                def __enter__(self):return self
                def write(self,data):
                    self.f.write(data[:7])
                    raise OSError("simulated_disk_full_during_second_write")
                def __exit__(self,*exc):
                    self.f.close()
                    return False
            def create(handle,mode="r",*args,**kwargs):
                underlying=original_open(handle,mode,*args,**kwargs)
                if handle==proof and mode=="xb":
                    return BrokenReportWriter(underlying)
                return underlying
            with patch("pathlib.Path.open",create):
                with self.assertRaisesRegex(OSError,"simulated_disk_full"):
                    persist_trusted_pair_no_overwrite(
                        archive,b"source_is_unverified_if_proof_fails",
                        proof,'{"pass":true}\n')
            self.assertFalse(archive.exists())
            self.assertFalse(proof.exists())
            # Recovery should not be blocked by a stale orphan archive.
            persist_trusted_pair_no_overwrite(archive,b"approved",proof,'{"pass":true}\n')
            self.assertEqual(archive.read_bytes(),b"approved")

    def test_exclusive_preexisting_archive_or_report_not_overwritten(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            src=root/"a.gz";dst=root/"proof.json"
            src.write_bytes(b"ORIGINAL_SOURCE")
            with self.assertRaisesRegex(ValueError,"refuse_overwrite"):
                persist_trusted_pair_no_overwrite(src,b"new",dst,'{"pass":true}\n')
            self.assertEqual(src.read_bytes(),b"ORIGINAL_SOURCE")
            self.assertFalse(dst.exists())
            src.unlink()
            dst.write_text("EXISTING_APPROVED_REPORT")
            with self.assertRaisesRegex(ValueError,"refuse_overwrite"):
                persist_trusted_pair_no_overwrite(src,b"new",dst,'{"pass":true}\n')
            self.assertFalse(src.exists())
            self.assertEqual(dst.read_text(),"EXISTING_APPROVED_REPORT")


if __name__=="__main__":
    unittest.main()
