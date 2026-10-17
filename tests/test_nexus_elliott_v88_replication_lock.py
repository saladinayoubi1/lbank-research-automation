"""V88 manifest-only synthetic tests, no market data or network."""
import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from research.elliott_v88_replication_lock import lock_v88 as v88


class V88PreregistrationContractTests(unittest.TestCase):
    def test_exact_fixed_days_and_symbols(self):
        m=v88.manifest()
        self.assertEqual(m["exchange_and_granularity"]["symbols"],["BTCUSDT","ETHUSDT"])
        self.assertEqual(m["period"]["first_open_utc"],"2024-07-01T00:00:00Z")
        self.assertEqual(m["period"]["exclusive_end_utc"],"2024-07-15T00:00:00Z")
        self.assertEqual(m["period"]["duration_days"],14)
        self.assertEqual(len(m["period"]["split_A_days"]),7)
        self.assertEqual(len(m["period"]["split_B_days"]),7)
        self.assertEqual(m["period"]["split_A_days"][-1],"2024-07-07")
        self.assertEqual(m["period"]["split_B_days"][0],"2024-07-08")
        self.assertEqual(m["period"]["split_B_days"][-1],"2024-07-14")

    def test_28_zip_sources_and_exact_dates(self):
        m=v88.manifest()
        self.assertEqual(len(m["scheduled_inputs"]),28)
        self.assertEqual(len({(x["symbol"],x["utc_day"])
                              for x in m["scheduled_inputs"]}),28)
        v88.verify(m)

    def test_every_zip_has_official_exact_checksum(self):
        for entry in v88.manifest()["scheduled_inputs"]:
            self.assertTrue(entry["official_source_url"].startswith(
                "https://data.binance.vision/data/spot/daily/klines/"))
            self.assertTrue(entry["official_source_url"].endswith(entry["zip_file"]))
            self.assertEqual(entry["official_checksum_url"],
                             entry["official_source_url"]+".CHECKSUM")
            self.assertEqual(entry["official_checksum_file"],
                             entry["zip_file"]+".CHECKSUM")
            self.assertEqual(entry["csv_member"],
                             entry["zip_file"][:-4]+".csv")
            self.assertEqual(entry["expected_1m_rows"],1440)
            self.assertIsNone(entry["zip_sha256"])
            self.assertIs(entry["downloaded"],False)

    def test_exact_row_and_aggregate_counts(self):
        m=v88.manifest()["exchange_and_granularity"]
        self.assertEqual(m["per_symbol_expected_1m_rows"],20160)
        self.assertEqual(m["per_symbol_expected_3m_bars"],6720)
        self.assertEqual(m["per_symbol_expected_15m_bars"],1344)

    def test_no_execution_or_score_enabled(self):
        m=v88.manifest()
        self.assertIs(v88.SOURCE_ACQUISITION_ENABLED,False)
        self.assertIs(v88.RESULT_SCORING_ENABLED,False)
        self.assertIs(v88.PAPER_ELIGIBLE,False)
        self.assertIs(v88.LIVE_ENABLED,False)
        self.assertIs(v88.V52_UNCHANGED,True)
        self.assertIs(m["study_limitations"]["live_trading"],False)
        self.assertIsNone(m["study_limitations"]["net_pnl"])
        self.assertIs(m["study_limitations"]["v52_warmup_or_future_scores_not_read"],True)
        self.assertIs(m["study_limitations"]["draft_pr_only_no_merge"],True)

    def test_both_splits_evaluation_only(self):
        period=v88.manifest()["period"]
        self.assertTrue(period["splits_are_both_evaluation_only"])
        self.assertTrue(period["no_train_or_tune_on_either_split"])
        self.assertTrue(period["no_replacement_days_if_unavailable"])

    def test_lock_fixed_count_family_v87(self):
        m=v88.manifest()["frozen_recognition"]
        self.assertEqual(m["zigzag_535_inner_1m_pivot_counts_ABC"],[4,2,4])
        self.assertEqual(m["flat_335_inner_1m_pivot_counts_ABC"],[2,2,4])
        self.assertEqual(m["parent_15m_strict_pivot_halfwidth_bars"],3)
        self.assertEqual(m["child_3m_strict_pivot_halfwidth_bars"],1)
        self.assertEqual(m["physical_source_1m_pivot_halfwidth_bars"],3)
        self.assertEqual(m["inner_1m_strict_pivot_halfwidth_bars"],1)
        self.assertTrue(m["do_not_prune_same_kind_or_awkward_primitive_pivots"])
        self.assertFalse(m["allow_paper_entry_or_pnl"])

    def test_source_acceptance_fails_closed(self):
        m=v88.manifest()["source_acceptance"]
        for key,value in m.items():
            if key.startswith(("require_","reject_","fail_closed_","do_not_")):
                self.assertIs(value,True,key)

    def test_changed_source_day_rejected(self):
        m=v88.manifest()
        m["scheduled_inputs"][4]["utc_day"]="2024-07-20"
        with self.assertRaisesRegex(ValueError,"deviates"):
            v88.verify(m)

    def test_removed_source_rejected(self):
        m=v88.manifest()
        m["scheduled_inputs"].pop()
        with self.assertRaises(ValueError):
            v88.verify(m)

    def test_changed_family_rule_rejected(self):
        m=v88.manifest()
        m["frozen_recognition"]["flat_335_inner_1m_pivot_counts_ABC"]=[2,3,4]
        with self.assertRaises(ValueError):
            v88.verify(m)

    def test_manifest_is_deterministic_under_repeated_render(self):
        x=v88.canonical_bytes(v88.manifest())
        y=v88.canonical_bytes(v88.manifest())
        self.assertEqual(x,y)
        self.assertEqual(hashlib.sha256(x).hexdigest(),
                         hashlib.sha256(y).hexdigest())
        self.assertEqual(json.loads(x.decode()),v88.manifest())

    def test_no_market_access_during_seal(self):
        with tempfile.TemporaryDirectory() as base:
            path=Path(base)/"V88_PREREGISTRATION.json"
            with patch.object(v88,"ARTIFACT",path):
                result=v88.seal()
                self.assertEqual(path.read_bytes(),v88.canonical_bytes(result))
                self.assertFalse(any(x["downloaded"] for x in result["scheduled_inputs"]))

    def test_existing_seal_is_idempotent(self):
        with tempfile.TemporaryDirectory() as base:
            path=Path(base)/"V88_PREREGISTRATION.json"
            with patch.object(v88,"ARTIFACT",path):
                v88.seal()
                initial=path.read_bytes()
                v88.seal()
                self.assertEqual(path.read_bytes(),initial)

    def test_existing_seal_cannot_be_overwritten(self):
        with tempfile.TemporaryDirectory() as base:
            path=Path(base)/"V88_PREREGISTRATION.json"
            path.write_text('{"not":"the-frozen-manifest"}',encoding="utf8")
            with patch.object(v88,"ARTIFACT",path):
                with self.assertRaisesRegex(RuntimeError,"different bytes"):
                    v88.seal()

    def test_source_manifest_does_not_claim_verified_files(self):
        m=v88.manifest()
        self.assertEqual(m["protocol_state"],"LOCKED_SOURCE_UNOPENED")
        self.assertFalse(any(x["downloaded"] for x in m["scheduled_inputs"]))
        self.assertTrue(all(x["zip_sha256"] is None
                            for x in m["scheduled_inputs"]))
        self.assertTrue(m["study_limitations"]["historical_not_prospective"])
        self.assertFalse(m["study_limitations"]["absolute_never_seen_claim"])
