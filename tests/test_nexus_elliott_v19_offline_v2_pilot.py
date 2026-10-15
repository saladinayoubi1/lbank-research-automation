"""Fail-closed offline Elliott V19 source-origin pilot guards.

No external network, cached market source mutation, Paper/Live or simulated
strategy outcome. Integration uses the existing backfill engine separately.
"""
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

HERE=Path(__file__).resolve().parents[1]/"docs"/"evidence"/"elliott-v19-offline-v2-20261015"
sys.path.insert(0,str(HERE))
import build_two_day_source_bound_v2 as pilot


class OfflineTradeV19GuardTests(unittest.TestCase):
    def test_authority_and_two_day_scope(self):
        self.assertTrue(pilot.RESEARCH_ONLY)
        for flag in (pilot.LIVE_ENABLED,pilot.AUTO_DEMO,
                     pilot.ENTRY_SIGNAL,pilot.PAPER_ELIGIBLE):
            self.assertFalse(flag)
        self.assertEqual(pilot.DATES,("2026-07-31","2026-08-01"))
        self.assertEqual(set(pilot.TIMEFRAMES),{"minute15","hour1","hour4"})

    def test_inventory_is_offline_explicit_and_two_symbol(self):
        for symbol in ("BTCUSDT","ETHUSDT"):
            inv=pilot.certified_local_inventory(symbol)
            self.assertEqual(inv.symbol,symbol)
            self.assertEqual(len(inv.daily),2)
            self.assertEqual(inv.monthly,{})
            self.assertTrue(all(x.endswith(".csv.gz") for x in inv.daily.values()))

    def test_unknown_date_and_symbol_deny(self):
        for s,day in (("BTCUSDT","2026-10-16"),("BITGET","2026-07-31")):
            with self.subTest(s=s,day=day), self.assertRaises(ValueError):
                pilot.file_name(s,day)

    def test_state_root_must_be_fresh(self):
        with tempfile.TemporaryDirectory() as folder:
            cache=Path(folder)/"protected-cache"
            old=Path(folder)/"protected-legacy"
            cache.mkdir()
            old.mkdir()
            existing=Path(folder)/"already-exists"
            existing.mkdir()
            with self.assertRaisesRegex(FileExistsError,"fresh unique"):
                pilot.require_new_isolated_output(existing,(cache,old))
            with self.assertRaisesRegex(ValueError,"overlaps"):
                pilot.require_new_isolated_output(cache/"test",(cache,old))
            with self.assertRaisesRegex(ValueError,"overlaps"):
                pilot.require_new_isolated_output(old,(cache,old))

    def test_missing_raw_files_fails_before_backfill_or_network(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            source=root/"src"
            archive=root/"archive"
            target=root/"new"
            source.mkdir();archive.mkdir()
            with patch.object(pilot.backfill,"run_backfill") as forbidden:
                with self.assertRaisesRegex(FileNotFoundError,"Missing cached"):
                    pilot.run(cache_root=source,legacy_root=archive,state_root=target)
                forbidden.assert_not_called()
                self.assertFalse(target.exists())

    def test_cached_july_sha_mismatch_is_rejected_without_rewrite(self):
        with tempfile.TemporaryDirectory() as folder:
            cache=Path(folder)
            sample=cache/pilot.file_name("BTCUSDT","2026-07-31")
            sample.write_bytes(b"tampered bytes, do not parse")
            before=sample.read_bytes()
            with self.assertRaisesRegex(ValueError,"digest"):
                pilot.offline_source(cache,"BTCUSDT",sample.name,cache)
            self.assertEqual(sample.read_bytes(),before)

    def test_local_august_blob_is_not_falsely_exchange_attested(self):
        with tempfile.TemporaryDirectory() as folder:
            cache=Path(folder)
            sample=cache/pilot.file_name("ETHUSDT","2026-08-01")
            sample.write_bytes(b"fake-local-blob-for-only-unit-test")
            r=pilot.offline_source(cache,"ETHUSDT",sample.name,cache)
            self.assertEqual(r["sha256"],hashlib.sha256(sample.read_bytes()).hexdigest())
            self.assertIsNone(r["http_status"])
            self.assertFalse(r["external_exchange_origin_attested"])
            self.assertEqual(r["acquisition"],"preexisting-offline-local-raw-archive")

    def test_reject_unknown_offline_filename_without_network(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaisesRegex(ValueError,"declared local source inventory"):
                pilot.offline_source(Path(folder),"BTCUSDT","BTCUSDT_2026-08-02.csv.gz",Path(folder))


if __name__=="__main__":
    unittest.main()
