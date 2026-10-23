"""No network/order unit tests for the MANUAL locked Oct23 archive orchestration."""
from __future__ import annotations
import hashlib,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from research.nexus_mr40_bybit_forward_shadow_v1 import NOT_BEFORE
from research.nexus_mr40_independent_closed_signal_v1 import canon
from research.nexus_mr40_oct23_manual_postday_shadow_and_risk_v1 import (
    execute,inspect_targets,HTTP_URL)

def paths(root):
    return {
        "original_dir":root/"original",
        "bridge":root/"bridge.json",
        "oct22_report":root/"parity.json",
        "oct22_history":root/"state.json",
        "archive_dir":root/"results",
        "shadow_lock":root/"shadow_lock.json",
        "risk_lock":root/"risk_lock.json"
    }

def fake_risk_output(filename):
    d={"schema":"TEST_ONLY_NEVER_OFFICIAL","orders":0,"paper_modified":False}
    d["digest"]=hashlib.sha256(canon(d)).hexdigest()
    filename.parent.mkdir(parents=True,exist_ok=True)
    filename.write_text(json.dumps(d,sort_keys=True))

class TestManualOneShotResearchRunner(unittest.TestCase):
    def test_not_yet_day_end_uses_zero_network_and_zero_file_access(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            def fail(*args,**kwargs): raise AssertionError("access too early")
            with patch(
                "research.nexus_mr40_oct23_manual_postday_shadow_and_risk_v1.preflight",
                side_effect=fail),patch(
                "research.nexus_mr40_oct23_manual_postday_shadow_and_risk_v1.inspect_targets",
                side_effect=fail):
                r=execute(root,root/"original",now_ms=NOT_BEFORE-1,
                          official_head=fail,run_shadow_action=fail,run_risk_action=fail)
            self.assertEqual(r["status"],"NOT_YET_TIME")
            self.assertEqual(r["orders"],0)

    def test_preflight_after_utc_end_never_performs_any_http_get(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            def fail(*args,**kwargs):raise AssertionError("no network/data writes")
            with patch(
                "research.nexus_mr40_oct23_manual_postday_shadow_and_risk_v1.preflight",
                return_value=paths(root)):
                r=execute(root,root/"original",now_ms=NOT_BEFORE+1,
                    preflight_only=True,official_head=fail,
                    run_shadow_action=fail,run_risk_action=fail)
            self.assertEqual(r["status"],"READY_FOR_OFFICIAL_SOURCE_PUBLICATION")

    def test_source_404_preserves_empty_archive_and_report_paths(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            def fail(*a,**k):raise AssertionError("never call GET after 404")
            with patch(
                "research.nexus_mr40_oct23_manual_postday_shadow_and_risk_v1.preflight",
                return_value=paths(root)):
                x=execute(root,root/"original",now_ms=NOT_BEFORE+1000,
                    official_head=lambda:{"status":404,"unpublished":True},
                    run_shadow_action=fail,run_risk_action=fail)
            self.assertEqual(x["status"],"OFFICIAL_DAY_NOT_PUBLISHED")
            self.assertEqual(x["official_url"],HTTP_URL)
            a,s,r=inspect_targets(root)
            self.assertFalse(a.exists() or s.exists() or r.exists())

    def test_partial_shadow_archive_pair_refuses_network_and_trading(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            target=root/"results/Bybit_BTCUSDT_Spot_2026-10-23.csv.gz"
            target.parent.mkdir(parents=True)
            target.write_bytes(b"UNTRUSTED_SOURCE")
            with self.assertRaisesRegex(ValueError,"partial_oct23_archive_shadow"):
                execute(root,root/"original",now_ms=NOT_BEFORE+1000,
                        official_head=lambda:{"status":200})
            self.assertEqual(target.read_bytes(),b"UNTRUSTED_SOURCE")

    def test_no_overwrite_existing_risk_result(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            target=root/"results/mr40_oct23_prearm_forward_risk_telemetry_20261024.json"
            target.parent.mkdir(parents=True)
            target.write_text("existing result")
            with self.assertRaisesRegex(ValueError,"risk_report_already_exists"):
                execute(root,root/"original",now_ms=NOT_BEFORE+1000,
                        official_head=lambda:{"status":200})
            self.assertEqual(target.read_text(),"existing result")

    def test_after_full_archive_download_run_shadow_then_independent_risk_in_order(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);calls=[]
            def head():
                calls.append("head")
                return {"status":200}
            def shadow(*a,**kw):
                calls.append("shadow")
                self.assertEqual(kw["oct22_verified_audit"],root/"parity.json")
                (root/"results").mkdir(parents=True,exist_ok=True)
                (root/"results/Bybit_BTCUSDT_Spot_2026-10-23.csv.gz").write_bytes(b"FAKE")
                (root/"results/bybit_oct23_spot_forward_shadow_20261024.json").write_text("synthetic")
            def risk(*a,**kw):
                calls.append("risk")
                self.assertEqual(kw["original_dir"],root/"original")
                self.assertEqual(kw["bridge_file"],root/"bridge.json")
                self.assertEqual(kw["oct22_source_report"],root/"parity.json")
                fake_risk_output(a[4])
            with patch(
                "research.nexus_mr40_oct23_manual_postday_shadow_and_risk_v1.preflight",
                return_value=paths(root)):
                result=execute(root,root/"original",now_ms=NOT_BEFORE+1000,
                               official_head=head,run_shadow_action=shadow,
                               run_risk_action=risk)
            self.assertEqual(calls,["head","shadow","risk"])
            self.assertEqual(result["status"],"LOCKED_POST_DAY_RESEARCH_RISK_TELEMETRY_COMPLETE")
            self.assertEqual(result["orders"],0)
            self.assertFalse(result["paper_modified"])

    def test_already_pinned_archive_plus_shadow_resumes_risk_without_http(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            archive=root/"results/Bybit_BTCUSDT_Spot_2026-10-23.csv.gz"
            shadow=root/"results/bybit_oct23_spot_forward_shadow_20261024.json"
            archive.parent.mkdir(parents=True)
            archive.write_bytes(b"PRESERVED")
            shadow.write_text("PRESERVED")
            def fail(*a,**kw):raise AssertionError("must never redownload a trusted source")
            def risk(*a,**kw):fake_risk_output(a[4])
            with patch(
                "research.nexus_mr40_oct23_manual_postday_shadow_and_risk_v1.preflight",
                return_value=paths(root)):
                result=execute(root,root/"original",now_ms=NOT_BEFORE+1000,
                    official_head=fail,run_shadow_action=fail,run_risk_action=risk)
            self.assertEqual(result["status"],"LOCKED_POST_DAY_RESEARCH_RISK_TELEMETRY_COMPLETE")
            self.assertEqual(archive.read_bytes(),b"PRESERVED")
            self.assertEqual(shadow.read_text(),"PRESERVED")

if __name__=="__main__":
    unittest.main()
