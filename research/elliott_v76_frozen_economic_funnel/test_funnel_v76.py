"""V76 deterministic legacy cost decomposition and event admission regressions."""
import unittest
from decimal import Decimal
from copy import deepcopy
from funnel_v76 import (
    trade_economics,aggregate,event_funnel,hashfile,
    RESEARCH_ONLY,ENTRY_SIGNAL,PAPER_ELIGIBLE,LIVE_ENABLED
)

def sample_trade(**overrides):
    t=dict(quantity="1",entry_reference="100",exit_reference="110",
           entry_slipped="101",exit_slipped="109",entry_fee="1",
           exit_fee="1",net_pnl="6",exit_reason="target")
    t.update(overrides)
    return t

def synthetic_six_cells():
    counts=[
        ("BTCUSDT","train",6,1),("BTCUSDT","validation",5,1),
        ("BTCUSDT","historically_inspected_test",0,0),
        ("ETHUSDT","train",6,4),("ETHUSDT","validation",4,3),
        ("ETHUSDT","historically_inspected_test",3,1)]
    out=[]
    for symbol,part,size,n in counts:
        ev=[]
        attempts=[]
        trades=[]
        for i in range(size):
            stamp=f"2024-01-01T{i:02d}:15:00Z"
            kind="scheduled_next_open" if i<n else "signal_denied"
            ev.append(dict(bar_index=i+20,decision_at=stamp,admission=kind,
                denial_fields=[] if i<n else ["h1_vol_ok"]))
            if i<n:
                attempts.append(dict(decision=dict(bar_index=i+20,decision_at=stamp),
                                     disposition="filled"))
                trades.append(dict(trade_index=i))
        out.append(dict(symbol=symbol,part=part,profile="conservative",
                        price_events=ev,entry_attempts=attempts,trades=trades))
    return out

class V76LegacyLossFunnelTests(unittest.TestCase):
    def test_exact_gross_slippage_fees_net_decomposition(self):
        result=trade_economics(sample_trade())
        self.assertEqual(result["gross"],Decimal(10))
        self.assertEqual(result["slippage"],Decimal(2))
        self.assertEqual(result["fees"],Decimal(2))
        self.assertEqual(result["net"],Decimal(6))
    def test_losing_stop_is_not_hidden_by_positive_winner(self):
        winner=trade_economics(sample_trade())
        stop=trade_economics(sample_trade(exit_reference="96",
            entry_slipped="101",exit_slipped="95",
            exit_reason="stop",net_pnl="-8"))
        summary=aggregate([winner,stop])
        self.assertEqual(summary["net"],Decimal(-2))
        self.assertEqual(summary["exit_counts"],{"target":1,"stop":1})
        self.assertEqual(summary["observed_win_fraction"],Decimal("0.5"))
        self.assertEqual(summary["empirical_breakeven_win_fraction"],Decimal(8)/14)
    def test_malformed_net_rejected(self):
        with self.assertRaisesRegex(ValueError,"TRADE_NET"):
            trade_economics(sample_trade(net_pnl="60"))
    def test_unmodeled_favorable_slippage_rejected(self):
        with self.assertRaisesRegex(ValueError,"FAVORABLE_SLIPPAGE"):
            trade_economics(sample_trade(entry_slipped="98",net_pnl="9"))
    def test_zero_position_invalid(self):
        with self.assertRaisesRegex(ValueError,"NEGATIVE_OR_INVALID"):
            trade_economics(sample_trade(quantity="0"))
    def test_24_candidates_10_admitted_14_denied(self):
        r=event_funnel(synthetic_six_cells())
        self.assertEqual((r["price_events"],r["scheduled"],r["denied"]),
                         (24,10,14))
        self.assertEqual(r["denial_field_hits"]["h1_vol_ok"],14)
    def test_missing_denial_fields_rejected(self):
        c=synthetic_six_cells()
        c[0]["price_events"][3]["denial_fields"]=[]
        with self.assertRaisesRegex(ValueError,"DENIAL_HAS_NO_REASON"):
            event_funnel(c)
    def test_dropped_attempt_rejected(self):
        c=synthetic_six_cells();c[0]["entry_attempts"]=[]
        with self.assertRaisesRegex(ValueError,"EVENT_SCHEDULED_ATTEMPT_FILL"):
            event_funnel(c)
    def test_duplicated_decision_rejected(self):
        c=synthetic_six_cells()
        c[0]["price_events"][2]["bar_index"]=c[0]["price_events"][3]["bar_index"]
        c[0]["price_events"][2]["decision_at"]=c[0]["price_events"][3]["decision_at"]
        with self.assertRaisesRegex(ValueError,"DUPLICATE_EVENT"):
            event_funnel(c)
    def test_read_only_permanently(self):
        self.assertTrue(RESEARCH_ONLY)
        self.assertFalse(ENTRY_SIGNAL or PAPER_ELIGIBLE or LIVE_ENABLED)

if __name__=="__main__":unittest.main()
