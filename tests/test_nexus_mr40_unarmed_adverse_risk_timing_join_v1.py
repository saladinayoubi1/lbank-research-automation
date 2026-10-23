"""Already observed 4h candle LOW before +2% profit armed protective stop tests."""
from __future__ import annotations
import copy,tempfile,unittest
from pathlib import Path
from research.nexus_mr40_unarmed_adverse_risk_timing_join_v1 import join,run,verify_file

def sources():
    e=[]
    old={}
    for window in ("train","evaluation"):
        old[window]={"losers":6 if window=="train" else 4,
                     "losers_without_2pct_closed_trigger":4,
                     "worst_unarmed":[]}
        for i in range(4):
            day=i+1+(0 if window=="train" else 10)
            a=f"2025-01-{day:02d}T00:00:00+00:00"
            b=f"2025-01-{day:02d}T08:00:00+00:00"
            low=("15" if window=="evaluation" else "8") if i==0 else (
                "7" if i==1 else "3")
            hit5= int(low)>=5
            hit10=int(low)>=10
            events={}
            for val in ("5","10","15"):
                events[val]=({"bar_start_utc":a,"bar_end_utc":b,
                              "hour_age_at_bar_start":0,
                              "band":"EARLY_0_TO_24_HOURS"}
                             if int(low)>=int(val) else None)
            e.append({"entry_open_utc":a,"exit_open_utc":b,
                      "window":window,"trade_index":len(e)+1,
                      "whole_position_adverse_price_MAE_pct":low,
                      "first_threshold_breach":events})
            old[window]["worst_unarmed"].append({
                "entry_utc":a,"exit_utc":b,"hit_arm2_close":False,
                "first_arm_close_utc":None,"max_completed_close_gain_pct":0,
                "baseline_pnl":-100})
    # real old independent history has 47 episodes. Synthetics fill others,
    # never used for execution results.
    for j in range(39):
        e.append({"entry_open_utc":f"2023-01-01T{j:02d}:00:00+00:00",
                  "exit_open_utc":f"2023-01-02T{j:02d}:00:00+00:00"})
    # ensure eval profile exactly two >=5 and one >=10, train similarly
    for g in ("train","evaluation"):
        old[g]["losers_without_2pct_closed_trigger"]=4
    return ({"per_position":e,"group_stats":{"all_47":{"positions":47}}},
            {"unarmed_loss_coverage":old},
            {"ratchet_failure_mode":{
                "evaluation_baseline_loss_makers":4,
                "no_2pct_completed_close_arm_on_any_eval_loser":True}})

class TestPinnedPreArmRiskJoin(unittest.TestCase):
    def test_historical_unarmed_loser_sources_have_unique_event_joins(self):
        a,b,c=sources()
        x=join(a,b,c)
        self.assertEqual(x["windows"]["evaluation"]["unarmed_loser_count_with_candle_low_5pct"],2)
        self.assertEqual(x["windows"]["evaluation"]["unarmed_loser_count_with_candle_low_10pct"],1)
        self.assertFalse(x["decision"]["paper_or_live_promotion_authorized"])

    def test_unchanged_stop_arm_loser_must_never_be_marked_armed(self):
        a,b,c=sources()
        b["unarmed_loss_coverage"]["evaluation"]["worst_unarmed"][0]["hit_arm2_close"]=True
        with self.assertRaisesRegex(ValueError,"UNARMED_EVENT_MARKET_CLOCK_OR_GAIN_CONTRADICTION"):
            join(a,b,c)

    def test_duplicate_market_episode_identity_cannot_bypass_consistency(self):
        a,b,c=sources()
        a["per_position"][0]["entry_open_utc"]=a["per_position"][1]["entry_open_utc"]
        a["per_position"][0]["exit_open_utc"]=a["per_position"][1]["exit_open_utc"]
        with self.assertRaisesRegex(ValueError,"DUPLICATE_FROZEN_EPISODE"):
            join(a,b,c)

    def test_false_price_low_threshold_presence_fails(self):
        a,b,c=sources()
        pos=next(x for x in a["per_position"] if x.get("whole_position_adverse_price_MAE_pct")=="15")
        pos["first_threshold_breach"]["10"]=None
        with self.assertRaisesRegex(ValueError,"LOW_THRESHOLD_VS_FULL_MAE_INCONSISTENT"):
            join(a,b,c)

    def test_never_compare_different_quote_capitals_as_equal_cash(self):
        a,b,c=sources()
        x=join(a,b,c)
        self.assertTrue(x["equity_models_not_interchangeable"])
        self.assertTrue(all(
           "prior_10k_quote_baseline_PnL_not_comparable_to_500_USDT" in z
           for w in x["windows"].values() for z in w["episodes"]))

    def test_verified_source_sha_enforced(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)/"fake.json";p.write_text('{"digest":"fake"}')
            with self.assertRaisesRegex(ValueError,"SOURCE_SHA_DRIFT"):
                verify_file(p,"adverse_timing")

    def test_do_not_overwrite_existing_output(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)/"audit.json";p.write_text("untouched")
            with self.assertRaisesRegex(ValueError,"REFUSE_OVERWRITE"):
                run(Path(t)/"missing",Path(t)/"missing",Path(t)/"missing",p)
            self.assertEqual(p.read_text(),"untouched")

if __name__=="__main__":
    unittest.main()
