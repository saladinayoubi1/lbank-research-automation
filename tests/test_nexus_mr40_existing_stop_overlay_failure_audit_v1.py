"""Do not silently reinterpret old MR40 stop-overlay audit results."""
import copy,tempfile,unittest
from pathlib import Path
from research.nexus_mr40_existing_stop_overlay_failure_audit_v1 import (
    SOURCES,RESULT_DIGEST,select_row,read_pinned,audit_source,run)


def row(case,window,profile,pnl,dd,capital=10000):
    return {"case":case,"window":window,"profile":profile,"venue":"Bybit",
            "capital":capital,"net_pnl_usdt":pnl,
            "max_close_drawdown_pct":dd,"longest_underwater_days":3,
            "cagr_pct":4}

def make_fake_sources():
    cases={"trigger_ratchet_result":"arm2_be","early_fuse_result":"baseline",
           "partial_trim_result":"trim75at8"}
    data={}
    for key,candidate in cases.items():
        rows=[]
        for window in ("train","evaluation"):
            for profile in ("normal","stress"):
                rows.append(row("baseline",window,profile,100,15))
                if candidate!="baseline":
                    pnl,dd=(100,15) if key=="trigger_ratchet_result" else (
                        (90,16) if window=="evaluation" else (90,14))
                    rows.append(row(candidate,window,profile,pnl,dd))
        selection=({"profit":"arm2_be","efficiency":"arm2_be",
                    "profit_eligible":["arm2_be"],"efficiency_eligible":["arm2_be"]}
                   if key=="trigger_ratchet_result" else
                   {"profit":"baseline","efficiency":"trim75at8",
                    "profit_eligible":[],"efficiency_eligible":["trim75at8"]}
                   if key=="partial_trim_result" else
                   {"profit":"baseline","efficiency":"baseline",
                    "profit_eligible":[],"efficiency_eligible":[]})
        data[key]={"rows":rows,"paper_changed":False,"research_only":True,
                   "evaluation_success":{"profit":False,"efficiency":False},
                   "selection":selection}
    losers=[{"entry_utc":"2025-01-01T00:00:00+00:00",
              "exit_utc":"2025-01-02T00:00:00+00:00","holding_h":24,
              "max_completed_close_gain_pct":0,
              "baseline_pnl":-5,
              "hit_arm2_close":False,"first_arm_close_utc":None}
             for _ in range(4)]
    data["ratchet_unarmed_audit"]={"unarmed_loss_coverage":{"evaluation":{
        "losers":4,"losers_without_2pct_closed_trigger":4,"worst_unarmed":losers}}}
    data["ratchet_equal_cash_audit"]={"windows":[
        {"window":"train","profile":q,"focus_log_contribution_pct":117}
        for q in ("normal","stress")]+[
        {"window":"evaluation","profile":q,"relative_terminal_wealth_gain_pct":0}
        for q in ("normal","stress")]}
    return data

class TestPriorStopFailureAudit(unittest.TestCase):
    def test_source_facts_reproduced_without_repeating_backtests(self):
        report=audit_source(make_fake_sources())
        self.assertEqual(len(report["studies"]),3)
        self.assertTrue(report["ratchet_failure_mode"]["no_2pct_completed_close_arm_on_any_eval_loser"])
        self.assertFalse(report["research_decision"]["new_Paper_rule_authorized"])

    def test_bad_selection_fails_without_automatic_retraining(self):
        src=make_fake_sources()
        src["trigger_ratchet_result"]["selection"]["profit"]="ratchet_2_5_8"
        with self.assertRaisesRegex(ValueError,"TRAIN_SELECTION_CHANGED"):
            audit_source(src)

    def test_test_sample_reversal_fails_loudly(self):
        src=make_fake_sources()
        src["partial_trim_result"]["rows"]=[
          {**r,"net_pnl_usdt":111} if r["case"]=="trim75at8"
             and r["window"]=="evaluation" else r
          for r in src["partial_trim_result"]["rows"]]
        with self.assertRaisesRegex(ValueError,"OUTCOME_NO_LONGER_ADVERSE"):
            audit_source(src)

    def test_fake_proof_of_train_or_evaluation_success_rejected(self):
        src=make_fake_sources()
        src["early_fuse_result"]["evaluation_success"]["profit"]=True
        with self.assertRaisesRegex(ValueError,"CONCLUSION_CHANGED"):
            audit_source(src)

    def test_broken_10k_single_row_source_not_silently_accepted(self):
        src=make_fake_sources()
        src["trigger_ratchet_result"]["rows"].append(
            copy.deepcopy(src["trigger_ratchet_result"]["rows"][0]))
        with self.assertRaisesRegex(ValueError,"MISSING_OR_AMBIGUOUS_10K_RESULT"):
            audit_source(src)

    def test_prior_source_sha_is_mandatory(self):
        with tempfile.TemporaryDirectory() as td:
            d=Path(td);files={}
            for key in SOURCES:
                p=d/(key+".json")
                p.write_text('{"tampered": true}')
                files[key]=p
            with self.assertRaisesRegex(ValueError,"PINNED_SOURCE_CHANGED"):
                read_pinned(files)

    def test_no_overwrite_of_old_or_new_evidence(self):
        with tempfile.TemporaryDirectory() as td:
            d=Path(td);out=d/"audit.json";out.write_text("original")
            with self.assertRaisesRegex(ValueError,"REFUSE_OVERWRITE"):
                run({},out)
            self.assertEqual(out.read_text(),"original")

if __name__=="__main__":
    unittest.main()
