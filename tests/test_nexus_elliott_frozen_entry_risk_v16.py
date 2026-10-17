"""Read-only numeric invariants of source-bound frozen Elliott entry diagnostics."""
import sys
import unittest
from pathlib import Path

import pandas as pd

P=Path(__file__).resolve().parents[1]/"docs"/"evidence"/"elliott-v16-entry-economics-20261015"
sys.path.insert(0,str(P))
from frozen_entry_risk_audit import (
    PROFILES,RESEARCH_ONLY,LIVE_ENABLED,AUTO_DEMO,SIMULATOR_INVOKED,
    observed_next_open_diagnostic,validate_archive_frame,
)


def fixture(profile="conservative"):
    n=35
    t=pd.date_range("2024-01-01",periods=n,freq="15min",tz="UTC")
    op=[100+i*.1 for i in range(n)]
    hi=[v+1 for v in op]
    lo=[v-1 for v in op]
    cl=[v+.2 for v in op]
    # Correction anchor predates the 14 completed bars used for mean range.
    lo[3]=98.0
    frame=pd.DataFrame(dict(timestamp=t,open=op,high=hi,low=lo,close=cl))
    i=20
    fee,slip=PROFILES[profile]
    opening=frame.iloc[i+1]["open"]
    slipped=opening*(1+float(slip)/10000)
    mean_range=2.0
    stop=slipped-1.5*mean_range
    entry={
        "atr":mean_range,"disposition":"filled","entry_reference":opening,
        "entry_slipped":slipped, "stop":stop,"fill_bar":{
            "bar_index":i+1,"open_at":str(frame.timestamp.iloc[i+1]),
            "decision_at":str(frame.timestamp.iloc[i+1]+pd.Timedelta(minutes=15))
        },"decision":{
            "bar_index":i,
            "decision_at":str(frame.timestamp.iloc[i]+pd.Timedelta(minutes=15)),
            "setup":{"lagged_elliott5_wave2_index":3.0,
                     "lagged_elliott5_wave2_low":98.0}
        }
    }
    return frame,entry


class FrozenEntryRiskV16Tests(unittest.TestCase):
    def test_read_only_no_signal(self):
        self.assertTrue(RESEARCH_ONLY)
        self.assertFalse(LIVE_ENABLED)
        self.assertFalse(AUTO_DEMO)
        self.assertFalse(SIMULATOR_INVOKED)

    def test_next_open_cost_and_structural_distance_conservative(self):
        f,e=fixture("conservative")
        r=observed_next_open_diagnostic(f,e,"conservative")
        self.assertEqual(r["status"],"EX_ANTE_STRUCTURAL_RISK_ONLY")
        self.assertEqual(r["actual_future_target_or_stop_result"],"NOT_EVALUATED")
        self.assertEqual(r["simulator_invoked"],False)
        self.assertGreater(float(r["structural_to_parent_stop_multiple"]),1)
        self.assertAlmostEqual(float(r["parent_stop_risk_per_unit"]),3)
        self.assertGreater(float(r["structural_risk_per_unit"]),4)
        self.assertGreater(float(r["projected_target_net_per_unit"]),0)
        self.assertLess(float(r["projected_stop_net_per_unit"]),0)
        self.assertLess(float(r["reference_dollar_stop_risk_before_gap_or_fees"]),10.000000001)

    def test_stress_profile_slippage_affects_input_and_output(self):
        f,e=fixture("stress")
        a=observed_next_open_diagnostic(f,e,"stress")
        fc,ec=fixture("conservative")
        b=observed_next_open_diagnostic(fc,ec,"conservative")
        self.assertGreater(float(a["entry_slipped"]),float(b["entry_slipped"]))
        self.assertGreater(float(a["break_even_target_hit_fraction_if_full_2r"]),
                           float(b["break_even_target_hit_fraction_if_full_2r"]))

    def test_cannot_confuse_closed_decision_with_next_open(self):
        f,e=fixture()
        e["entry_reference"]=f.iloc[20]["close"]
        with self.assertRaisesRegex(AssertionError,"next-open fill"):
            observed_next_open_diagnostic(f,e,"conservative")

    def test_cannot_invent_slipped_execution(self):
        f,e=fixture()
        e["entry_slipped"]+=3
        with self.assertRaisesRegex(AssertionError,"slipped fill"):
            observed_next_open_diagnostic(f,e,"conservative")

    def test_correction_low_is_bound_to_raw(self):
        f,e=fixture()
        e["decision"]["setup"]["lagged_elliott5_wave2_low"]=97.5
        with self.assertRaisesRegex(AssertionError,"raw correction low"):
            observed_next_open_diagnostic(f,e,"conservative")

    def test_next_open_bar_index_is_exactly_decision_plus_one(self):
        f,e=fixture()
        e["fill_bar"]["bar_index"]=22
        with self.assertRaisesRegex(AssertionError,"causal decision"):
            observed_next_open_diagnostic(f,e,"conservative")

    def test_mismatched_utc_fill_timestamp_fails_closed(self):
        f,e=fixture()
        e["fill_bar"]["open_at"]="2024-01-01T22:00:00+00:00"
        with self.assertRaisesRegex(AssertionError,"next-open timing"):
            observed_next_open_diagnostic(f,e,"conservative")

    def test_mean_high_low_proxy_is_not_true_range_name(self):
        f,e=fixture()
        r=observed_next_open_diagnostic(f,e,"conservative")
        self.assertEqual(float(r["parent_proxy_atr"]),2.0)
        self.assertGreater(float(r["prior_completed_true_range_mean"]),0)
        self.assertIn("structural_risk_to_prior_true_range_mean",r)

    def test_partial_gapped_source_rejected(self):
        f,_=fixture()
        f=f.drop(index=4).reset_index(drop=True)
        with self.assertRaisesRegex(ValueError,"not 15m"):
            validate_archive_frame(f)

    def test_invalid_ohlc_rejected(self):
        f,_=fixture()
        f.loc[4,"low"]=f.loc[4,"high"]+1
        with self.assertRaisesRegex(ValueError,"OHLC"):
            validate_archive_frame(f)

    def test_unknown_profile_or_nonfilled_denied(self):
        f,e=fixture()
        with self.assertRaises(ValueError):
            observed_next_open_diagnostic(f,e,"live")
        e["disposition"]="denied"
        with self.assertRaises(ValueError):
            observed_next_open_diagnostic(f,e,"conservative")


if __name__=="__main__":
    unittest.main()
