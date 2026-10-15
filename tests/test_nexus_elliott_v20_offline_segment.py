"""Fail-closed no-network V20 standalone segment tests, synthetic files only."""
import sys
import tempfile
import unittest
from hashlib import sha256
from pathlib import Path
from unittest.mock import patch

BASE=Path(__file__).resolve().parents[1]/"docs"/"evidence"/"elliott-v20-local-gap-20261015"
sys.path.insert(0,str(BASE))
import build_disconnected_30day_v2 as segment


class OfflineSeptemberV20Tests(unittest.TestCase):
    def test_research_authority_and_disconnected_scope(self):
        self.assertTrue(segment.RESEARCH_ONLY)
        self.assertFalse(segment.LIVE_ENABLED)
        self.assertFalse(segment.AUTO_DEMO)
        self.assertFalse(segment.TRADING_AUTHORITY)
        self.assertEqual(len(segment.fixed_days()),30)
        self.assertEqual(segment.EXPECTED_ARCHIVES,60)
        self.assertEqual(segment.ROWS,{"minute15":2880,"hour1":720,"hour4":180})

    def test_monthly_or_outside_period_cannot_be_admitted(self):
        for sym,day in (("BTCUSDT","2026-08-02"),
                        ("ETHUSDT","2026-10-08"),
                        ("LBank","2026-09-08")):
            with self.subTest(sym=sym,day=day),self.assertRaises(ValueError):
                segment.source_name(sym,day)

    def test_local_offline_inventory_contains_both_pairs_30_days(self):
        for sym in segment.SYMBOLS:
            inv=segment.offline_inventory(sym)
            self.assertEqual(len(inv.daily),30)
            self.assertEqual(inv.monthly,{})
            self.assertEqual(inv.daily["2026-09-08"],
                             sym+"_2026-09-08.csv.gz")

    def test_missing_cached_archive_fails_before_backfill(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache=Path(tmp)/"cache"
            cache.mkdir()
            with self.assertRaisesRegex(FileNotFoundError,"missing/nonempty"):
                segment.preflight(cache,Path(tmp)/"new",[Path(tmp)/"legacy"])

    def test_cache_or_protected_output_overlap_denied(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            cache=root/"cached";legacy=root/"legacy"
            cache.mkdir();legacy.mkdir()
            with self.assertRaisesRegex(ValueError,"collides"):
                segment.preflight(cache,cache/"new",[legacy])
            with self.assertRaisesRegex(ValueError,"collides"):
                segment.preflight(cache,legacy/"new",[legacy])

    def test_existing_segment_never_auto_cleans_or_resumes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            cache=root/"cache";already=root/"already"
            cache.mkdir();already.mkdir()
            with self.assertRaisesRegex(FileExistsError,"fresh"):
                segment.preflight(cache,already,[root/"legacy"])

    def test_tampered_preflight_source_denied_by_offline_loader(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            f=root/"BTCUSDT_2026-09-08.csv.gz"
            f.write_bytes(b"original")
            hash_0=sha256(f.read_bytes()).hexdigest()
            loader=segment.offline_downloader(root,{("BTCUSDT",f.name):hash_0})
            ok=loader("BTCUSDT",f.name,root)
            self.assertEqual(ok["sha256"],hash_0)
            self.assertFalse(ok["provider_authenticity_rechecked"])
            self.assertIsNone(ok["http_status"])
            f.write_bytes(b"changed")
            with self.assertRaisesRegex(ValueError,"changed"):
                loader("BTCUSDT",f.name,root)
            with self.assertRaisesRegex(ValueError,"unplanned"):
                loader("BTCUSDT","BTCUSDT_2026-10-08.csv.gz",root)


if __name__=="__main__":
    unittest.main()
