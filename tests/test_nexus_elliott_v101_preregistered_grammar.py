"""V101 preregistered impulse grammar -- synthetic-only CI contract."""
import json
import tempfile
import unittest
from dataclasses import replace
from decimal import Decimal as D
from pathlib import Path

from research.elliott_v99_causal_scale.scale_v99 import ObservedSwing
from research.elliott_v101_preregistered_grammar import grammar_v101 as v101

T=1790006400000
M=60000


def swing(kind,idx,price,lag):
    return ObservedSwing(
        kind,T+idx*M,T+(idx+lag+1)*M,
        D(str(price)),D(str(price)),idx,idx+lag)


def synthetic():
    indexes=[0,10,20,30,40,50,60]
    prices=[110,100,120,110,140,125,150]
    coarse=[swing("HIGH" if i%2==0 else "LOW",idx,prices[i],2)
            for i,idx in enumerate(indexes)]
    fine=[swing(coarse[1].kind,10,prices[1],1)]
    for leg,n in enumerate(v101.FIXED_INTERIOR_SWINGS):
        left=indexes[leg+1]
        right=indexes[leg+2]
        for j in range(n):
            idx=left+(j+1)*(right-left)//(n+1)
            kind="LOW" if fine[-1].kind=="HIGH" else "HIGH"
            fine.append(swing(kind,idx,100+idx,1))
        boundary=coarse[leg+2]
        fine.append(swing(boundary.kind,indexes[leg+2],prices[leg+2],1))
    return fine,coarse,coarse[-1].confirmed_ms


class PreregisteredV101Tests(unittest.TestCase):
    def test_complete_synthetic_impulse_screen_never_certifies_market(self):
        fine,coarse,asof=synthetic()
        result=v101.inspect_window(coarse,fine,asof)
        self.assertTrue(result["necessary_geometry_and_degree_skeleton_pass"])
        self.assertEqual(result["observed_interior_counts"],[4,2,4,2,4])
        self.assertEqual(result["hard_rejections"],[])
        self.assertFalse(result["full_elliott_market_wave_proven"])
        self.assertFalse(result["pattern_position_proven"])
        self.assertFalse(result["entry_signal"])
        self.assertFalse(result["paper_eligible"])
        self.assertIsNone(result["net_pnl"])

    def test_missing_two_pivots_cannot_be_silently_pruned(self):
        fine,coarse,asof=synthetic()
        truncated=[x for x in fine if x.center_index not in (12,14)]
        result=v101.inspect_window(coarse,truncated,asof)
        self.assertFalse(result["necessary_geometry_and_degree_skeleton_pass"])
        self.assertIn("LEG1_UNPRUNED_FINE_COUNT_NOT_FROZEN_DEGREE",
                      result["hard_rejections"])

    def test_parent_geometry_not_optimized_when_wave4_overlaps(self):
        fine,coarse,asof=synthetic()
        coarse[5]=replace(coarse[5],center_close=D("119"))
        fine=[replace(x,center_close=D("119"))
              if x.center_ms==coarse[5].center_ms else x for x in fine]
        result=v101.inspect_window(coarse,fine,asof)
        self.assertIn("WAVE4_OVERLAPS_WAVE1_NONDIAGONAL",
                      result["hard_rejections"])

    def test_wrong_position_missing_predecessor_is_refused(self):
        fine,coarse,asof=synthetic()
        with self.assertRaisesRegex(ValueError,"seven"):
            v101.inspect_window(coarse[1:],fine,asof)

    def test_future_decision_after_original_confirmation_refused(self):
        fine,coarse,asof=synthetic()
        with self.assertRaisesRegex(ValueError,"never later"):
            v101.inspect_window(coarse,fine,asof+M)

    def test_premature_last_coarse_confirmation_refused(self):
        fine,coarse,asof=synthetic()
        with self.assertRaisesRegex(ValueError,"never later"):
            v101.inspect_window(coarse,fine,asof-M)

    def test_different_fine_boundary_price_does_not_promote(self):
        fine,coarse,asof=synthetic()
        ix=next(i for i,x in enumerate(fine) if x.center_ms==coarse[2].center_ms)
        fine[ix]=replace(fine[ix],center_close=D("119"))
        result=v101.inspect_window(coarse,fine,asof)
        self.assertIn("LEG1_MISSING_CAUSAL_FINE_RIGHT_BOUNDARY",
                      result["hard_rejections"])

    def test_forged_future_fine_center_rejected(self):
        fine,coarse,asof=synthetic()
        fine[-1]=replace(fine[-1],confirmed_index=65,
                         confirmed_ms=T+66*M)
        with self.assertRaisesRegex(ValueError,"future"):
            v101.inspect_window(coarse,fine,asof)

    def test_unaligned_asof_rejected(self):
        fine,coarse,asof=synthetic()
        with self.assertRaisesRegex(ValueError,"cutoff"):
            v101.inspect_window(coarse,fine,asof-1)

    def test_source_index_mismatch_rejected(self):
        fine,coarse,asof=synthetic()
        fine[1]=replace(fine[1],center_index=11)
        with self.assertRaisesRegex(ValueError,"index/time"):
            v101.inspect_window(coarse,fine,asof)

    def test_frozen_rulebook_future_period_and_no_lookahead(self):
        r=v101.manifest()
        self.assertEqual(r["window_start_utc"],"2026-11-16T00:00:00Z")
        self.assertEqual(r["window_end_exclusive_utc"],"2026-11-30T00:00:00Z")
        self.assertEqual(r["source_rows_per_pair"],20160)
        self.assertEqual(r["symbol_universe"],["BTCUSDT","ETHUSDT"])
        self.assertEqual(r["market_source"],"BYBIT_SPOT_PUBLIC_CLOSED_1M")
        self.assertEqual(r["candidate_enumeration"],
                         "ALL_SLIDING_SEVEN_CONSECUTIVE_COARSE_PIVOTS")
        self.assertTrue(r["data_not_fetched_in_v101"])
        self.assertFalse(r["market_degree_authenticated"])
        self.assertFalse(r["paper_eligible"])

    def test_freeze_rulebook_is_byte_deterministic_and_refuses_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/"V101_PREREGISTRATION.json"
            first=v101.freeze_unopened_rulebook(p)
            self.assertEqual(p.read_bytes(),v101.manifest_bytes())
            self.assertEqual(first["sha256"],v101.prereg_sha())
            second=v101.freeze_unopened_rulebook(p)
            self.assertEqual(first,second)
            p.write_text("{}")
            with self.assertRaisesRegex(ValueError,"differs"):
                v101.freeze_unopened_rulebook(p)

    def test_unknown_order_connector_never_created(self):
        self.assertTrue(v101.RESEARCH_ONLY)
        self.assertFalse(v101.LIVE_ENABLED)
        self.assertFalse(v101.PAPER_ELIGIBLE)
        self.assertFalse(v101.ENTRY_SIGNAL)
        self.assertTrue(v101.V52_UNCHANGED)
        self.assertIsNone(v101.ORDER_ADAPTER)
        self.assertEqual(v101.CERTIFIED_ELLIOTT_PATTERNS,0)

    def test_old_source_cannot_be_presented_as_future_validation(self):
        from research.elliott_v99_causal_scale.scale_v99 import CloseMinute
        old=[CloseMinute(T+i*M,D("100")) for i in range(80)]
        with self.assertRaisesRegex(ValueError,"locked future-window"):
            v101.enumerate_all_source_candidates(old,T+80*M)

    def test_incomplete_future_source_refused_before_any_candidate(self):
        from research.elliott_v99_causal_scale.scale_v99 import CloseMinute
        from datetime import datetime
        start=int(datetime.fromisoformat(v101.WINDOW_START_UTC.replace("Z","+00:00")).timestamp()*1000)
        short=[CloseMinute(start+i*M,D("100")) for i in range(80)]
        with self.assertRaisesRegex(ValueError,"locked future-window"):
            v101.enumerate_all_source_candidates(short,start+80*M)

    def test_frozen_prereg_json_has_no_market_outcomes(self):
        raw=json.loads(v101.manifest_bytes())
        self.assertEqual(raw["status"],"RULES_FROZEN_BEFORE_DATA_AVAILABLE_NOT_EVALUATED")
        self.assertEqual(raw["orders"],0)
        self.assertFalse(raw["profitability_demonstrated"])
        self.assertEqual(raw["wave_family"],"NONDIAGONAL_NONTRUNCATED_IMPULSE_NECESSARY_ONLY")
        self.assertEqual(raw["fixed_interior_fine_pivot_counts"],[4,2,4,2,4])
