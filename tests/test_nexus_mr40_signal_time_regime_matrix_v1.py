"""Portable causal-feature tests, plus on-research-laptop frozen evidence checks."""
import copy
from decimal import Decimal as D
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from research import nexus_mr40_signal_time_regime_matrix_v1 as m


def synthetic():
    # 185 contiguous completed 4h candles with exact known True Range of 2.
    return [[i*m.STEP, "100", "101", "99", "100", "10"] for i in range(185)]


class PortableRegimeTests(unittest.TestCase):
    def test_constant_price_atr_and_ohlc_shape(self):
        v=m.signal_features(synthetic(),180)
        self.assertEqual(v["ATR14_pct"],"2.00000000")
        self.assertEqual(v["signal_4h_range_pct"],"2.00000000")
        self.assertEqual(v["signal_close_location_in_range"],"0.50000000")
        self.assertEqual(v["return_10_closed_bars_pct"],"0E-8")
        self.assertIsNone(v["MR40_zscore"])

    def test_future_candle_cannot_affect_signal_features(self):
        rows=synthetic()
        a=m.signal_features(rows[:181],180)
        rows[181]=[181*m.STEP,"10000","10101","9900","10001","123456"]
        rows[184]=[184*m.STEP,"9000","9100","8900","9100","123456"]
        self.assertEqual(a,m.signal_features(rows,180))

    def test_signal_candle_is_known_after_close(self):
        rows=synthetic()
        rows[180]=[180*m.STEP,"90","101","89","92","10"]
        f=m.signal_features(rows,180)
        self.assertLess(D(f["return_10_closed_bars_pct"]),0)
        self.assertLess(D(f["signal_close_location_in_range"]),D("0.5"))

    def test_must_have_180_previous_closed_bars(self):
        with self.assertRaisesRegex(ValueError,"insufficient_closed_signal_history"):
            m.signal_features(synthetic(),179)

    def test_missing_4h_continuity_fails(self):
        rows=synthetic()
        rows[170][0]+=m.STEP
        with self.assertRaisesRegex(ValueError,"signal_history_utc_discontinuity"):
            m.signal_features(rows,180)

    def test_bad_signal_ohlcv_fails(self):
        rows=synthetic()
        rows[180][2]="95"
        with self.assertRaisesRegex(ValueError,"invalid_signal_ohlcv"):
            m.signal_features(rows,180)

    def test_bad_atr_component_fails(self):
        rows=synthetic()
        rows[179][3]="110"
        with self.assertRaisesRegex(ValueError,"invalid_ATR_history_ohlcv"):
            m.signal_features(rows,180)

    def test_null_close_location_on_flat_bar(self):
        rows=synthetic()
        rows[180]=[180*m.STEP,"100","100","100","100","10"]
        self.assertIsNone(m.signal_features(rows,180)["signal_close_location_in_range"])

    def test_digest_is_canonical(self):
        from research.nexus_mr40_independent_closed_signal_v1 import canon
        self.assertEqual(canon({"z":1,"a":2}),canon({"a":2,"z":1}))


class LockedResearchEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root=Path(__file__).resolve().parents[1]
        cls.original=Path("E:/NEXUS-Research/MR40-Staged-Entry-20261022/source/inputs")
        required=[
            cls.root/"research"/m.PROTOCOL,
            cls.root/"results"/m.CROSS,
            cls.root/"results"/m.OUTPUT,
            cls.original/"bybit_prepared_inputs.json",
            cls.original/"bybit_october_input_extension.json"
        ]
        if not all(x.exists() for x in required):
            raise unittest.SkipTest("locked 47 research source files not present in CI")

    def test_real_47_features_independent(self):
        v=m.audit(self.root,self.original)
        self.assertEqual(len(v["per_position"]),47)
        self.assertEqual(v["summary"]["train"]["winners"],19)
        self.assertEqual(v["summary"]["evaluation"]["losers"],4)
        self.assertEqual(v["decision"],"ENTRY_CAUSE_DESCRIPTIVE_ONLY_NO_PROMOTE")
        self.assertEqual(v["digest"],"791b3edce8fc1959a35302fad0cca0e197315729107e7467cf49c0db53913550")

    def test_real_market_and_join_pinned(self):
        rows,cross,ph=m.load_locked(self.root,self.original)
        self.assertEqual(len(rows),8514)
        self.assertEqual(len(cross["entries"]),47)
        self.assertEqual(m.file_sha(self.root/"results"/m.CROSS),m.CROSS_SHA)

    def test_existing_full_report_must_not_be_overwritten(self):
        result=self.root/"results"/m.OUTPUT
        orig_hash=m.file_sha(result)
        with patch("sys.argv",["test","--root",str(self.root),"--original-dir",str(self.original)]):
            with self.assertRaises(FileExistsError):
                m.main()
        self.assertEqual(m.file_sha(result),orig_hash)


if __name__=="__main__":
    unittest.main()
