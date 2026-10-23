"""Synthetic acceptance-screen tests; no market data, broker, or paper access."""
import copy
from datetime import datetime, timedelta, timezone
from unittest import TestCase, main
from research.nexus_mr40_forward_closed_trade_decision_gate_v1 import assess, when, finite

PROTO={
  "schema":"nexus.mr40.forward_closed_trade_decision_gate.v1",
  "min_fully_closed_positions_per_arm":12,
  "safety":{"auto_promote":False}
}

def sample(n=12):
    first=datetime(2026,10,24,tzinfo=timezone.utc)
    start=lambda dt:dt.isoformat().replace("+00:00","Z")
    def records(prefix,trade_pnl):
        return [
          {"trade_uid":prefix+str(i),"entry_utc":start(first+timedelta(days=i)),
           "exit_utc":start(first+timedelta(days=i,hours=2)),
           "closed":True,"open_exposure":False,
           "net_pnl_conservative_USDT":str(trade_pnl)}
          for i in range(n)
        ]
    return {
     "schema":"nexus.mr40.prospective_dual_arm_economic_claim.v1",
     "source_market":"Bybit BTCUSDT Spot",
     "execution_mode":"research_only",
     "historical_seen_47_included":False,
     "precommitted_locked_criteria":True,
     "same_observation_window_both_arms":True,
     "initial_reference_capital_USDT":"500",
     "forward_start_utc":start(first),
     "forward_end_utc":start(first+timedelta(days=n+1)),
     "arms":{
      "baseline":{"arm":"baseline","cost_profile":"conservative",
        "fully_closed_trades":records("b",1),"net_pnl_conservative_USDT":str(n),
        "modeled_intratrade_low_DD_pct":"10"},
      "candidate":{"arm":"candidate","cost_profile":"conservative",
        "fully_closed_trades":records("c",2),"net_pnl_conservative_USDT":str(n*2),
        "modeled_intratrade_low_DD_pct":"8"}
     }
    }


class ProspectiveNumericGateTests(TestCase):
    def test_exactly_12_each_all_numeric_gates_pass_but_no_promotion(self):
        z=assess(sample(),PROTO)
        self.assertTrue(z["necessary_numeric_conditions_pass"])
        self.assertFalse(z["paper_or_live_promotion_authorized"])
        self.assertFalse(z["economic_edge_verified"])
        self.assertFalse(z["authentic_market_source_verified"])

    def test_11_positions_rejected(self):
        x=sample(11)
        self.assertFalse(assess(x,PROTO)["necessary_numeric_conditions_pass"])

    def test_candidate_cannot_reduce_profit(self):
        x=sample()
        for t in x["arms"]["candidate"]["fully_closed_trades"]:
            t["net_pnl_conservative_USDT"]="0.5"
        x["arms"]["candidate"]["net_pnl_conservative_USDT"]="6"
        self.assertFalse(assess(x,PROTO)["conservative_net_profit_preserved_numerically"])

    def test_low_dd_must_improve_at_least_20pct(self):
        x=sample()
        x["arms"]["candidate"]["modeled_intratrade_low_DD_pct"]="8.00000001"
        self.assertFalse(assess(x,PROTO)["modeled_low_DD_at_least_20pct_better_numerically"])

    def test_no_prior_47_trades(self):
        x=sample()
        x["historical_seen_47_included"]=True
        with self.assertRaisesRegex(ValueError,"historical_leakage"):
            assess(x,PROTO)

    def test_trade_start_before_cutoff_rejected(self):
        x=sample()
        x["forward_start_utc"]="2026-10-22T00:00:00Z"
        with self.assertRaisesRegex(ValueError,"forward_window_not_after_lock"):
            assess(x,PROTO)

    def test_open_position_rejected(self):
        x=sample()
        x["arms"]["baseline"]["fully_closed_trades"][0]["open_exposure"]=True
        with self.assertRaisesRegex(ValueError,"incomplete_or_open"):
            assess(x,PROTO)

    def test_partial_profit_report_rejected(self):
        x=sample()
        x["arms"]["candidate"]["net_pnl_conservative_USDT"]="999"
        with self.assertRaisesRegex(ValueError,"declared_pnl_not_equal"):
            assess(x,PROTO)

    def test_duplicate_trade_ids_rejected(self):
        x=sample()
        x["arms"]["baseline"]["fully_closed_trades"][0]["trade_uid"]="b1"
        with self.assertRaisesRegex(ValueError,"duplicate_trade_uid"):
            assess(x,PROTO)

    def test_overlapping_spot_positions_rejected(self):
        x=sample()
        x["arms"]["baseline"]["fully_closed_trades"][1]["entry_utc"]=x["arms"]["baseline"]["fully_closed_trades"][0]["entry_utc"]
        with self.assertRaisesRegex(ValueError,"long_only_trade_overlap"):
            assess(x,PROTO)

    def test_non_UTC_offset_and_nan_rejected(self):
        x=sample()
        x["arms"]["baseline"]["fully_closed_trades"][0]["entry_utc"]="2026-10-24T12:00:00+02:00"
        with self.assertRaisesRegex(ValueError,"timestamp_must_be_UTC_Z"):
            assess(x,PROTO)
        self.assertRaisesRegex(ValueError,"nonfinite_decimal",finite,"NaN")

    def test_different_venue_or_profile_not_allowed(self):
        x=sample()
        x["source_market"]="LBank"
        with self.assertRaisesRegex(ValueError,"wrong_venue"):
            assess(x,PROTO)
        x=sample()
        x["arms"]["baseline"]["cost_profile"]="optimistic"
        with self.assertRaisesRegex(ValueError,"arm_or_cost_profile_mismatch"):
            assess(x,PROTO)

    def test_broken_protocol_no_auto_promote_fails(self):
        p=copy.deepcopy(PROTO)
        p["safety"]["auto_promote"]=True
        with self.assertRaisesRegex(ValueError,"locked_12"):
            assess(sample(),p)

if __name__=="__main__":
    main()
