"""V115 source-isolation tests: synthetic bars, not additional market data."""
import copy
import json
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from test_nexus_elliott_v108_forward_outcomes import bar
from test_nexus_elliott_v111_source_capacity import sample
from research.elliott_v115_historical_profile import profile_v115 as v115
from research.elliott_v102_bybit_intake import intake_v102 as v102
from research.elliott_v111_source_capacity import bridge_v111 as v111
from research.elliott_v113_incremental_audit import incremental_v113 as v113

MIN=60000
T=1719792000000

def synthetic_80(n=80):
    return {
        symbol:[bar(T+i*MIN,100,100,100,100) for i in range(n)]
        for symbol in v115.SYMBOLS
    }


class V115PreinspectedSourcePerformanceContract(unittest.TestCase):
    def test_two_pair_zero_event_corpus_uses_full_v99_v111_v113(self):
        physical=synthetic_80()
        streams=v115.as_source_streams(physical)
        self.assertEqual(set(streams),set(v115.SYMBOLS))
        for coarse,fine,bars in streams.values():
            self.assertEqual(coarse,[])
            self.assertEqual(fine,[])
            self.assertEqual(len(bars),80)
        study=v111.portfolio_census_from_source_streams(streams)
        verified=v113.audit_streaming(streams,study)
        self.assertEqual(verified["all_original_candidate_windows"],0)
        self.assertEqual(verified["all_mandatory_causal_checkpoints"],2)
        self.assertEqual(study["orders"],0)
        self.assertEqual(v115.bounded_summary(study)[
            "all_hypothetical_source_proposals"],0)

    def test_real_source_loader_rejects_unknown_market_before_file_read(self):
        with self.assertRaisesRegex(ValueError,"only original preinspected"):
            v115.historical_seven_fields("XRPUSDT",{},{})

    def test_complete_original_btc_and_eth_period_required(self):
        physical=synthetic_80()
        del physical["ETHUSDT"]
        with self.assertRaisesRegex(ValueError,"complete original two-symbol"):
            v115.as_source_streams(physical)

    def test_both_symbol_gap_rejected_before_decision_census(self):
        physical=synthetic_80()
        physical["ETHUSDT"][6]=bar(T+7*MIN,100,100,100,100)
        with self.assertRaisesRegex(ValueError,"gap/duplicate"):
            v115.as_source_streams(physical)

    def test_coarse_and_fine_no_future_events_of_partial_source(self):
        physical=synthetic_80()
        streams=v115.as_source_streams(physical)
        self.assertEqual(streams["BTCUSDT"][2][-1].ms+MIN,
                         T+80*MIN)
        self.assertEqual(len(streams["ETHUSDT"][0]),0)

    def test_comparison_only_mature_first_week_reference_screens(self):
        from test_nexus_elliott_v111_source_capacity import sample
        coarse,fine,t,bars=sample(ext=2)
        first=v111.portfolio_census_from_source_streams({
            "BTCUSDT":(coarse,fine,bars)})
        later=v111.portfolio_census_from_source_streams({
            "BTCUSDT":(coarse,fine,bars+[
                bar(t+2*MIN,110,125,105,119),
                bar(t+3*MIN,110,130,90,110)
            ])})
        self.assertTrue(v115._mature_only_compare(
            first,later,t+2*MIN)["all_first_week_mature_screens_unchanged"])
        before=copy.deepcopy(later)
        before["all_original_candidate_reference_screens"][0][
            "reference_screen_status"]="FUTURE_PROFIT"
        with self.assertRaisesRegex(ValueError,"LATER_2024_BARS"):
            v115._mature_only_compare(first,before,t+2*MIN)

    def test_manifest_is_preinspected_binance_not_bybit_or_holdout(self):
        p=v115.rules()
        self.assertEqual(p["source_exchange"],"BINANCE_SPOT_NOT_BYBIT")
        self.assertEqual(p["data_status"],"REPEATEDLY_INSPECTED_NOT_INDEPENDENT_HOLDOUT")
        self.assertEqual(p["full_original_1m_per_pair"],20160)
        self.assertTrue(p["no_trading_return_or_pnl"])
        self.assertTrue(p["zero_bybit_future_market_candles"])
        self.assertEqual(p["orders"],0)
        self.assertFalse(v115.LIVE_ENABLED)
        self.assertFalse(v115.PAPER_ELIGIBLE)
        self.assertIsNone(v115.ORDER_ADAPTER)

    def test_never_overwrite_old_measured_evidence(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/"profile.json"
            path.write_text('{"not_the_profile":true}')
            with patch.object(v115,"profile_inspected_historical",
                return_value={"measure":"all_original"}):
                with self.assertRaisesRegex(ValueError,"NEVER_BE_OVERWRITTEN"):
                    v115.write_once(path)

    def test_frozen_parent_git_rulebook_and_immutability(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/"rulebook.json"
            r=v115.freeze(path)
            self.assertEqual(r,v115.freeze(path))
            self.assertEqual(r["orders"],0)
            self.assertEqual(json.loads(path.read_text())["zero_real_market_orders"],True)
            path.write_text("{}")
            with self.assertRaisesRegex(ValueError,"IMMUTABILITY"):
                v115.freeze(path)

    def test_bounded_summary_contains_all_rejections_and_no_net_pnl(self):
        data=v115.as_source_streams(synthetic_80())
        study=v111.portfolio_census_from_source_streams(data)
        summary=v115.bounded_summary(study)
        self.assertEqual(summary["all_original_six_coarse_windows"],0)
        self.assertEqual(summary["all_reference_abstentions"],0)
        self.assertIsNone(summary["real_pnl"])
        self.assertEqual(summary["orders"],0)
