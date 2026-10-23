"""Synthetic 4h adverse LOW timing diagnostics, no actual stop fills."""
import tempfile,unittest
from pathlib import Path
from decimal import Decimal as D
from research.nexus_mr40_all47_adversity_timing_v1 import inspect_one,aggregate,band,run,validate_protocol

def rows(n):
    return [[i*14400000,"100","101","99","100","1"] for i in range(n+1)]

def pair(b,n):
    return {"entry_next_open_index":0,"exit_next_open_index":n,
        "entry_next_open_ms":b[0][0],"exit_next_open_ms":b[n][0],
        "entry_next_open_price":"100","entry_signal_index":0,"exit_signal_index":n-1}

class TestFixedAdversityWindows(unittest.TestCase):
    def test_crossing_hours_fixed_and_no_lookahead(self):
        b=rows(32);b[2][3]="94";b[7][3]="89";b[31][3]="84"
        out=inspect_one(b,pair(b,32))
        self.assertEqual(out["first_threshold_breach"]["5"]["band"],"EARLY_0_TO_24_HOURS")
        self.assertEqual(out["first_threshold_breach"]["10"]["band"],"MIDDLE_24_TO_120_HOURS")
        self.assertEqual(out["first_threshold_breach"]["15"]["band"],"LATE_FROM_120_HOURS")
        self.assertEqual(out["first_threshold_breach"]["10"]["hour_age_at_bar_start"],28)
        self.assertEqual(D(out["whole_position_adverse_price_MAE_pct"]),D(16))
        self.assertEqual(out["by_time_band"]["EARLY_0_TO_24_HOURS"]["held_bars"],6)
        self.assertEqual(out["by_time_band"]["MIDDLE_24_TO_120_HOURS"]["held_bars"],24)
        self.assertEqual(out["by_time_band"]["LATE_FROM_120_HOURS"]["held_bars"],2)

    def test_exit_open_bar_extreme_does_not_contribute(self):
        b=rows(1);b[1][3]="1"
        out=inspect_one(b,pair(b,1))
        self.assertEqual(D(out["whole_position_adverse_price_MAE_pct"]),D(1))
        self.assertIsNone(out["first_threshold_breach"]["5"])

    def test_exposure_denominators_not_assumed_equal(self):
        short=rows(2);long=rows(31);long[30][3]="89"
        a=inspect_one(short,pair(short,2))
        b=inspect_one(long,pair(long,31))
        s=aggregate([a,b])
        late=s["bands"]["LATE_FROM_120_HOURS"]
        self.assertEqual(late["n_all_positions"],2)
        self.assertEqual(late["n_exposed_positions"],1)
        self.assertEqual(late["n_with_FIRST_breach_during_band"]["10"],1)
        self.assertEqual(s["ever_breached"]["10"],1)

    def test_window_boundaries_are_not_adjustable_by_results(self):
        self.assertEqual(band(20),"EARLY_0_TO_24_HOURS")
        self.assertEqual(band(24),"MIDDLE_24_TO_120_HOURS")
        self.assertEqual(band(116),"MIDDLE_24_TO_120_HOURS")
        self.assertEqual(band(120),"LATE_FROM_120_HOURS")
        with self.assertRaisesRegex(ValueError,"invalid_4h_offset"):
            band(121)

    def test_candle_gap_rejected(self):
        b=rows(3);p=pair(b,3);b[1][0]+=1000
        with self.assertRaisesRegex(ValueError,"market_bar_gap"):
            inspect_one(b,p)

    def test_protocol_changed_fixed_bands_refused(self):
        data={
            "schema":"nexus.mr40.all47_early_mid_late_adverse_timing.protocol.v1",
            "source":{"frozen_4h_rows_digest":"a458d9f83df633df8ee5cab5f2a19de41c4c79c61185b5abd258fdefa80d575a",
                "authentic_ledger_gzip_sha256":"2c7115bac4ae81cc5c21b9bfc96319d5bee79baa746074c92c998125a834331e",
                "complete_47_position_risk_report_file_sha256":"c401f4920d8f51abe2ed77c11aa3a9616df8cde2d0dd958d7dfd0a59c6cac051",
                "complete_47_position_risk_report_logical_digest":"6ec8b21dc24ef1de962c4b439f870420493cecab570c53311eb836dbe7240ba9",
                "pairs":47},
            "fixed_diagnostic":{
                "bands_full_fourhour_bar_offset_from_entry":[
                    {"label":"EARLY_0_TO_24_HOURS","lower_inclusive_hour":0,"upper_exclusive_hour":24},
                    {"label":"MIDDLE_24_TO_120_HOURS","lower_inclusive_hour":24,"upper_exclusive_hour":120},
                    {"label":"LATE_FROM_120_HOURS","lower_inclusive_hour":120,"upper_exclusive_hour":None}],
                "price_adverse_thresholds_pct":[5,10,15]},
            "safety":{"orders":0,"auto_promote":False,"live":False},
        }
        validate_protocol(data)
        data["fixed_diagnostic"]["price_adverse_thresholds_pct"]=[5,9,15]
        with self.assertRaisesRegex(ValueError,"protocol_drift"):
            validate_protocol(data)

    def test_refuse_rewrite_prior_report(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)/"old.json";p.write_text("keep")
            with self.assertRaisesRegex(ValueError,"refuse_overwrite"):
                run(Path(t)/"invalid_lock.json",Path(t),Path(t)/"bad.gz",Path(t)/"old_risk.json",p)
            self.assertEqual(p.read_text(),"keep")

if __name__=="__main__":
    unittest.main()
