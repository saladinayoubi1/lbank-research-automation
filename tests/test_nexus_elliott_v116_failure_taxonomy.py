"""V116 reject-cause ledger QA; fabricated pivot streams, no new market."""
import copy
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from test_nexus_elliott_v106_early_partial import synthetic
from research.elliott_v107_prefix_census import census_v107 as v107
from research.elliott_v116_failure_taxonomy import taxonomy_v116 as v116


def fixture(reject=False):
    coarse,fine,t=synthetic()
    if reject:
        coarse[2]=replace(coarse[2],center_close=coarse[0].center_close)
    return v107.enumerate_event_prefixes(fine,coarse,t)


class V116ExactFailureReasonSource(unittest.TestCase):
    def test_pass_one_original_six_coarse_window(self):
        result=v116.count_census(fixture())
        self.assertEqual(result["original_full_six_coarse_windows"],1)
        self.assertEqual(result["original_necessary_passes"],1)
        self.assertEqual(result["original_necessary_rejections"],0)
        self.assertEqual(result["all_rejection_reasons_overlapping_counts"],{})
        self.assertIsNone(result["real_source_profit_or_loss"])
        self.assertEqual(result["orders"],0)

    def test_rejected_source_retains_original_denominator_and_primary(self):
        result=v116.count_census(fixture(True))
        self.assertEqual(result["original_full_six_coarse_windows"],1)
        self.assertEqual(result["original_necessary_passes"],0)
        self.assertEqual(result["original_necessary_rejections"],1)
        self.assertEqual(sum(result["first_rejection_mutually_exclusive_counts"].values()),1)
        self.assertGreaterEqual(
            sum(result["all_rejection_reasons_overlapping_counts"].values()),1)
        self.assertTrue(result["all_original_candidate_outcomes_sha256"])

    def test_two_reasons_count_one_denominator_with_overlap(self):
        source=fixture(True)
        row=source["candidate_ledger"][0]
        # Add a second legitimate reason to the synthetic record only,
        # then independently sync its two original census summary fields.
        reason="WAVE2_UNPRUNED_FINE_COUNT_NOT_PREDECLARED"
        if reason not in row["rejections"]:
            row["rejections"].append(reason)
        from collections import Counter
        source["all_rejection_reasons_overlapping_counts"]=dict(
            Counter(row["rejections"]))
        source["first_rejection_mutually_exclusive_counts"]={row["rejections"][0]:1}
        result=v116.count_census(source)
        self.assertEqual(result["original_necessary_rejections"],1)
        self.assertGreaterEqual(result["rejection_reason_count_sum_not_unique_denominator"],2)

    def test_modified_source_first_rejection_summary_refused(self):
        source=fixture(True)
        source["first_rejection_mutually_exclusive_counts"]={}
        with self.assertRaisesRegex(ValueError,"source tally changed"):
            v116.count_census(source)

    def test_original_necessary_acceptance_bit_mismatch_refused(self):
        source=fixture()
        source["candidate_ledger"][0]["necessary_partial_skeleton_pass"]=False
        with self.assertRaisesRegex(ValueError,"failure list"):
            v116.count_census(source)

    def test_added_fake_future_profit_reason_refused(self):
        source=fixture(True)
        source["candidate_ledger"][0]["rejections"].append("TRUE_MARKET_LOSER")
        with self.assertRaisesRegex(ValueError,"unrecognized"):
            v116.count_census(source)

    def test_repeated_reason_cannot_double_count_one_window(self):
        source=fixture(True)
        row=source["candidate_ledger"][0]
        row["rejections"].append(row["rejections"][0])
        with self.assertRaisesRegex(ValueError,"unrecognized"):
            v116.count_census(source)

    def test_removed_window_detected_against_full_6_event_denominator(self):
        source=fixture(True)
        source["candidate_ledger"]=[]
        with self.assertRaisesRegex(ValueError,"six-event denominator"):
            v116.count_census(source)

    def test_window_ordinal_reshuffle_refused(self):
        source=fixture(True)
        source["candidate_ledger"][0]["window_ordinal"]=123
        with self.assertRaisesRegex(ValueError,"reordered"):
            v116.count_census(source)

    def test_future_certificate_claim_refused(self):
        source=fixture()
        source["candidate_ledger"][0]["certified_elliott_wave"]=True
        with self.assertRaisesRegex(ValueError,"unrecognized"):
            v116.count_census(source)

    def test_duplicate_fine_or_coarse_fingerprint_not_claimed_market_trades(self):
        result=v116.count_census(fixture())
        self.assertEqual(result["actual_elliott_waves_certified"],0)
        self.assertEqual(result["orders"],0)
        self.assertIsNone(result["real_source_profit_or_loss"])

    def test_static_rejection_taxonomy_covers_exact_grammar_reasons(self):
        codes=set(v116.CATEGORIES)
        self.assertIn("WAVE1_UNPRUNED_FINE_COUNT_NOT_PREDECLARED",codes)
        self.assertIn("PRIOR_TREND_LOWER_LOW_NOT_ATTESTED",codes)
        self.assertIn("WAVE2_FINE_CONFIRMATION_UNAVAILABLE_AT_LEG_END",codes)
        self.assertTrue(v116.rules()["no_gate_relaxed_or_reordered"])
        self.assertTrue(v116.rules()["first_rejection_only_is_ordered_not_unique_causal_explanation"])
        self.assertFalse(v116.LIVE_ENABLED)
        self.assertFalse(v116.PAPER_ELIGIBLE)
        self.assertIsNone(v116.ORDER_ADAPTER)

    def test_zero_windows_stays_zero_not_profit(self):
        s=fixture()
        s["candidate_ledger"]=[]
        s["all_observed_coarse_confirmed_events"]=0
        s["all_consecutive_six_coarse_windows"]=0
        s["necessary_partial_skeleton_passes"]=0
        s["necessary_partial_skeleton_rejections"]=0
        out=v116.count_census(s)
        self.assertEqual(out["original_rejection_fraction"],"0/0")
        self.assertEqual(out["orders"],0)

    def test_frozen_git_parent_and_json_byte_immutability(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/"V116_FROZEN.json"
            result=v116.freeze(path)
            self.assertEqual(result,v116.freeze(path))
            self.assertEqual(result["orders"],0)
            self.assertEqual(result["new_market_source_rows"],0)
            self.assertTrue(json.loads(path.read_text())[
                "historical_already_inspected_not_independent_holdout"])
            path.write_text("{}")
            with self.assertRaisesRegex(ValueError,"FROZEN TAXONOMY"):
                v116.freeze(path)

    def test_old_measured_evidence_file_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/"old_evidence.json"
            path.write_text("{}")
            with patch.object(v116,"historical_source_rejection_audit",
                              return_value={"schema":v116.SCHEMA,"orders":0}):
                with self.assertRaisesRegex(ValueError,"IMMUTABILITY"):
                    v116.write_once(path)
