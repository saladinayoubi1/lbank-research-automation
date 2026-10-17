"""V107 strict all-six consecutive prefix decisions: SYNTHETIC only."""
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from test_nexus_elliott_v106_early_partial import synthetic,pivot,MIN
from research.elliott_v107_prefix_census import census_v107 as v107


def later():
    coarse,fine,end=synthetic()
    coarse.append(pivot("HIGH",60,140,2))
    fine.append(pivot("HIGH",60,140,1))
    return coarse,fine,coarse[-1].confirmed_ms


class V107SourcePrefixCensusTests(unittest.TestCase):
    def test_one_complete_wave2_context_is_one_in_denominator(self):
        coarse,fine,t=synthetic()
        x=v107.enumerate_event_prefixes(fine,coarse,t)
        self.assertEqual(x["all_consecutive_six_coarse_windows"],1)
        self.assertEqual(x["necessary_partial_skeleton_passes"],1)
        self.assertEqual(x["necessary_partial_skeleton_rejections"],0)
        self.assertEqual(x["first_rejection_mutually_exclusive_counts"],{})
        self.assertEqual(x["candidate_ledger"][0]["decision_asof_ms"],t)
        self.assertFalse(x["candidate_ledger"][0]["certified_elliott_wave"])
        self.assertFalse(x["candidate_ledger"][0]["order_eligible"])
        self.assertIsNone(x["real_world_false_positive_rate"])
        self.assertIsNone(x["net_pnl"])

    def test_next_confirmed_coarse_swing_does_not_retroactively_revive_candidate(self):
        coarse,fine,asof=later()
        result=v107.enumerate_event_prefixes(fine,coarse,asof)
        self.assertEqual(result["all_consecutive_six_coarse_windows"],2)
        self.assertEqual(len(result["candidate_ledger"]),2)
        self.assertEqual(result["candidate_ledger"][0]["window_ordinal"],0)
        self.assertEqual(result["candidate_ledger"][1]["window_ordinal"],1)
        self.assertEqual(result["necessary_partial_skeleton_passes"]+
                         result["necessary_partial_skeleton_rejections"],2)
        first_prior=v107.enumerate_event_prefixes(
            [x for x in fine if x.confirmed_ms<=coarse[5].confirmed_ms],
            coarse[:6],coarse[5].confirmed_ms)
        self.assertEqual(result["candidate_ledger"][0],
                         first_prior["candidate_ledger"][0])
        self.assertNotIn("fine_confirmed_later_not_allowed",result["candidate_ledger"][0])

    def test_failed_original_window_remains_rejection_not_cherry_picked(self):
        coarse,fine,t=synthetic()
        coarse[2]=replace(coarse[2],center_close=coarse[0].center_close)
        x=v107.enumerate_event_prefixes(fine,coarse,t)
        self.assertEqual(x["necessary_partial_skeleton_passes"],0)
        self.assertEqual(x["necessary_partial_skeleton_rejections"],1)
        self.assertIn("PRIOR_TREND_LOWER_HIGH_NOT_ATTESTED",
                      x["candidate_ledger"][0]["rejections"])
        self.assertEqual(sum(x["first_rejection_mutually_exclusive_counts"].values()),1)
        self.assertEqual(x["all_consecutive_six_coarse_windows"],1)

    def test_five_or_fewer_completed_coarse_swing_events_are_not_candidates(self):
        coarse,fine,t=synthetic()
        for n in range(2,6):
            cutoff=coarse[n-1].confirmed_ms
            earlier=[e for e in fine if e.confirmed_ms<=cutoff]
            x=v107.enumerate_event_prefixes(earlier,coarse[:n],cutoff)
            self.assertEqual(x["all_consecutive_six_coarse_windows"],0)
            self.assertEqual(x["necessary_partial_skeleton_passes"],0)
            self.assertEqual(x["insufficient_initial_coarse_context_events"],n)
            self.assertEqual(x["candidate_ledger"],[])

    def test_empty_observer_ledger_does_not_invent_decisions(self):
        _,_,asof=synthetic()
        x=v107.enumerate_event_prefixes([],[],asof)
        self.assertEqual(x["all_consecutive_six_coarse_windows"],0)
        self.assertEqual(x["all_observed_coarse_confirmed_events"],0)
        self.assertFalse(x["entry_signal"])

    def test_arbitrary_missing_coarse_middle_event_not_silently_repaired(self):
        coarse,fine,t=synthetic()
        shortened=coarse[:3]+coarse[4:]
        with self.assertRaisesRegex(ValueError,"nonchronological or relabeled"):
            v107.enumerate_event_prefixes(fine,shortened,t)

    def test_future_unconfirmed_fine_event_never_accepted_as_known(self):
        coarse,fine,t=synthetic()
        fake=pivot("HIGH",60,140,2)
        with self.assertRaisesRegex(ValueError,"future"):
            v107.enumerate_event_prefixes(fine+[fake],coarse,t)

    def test_forged_source_event_index_or_clock_aborts_all_census(self):
        coarse,fine,t=synthetic()
        broken=replace(fine[1],center_index=fine[1].center_index-1)
        with self.assertRaisesRegex(ValueError,"index/time"):
            v107.enumerate_event_prefixes([fine[0],broken]+fine[2:],coarse,t)

    def test_future_dataset_cannot_be_opened_today(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(v107,"utc_ms",return_value=v107.v102.locked_range()[1]-1):
                with patch.object(v107.v104,"audit_archive_independent") as audit:
                    with self.assertRaisesRegex(ValueError,"NO_ARCHIVE_READ"):
                        v107.evaluate_future_sealed_archive(Path(tmp))
                    audit.assert_not_called()

    def test_untrusted_folder_type_refused_without_access(self):
        with self.assertRaisesRegex(ValueError,"explicit future"):
            v107.evaluate_future_sealed_archive("C:/temp/fake")

    def test_frozen_rulebook_cannot_be_silently_rewritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/"V107.json"
            a=v107.freeze_rulebook(path)
            self.assertEqual(a,v107.freeze_rulebook(path))
            self.assertEqual(a["source_rows_accessed"] if "source_rows_accessed" in a
                             else a["real_source_rows"],0)
            self.assertEqual(a["trades"],0)
            self.assertEqual(json.loads(path.read_text())["orders"],0)
            path.write_text("{}")
            with self.assertRaisesRegex(ValueError,"modified"):
                v107.freeze_rulebook(path)

    def test_no_real_pnl_or_false_positive_measurement_in_protocol(self):
        r=v107.rulebook()
        self.assertEqual(r["all_consecutive_coarse_window_size"],6)
        self.assertEqual(r["candidate_selection"],
                         "NO_SKIPS_ALL_SLIDING_WINDOWS_WITH_SIX_COARSE_EVENTS")
        self.assertIn("false_positive_rate",r["not_measured_outcomes"])
        self.assertTrue(r["source_must_pass_both_v103_and_v104_auditors"])
        self.assertTrue(r["future_source_not_read_or_fetched_during_v107"])
        self.assertFalse(r["live_enabled"])
        self.assertFalse(r["paper_eligible"])
        self.assertEqual(r["orders"],0)
        self.assertIsNone(v107.ORDER_ADAPTER)
        self.assertTrue(v107.V52_UNCHANGED)

    def test_multiple_blockers_counted_but_denominator_unique(self):
        coarse,fine,t=synthetic()
        coarse[2]=replace(coarse[2],center_close=coarse[0].center_close)
        coarse[5]=replace(coarse[5],center_close=coarse[3].center_close)
        final=fine[-1]
        fine[-1]=replace(final,center_close=coarse[3].center_close)
        x=v107.enumerate_event_prefixes(fine,coarse,t)
        self.assertEqual(x["all_consecutive_six_coarse_windows"],1)
        self.assertEqual(x["necessary_partial_skeleton_rejections"],1)
        self.assertEqual(sum(x["first_rejection_mutually_exclusive_counts"].values()),1)
        self.assertGreaterEqual(sum(x["all_rejection_reasons_overlapping_counts"].values()),2)
        self.assertIn("WAVE2_BREACHES_OR_TOUCHES_WAVE0_ORIGIN",
                      x["all_rejection_reasons_overlapping_counts"])

    def test_corrupted_postwindow_archive_abstains_before_classification(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)
            with patch.object(v107,"utc_ms",return_value=v107.v102.locked_range()[1]+MIN):
                with patch.object(v107.v104,"audit_archive_independent",
                                  side_effect=ValueError("SOURCE_HASH_CONFLICT")):
                    with patch.object(v107.v99,"observe_scale") as classifier:
                        with self.assertRaisesRegex(ValueError,"SOURCE_HASH_CONFLICT"):
                            v107.evaluate_future_sealed_archive(path)
                        classifier.assert_not_called()

    def test_status_does_not_read_market_or_claim_success(self):
        status=v107.static_status()
        self.assertEqual(status["v107_source_data_fetched"],0)
        self.assertEqual(status["real_market_patterns_tested"],0)
        self.assertEqual(status["orders"],0)
        self.assertFalse(status["entry_signal"])
