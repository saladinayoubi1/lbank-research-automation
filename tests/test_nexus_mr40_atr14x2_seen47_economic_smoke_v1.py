"""Synthetic old47 ATR economic smoke guards: no new OOS or fills."""
import json,tempfile,unittest
from decimal import Decimal as D
from pathlib import Path
from research.nexus_mr40_independent_closed_signal_v1 import STEP
from research.nexus_mr40_atr14x2_seen47_economic_smoke_v1 import (
    one_portfolio,validate_lock,run,EXPECTED_FORWARD_LOCK_SHA)

def rows():
    t=1792627200000
    data=[[t+i*STEP,"100","102","98","100","1"] for i in range(24)]
    data[20][1]="110";data[20][2]="111";data[20][3]="105";data[20][4]="110"
    return data

def pair(a):
    return {
        "entry_next_open_index":16,"exit_next_open_index":20,
        "entry_signal_index":15,"exit_signal_index":19,
        "entry_next_open_ms":a[16][0],"exit_next_open_ms":a[20][0],
        "entry_next_open_price":"100","exit_next_open_price":"110",
        "window":"evaluation"
    }

class TestFixedATRHistoricalSmoke(unittest.TestCase):
    def test_baseline_fee_math_on_complete_pair(self):
        a=rows()
        out=one_portfolio(a,[pair(a)],D("0.001"),D(0),False)
        expected=D(500)*(D(1)-D("0.001"))**2*D("1.1")
        self.assertAlmostEqual(float(D(out["modeled_end_cash_usdt"])),float(expected),places=9)
        self.assertEqual(out["hypothetical_stop_low_touch_count"],0)

    def test_ATR_stop_is_active_at_entry_and_not_a_fill(self):
        a=rows()
        a[16][3]="91"
        out=one_portfolio(a,[pair(a)],D("0.001"),D(0),True)
        self.assertEqual(out["hypothetical_stop_low_touch_count"],1)
        self.assertEqual(out["gap_below_protective_stop_count"],0)
        self.assertEqual(D(out["episodes"][0]["hypothetical_stop_quote"]),D(92))
        self.assertEqual(out["episodes"][0]["hold_bars_until_proxy_exit"],1)
        self.assertTrue(out["episodes"][0]["stop_intrabar_touch_price_is_not_an_actual_fill"])

    def test_open_gap_through_stop_more_loss_than_hoped_level(self):
        a=rows()
        a[17]=[a[17][0],"90","91","85","89","1"]
        out=one_portfolio(a,[pair(a)],D("0.001"),D(0),True)
        self.assertEqual(out["gap_below_protective_stop_count"],1)
        self.assertEqual(out["episodes"][0]["closed_position_reason"],"GAP_THROUGH_AT_OPEN")
        self.assertEqual(D(out["episodes"][0]["hypothetical_stop_quote"]),D(92))
        self.assertLess(D(out["modeled_end_cash_usdt"]),D(500)*D("0.9"))

    def test_exit_open_bar_future_low_cannot_trigger_stop(self):
        a=rows()
        a[20][3]="1"  # after natural exit at OPEN; MUST not be inspected
        candidate=one_portfolio(a,[pair(a)],D("0.001"),D(0),True)
        baseline=one_portfolio(a,[pair(a)],D("0.001"),D(0),False)
        self.assertEqual(candidate["hypothetical_stop_low_touch_count"],0)
        self.assertEqual(candidate["modeled_end_cash_usdt"],baseline["modeled_end_cash_usdt"])

    def test_both_cost_scenarios_use_same_historical_pair(self):
        a=rows()
        base=one_portfolio(a,[pair(a)],D("0.001"),D(0),False)
        stress=one_portfolio(a,[pair(a)],D("0.001"),D("0.001"),False)
        self.assertLess(D(stress["modeled_end_cash_usdt"]),D(base["modeled_end_cash_usdt"]))

    def test_source_verification_does_not_overwrite_existing_research(self):
        with tempfile.TemporaryDirectory() as d:
            t=Path(d);out=t/"old47.json";out.write_text("locked")
            with self.assertRaisesRegex(ValueError,"refuse_overwrite"):
                run(t/"missing",t/"missing",t/"missing",t/"missing",out)
            self.assertEqual(out.read_text(),"locked")

    def test_no_retuning_future_lock_is_allowed(self):
        with tempfile.TemporaryDirectory() as d:
            t=Path(d)
            f=Path("research/mr40_prearm_atr14x2_forward_protocol_20261023.json")
            p=Path("research/mr40_fixed_atr14x2_seen47_diagnostic_protocol_20261023.json")
            data=json.loads(p.read_text(encoding="utf8"))
            source=f.read_bytes()
            self.assertEqual(__import__("hashlib").sha256(source).hexdigest(),EXPECTED_FORWARD_LOCK_SHA)
            validate_lock(data,source)
            data["stop"]["multiplier"]="1.5"
            with self.assertRaisesRegex(ValueError,"study_lock_drift"):
                validate_lock(data,source)

if __name__=="__main__":
    unittest.main()
