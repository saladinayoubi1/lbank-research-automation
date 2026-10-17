"""Offline V20 gap/discovery adversarial tests; synthetic local files only."""
import json
import sys
import tempfile
import unittest
from hashlib import sha256
from pathlib import Path

MODULE=Path(__file__).resolve().parents[1]/"docs"/"evidence"/"elliott-v20-local-gap-20261015"
sys.path.insert(0,str(MODULE))
from offline_raw_trade_coverage import (
    START,END,days,coverage_from_names,gather_local_names,
    snapshot_v19_pilot,inspect
)


def source_pilot(root):
    original=root/"v19"
    receipt={"disposition":"PASS_TWO_DAY_OFFLINE_V2_ARCHIVE_NO_FUTURE_BRIDGE",
             "july31_material_mismatches":0,"july31_field_comparisons":1260,
             "prospective_bridge_complete":False,
             "network_requests":0,"orders_placed":0,
             "source_archives":[{"filename":f"{s}_{d}.csv.gz","sha256":"f"*64}
                  for s in ("BTCUSDT","ETHUSDT")
                  for d in ("2026-07-31","2026-08-01")],
             "timeframe_series":{}}
    for sym in ("BTCUSDT","ETHUSDT"):
        alias=sym.lower().replace("usdt","_usdt")
        receipt["timeframe_series"][sym]={}
        for tf in ("minute15","hour1","hour4"):
            f=original/"bybit_market"/alias/(tf+".parquet")
            f.parent.mkdir(parents=True,exist_ok=True)
            f.write_bytes((sym+tf).encode())
            receipt["timeframe_series"][sym][tf]={
                "sha256":sha256(f.read_bytes()).hexdigest()
            }
    (original/"V19_QA_RECEIPT.json").write_text(json.dumps(receipt))
    return original


class V20CachedRawSourceCoverageTests(unittest.TestCase):
    def test_expected_gap_size_is_not_silently_reduced(self):
        self.assertEqual(len(days()),75)
        missing=coverage_from_names({"files":{},"unavailable_search_roots":[]})
        self.assertEqual(missing["expected_daily_pair_slots"],150)
        self.assertEqual(missing["missing_day_slots"],150)
        self.assertEqual(missing["first_missing_day"],"2026-08-02")
        self.assertFalse(missing["all_source_days_available_from_local_cache"])

    def test_one_side_only_is_not_pair_complete(self):
        keys={("BTCUSDT","daily","2026-08-02"):[Path("btc.gz")]}
        s=coverage_from_names({"files":keys,"unavailable_search_roots":[]})
        self.assertEqual(s["missing_day_slots"],149)
        self.assertEqual(s["first_missing_day"],"2026-08-02")

    def test_monthly_file_is_just_candidate_and_no_proof(self):
        keys={("BTCUSDT","monthly","2026-08"):[Path("BTCUSDT-2026-08.csv.gz")]}
        s=coverage_from_names({"files":keys,"unavailable_search_roots":[]})
        self.assertEqual(s["coverage_by_symbol"]["BTCUSDT"],30)
        self.assertEqual(s["coverage_by_symbol"]["ETHUSDT"],0)
        self.assertEqual(s["missing_day_slots"],120)
        self.assertTrue(all(x["file_name_only_unverified"] for x in s["local_file_candidates"]))

    def test_recursive_cached_file_discovery_and_unavailable_root(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)/"cache"
            nested=root/"nested"
            nested.mkdir(parents=True)
            (nested/"BTCUSDT_2026-08-02.csv.gz").write_bytes(b"not exchange attested")
            (nested/"ETHUSDT-2026-09.csv.gz").write_bytes(b"not exchange attested")
            (nested/"other.csv.gz").write_bytes(b"ignored")
            inventory=gather_local_names([root,Path(folder)/"not-found"])
            self.assertIn(("BTCUSDT","daily","2026-08-02"),inventory["files"])
            self.assertIn(("ETHUSDT","monthly","2026-09"),inventory["files"])
            self.assertEqual(len(inventory["files"]),2)
            self.assertEqual(len(inventory["unavailable_search_roots"]),1)

    def test_pilot_sha256_independent_verification_and_corruption(self):
        with tempfile.TemporaryDirectory() as folder:
            root=source_pilot(Path(folder))
            verified=snapshot_v19_pilot(root)
            self.assertTrue(verified["v19_pilot_6_parquet_hashes_verified"])
            (root/"bybit_market"/"btc_usdt"/"minute15.parquet").write_bytes(b"tampered")
            with self.assertRaisesRegex(ValueError,"SHA256 mismatch"):
                snapshot_v19_pilot(root)

    def test_missing_or_unauthorized_v19_receipt_fails_closed(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaisesRegex(ValueError,"receipt absent"):
                snapshot_v19_pilot(Path(folder))
            root=source_pilot(Path(folder))
            p=root/"V19_QA_RECEIPT.json"
            obj=json.loads(p.read_text())
            obj["network_requests"]=1
            p.write_text(json.dumps(obj))
            with self.assertRaisesRegex(ValueError,"unexpected authority"):
                snapshot_v19_pilot(root)

    def test_no_source_files_does_not_infer_future_authenticity(self):
        with tempfile.TemporaryDirectory() as folder:
            pilot=source_pilot(Path(folder))
            root=Path(folder)/"cache"
            root.mkdir()
            report=inspect(pilot=pilot,roots=[root])
            self.assertEqual(report["disposition"],"BLOCKED_MISSING_LOCAL_RAW_TRADE_DAYS")
            self.assertFalse(report["provider_authenticity_rechecked"])
            self.assertFalse(report["continuation_accepted"])
            self.assertEqual(report["orders_placed"],0)
            self.assertEqual(report["source_coverage"]["missing_day_slots"],150)


if __name__=="__main__":
    unittest.main()
