"""Synthetic V18 future Bybit archive bridge / causal proof regression tests.

No public API calls, existing strategy execution, forward market sample,
broker order or mutation of the frozen historical archive.
"""
import unittest
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd

import nexus_elliott_forward_bridge_v18 as gate


def source(n=500):
    """Fictional closed bars covering the start of the preregistered window."""
    times=pd.date_range("2026-10-10T20:00:00Z",periods=n,freq="15min")
    index=np.arange(n,dtype=float)
    close=100+index*.007+np.sin(index/13)*1.5
    opening=close-.12
    return pd.DataFrame({
        "timestamp":times,"open":opening,
        "high":np.maximum(opening,close)+.7,
        "low":np.minimum(opening,close)-.8,
        "close":close,
        "volume":10+index%7,
    })


def close_time(f):
    return (f.timestamp.iloc[-1]+pd.Timedelta(minutes=15)).to_pydatetime()


class ResearchBridgeV18Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.candles=source(500)
        cls.clock=close_time(cls.candles)

    def test_review_is_research_only(self):
        self.assertTrue(gate.RESEARCH_ONLY)
        for flag in (gate.LIVE_ENABLED,gate.AUTO_DEMO,
                     gate.ENTRY_SIGNAL,gate.PAPER_ELIGIBLE,
                     gate.RECURSIVE_ELLIOTT_PROVEN):
            self.assertFalse(flag)

    def test_well_formed_15m_frame_is_accepted(self):
        clean=gate.validate_frame(self.candles)
        self.assertEqual(len(clean),500)
        self.assertEqual(clean.timestamp.iloc[0],self.candles.timestamp.iloc[0])

    def test_missing_august_to_october_bridge_is_rejected(self):
        f=self.candles
        with self.assertRaisesRegex(ValueError,"missing/overlapping"):
            gate.validated_bridge(f.iloc[:400],f.iloc[401:],self.clock)

    def test_overlapping_archive_end_is_rejected(self):
        f=self.candles
        with self.assertRaisesRegex(ValueError,"missing/overlapping"):
            gate.validated_bridge(f.iloc[:400],f.iloc[399:],self.clock)

    def test_contiguous_bridge_requires_completed_bars(self):
        f=self.candles
        result=gate.validated_bridge(f.iloc[:400],f.iloc[400:],self.clock)
        self.assertEqual(len(result),500)
        with self.assertRaisesRegex(ValueError,"future/forming"):
            gate.validated_bridge(f.iloc[:400],f.iloc[400:],
                                  self.clock-timedelta(minutes=15))

    def test_duplicate_15m_bar_rejected(self):
        f=self.candles.copy()
        f.loc[45,"timestamp"]=f.loc[44,"timestamp"]
        with self.assertRaisesRegex(ValueError,"gapped, duplicated"):
            gate.validate_frame(f)

    def test_out_of_order_bar_rejected(self):
        f=self.candles.copy()
        f.loc[90,"timestamp"],f.loc[91,"timestamp"]=f.loc[91,"timestamp"],f.loc[90,"timestamp"]
        with self.assertRaisesRegex(ValueError,"gapped, duplicated"):
            gate.validate_frame(f)

    def test_naive_clock_and_timestamps_rejected(self):
        f=self.candles.copy()
        f["timestamp"]=f.timestamp.dt.tz_localize(None)
        with self.assertRaisesRegex(ValueError,"timezone"):
            gate.validate_frame(f)
        with self.assertRaisesRegex(ValueError,"timezone-aware"):
            gate.inspect_latest_closed_decision(
                self.candles,symbol="BTCUSDT",
                observed_at_utc=self.clock.replace(tzinfo=None),
                continuation_sha256="a"*64,
            )

    def test_invalid_high_low_price_and_volume_rejected(self):
        for column, value in (
            ("high",1),("low",999),("volume",-1),("close",float("nan"))
        ):
            f=self.candles.copy()
            f.loc[45,column]=value
            with self.subTest(column=column),self.assertRaisesRegex(ValueError,"OHLCV"):
                gate.validate_frame(f)

    def test_missing_volume_is_not_silently_assumed(self):
        with self.assertRaisesRegex(ValueError,"OHLCV columns"):
            gate.validate_frame(self.candles.drop(columns="volume"))

    def test_unverified_external_provider_not_marked_authenticated(self):
        r=gate.inspect_latest_closed_decision(
            self.candles,symbol="BTCUSDT",observed_at_utc=self.clock,
            continuation_sha256="a"*64,
        )
        self.assertFalse(r["external_bybit_authenticity_verified"])
        self.assertFalse(r["live_enabled"])
        self.assertFalse(r["paper_eligible"])
        self.assertEqual(r["orders_placed"],0)
        self.assertNotEqual(r["status"],"LIVE_ORDER_READY")

    def test_stale_and_forming_decision_rejected(self):
        for shift in (-15,15):
            with self.subTest(shift=shift),self.assertRaisesRegex(
                ValueError,"stale or contains forming"
            ):
                gate.inspect_latest_closed_decision(
                    self.candles,symbol="ETHUSDT",
                    observed_at_utc=self.clock+timedelta(minutes=shift),
                    continuation_sha256="f"*64,
                )

    def test_frozen_future_cutoff_rejects_historical_decision(self):
        f=source(100)
        with self.assertRaisesRegex(ValueError,"outside preregistered"):
            gate.inspect_latest_closed_decision(
                f,symbol="BTCUSDT",observed_at_utc=close_time(f),
                continuation_sha256="a"*64,
            )

    def test_after_expiry_rejected(self):
        f=self.candles.copy()
        f["timestamp"]=f.timestamp+pd.Timedelta(days=31)
        with self.assertRaisesRegex(ValueError,"outside preregistered"):
            gate.inspect_latest_closed_decision(
                f,symbol="BTCUSDT",observed_at_utc=close_time(f),
                continuation_sha256="a"*64,
            )

    def test_bogus_manifest_hash_and_other_exchange_rejected(self):
        with self.assertRaisesRegex(ValueError,"SHA256"):
            gate.inspect_latest_closed_decision(
                self.candles,symbol="BTCUSDT",observed_at_utc=self.clock,
                continuation_sha256="not-a-hash")
        with self.assertRaisesRegex(ValueError,"pairs"):
            gate.inspect_latest_closed_decision(
                self.candles,symbol="LBank",observed_at_utc=self.clock,
                continuation_sha256="a"*64,
            )

    def test_incomplete_higher_timeframe_candles_excluded(self):
        h,q=gate.closed_higher_timeframes(self.candles)
        self.assertEqual(len(h),125)
        self.assertEqual(len(q),31)  # 500 bars from 20:00Z = 31 full 4h buckets
        self.assertTrue(
            (h.timestamp+pd.Timedelta(hours=1)<=pd.Timestamp(self.clock)).all())
        self.assertTrue(
            (q.timestamp+pd.Timedelta(hours=4)<=pd.Timestamp(self.clock)).all())

    def test_event_is_never_claimed_recursive_elliott(self):
        r=gate.inspect_latest_closed_decision(
            self.candles,symbol="ETHUSDT",observed_at_utc=self.clock,
            continuation_sha256="b"*64,
        )
        self.assertFalse(r["recursive_elliott_proven"])
        self.assertNotIn("broker_order",r)
        self.assertNotIn("net_pnl",r)


if __name__=="__main__":
    unittest.main()
