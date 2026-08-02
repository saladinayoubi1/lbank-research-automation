from __future__ import annotations

import sys
import types
import unittest

import pandas as pd


def _identity_retry(*args, **kwargs):
    def decorator(function):
        return function
    return decorator


tenacity_stub = types.ModuleType("tenacity")
tenacity_stub.retry = _identity_retry
tenacity_stub.retry_if_exception_type = lambda *args, **kwargs: None
tenacity_stub.stop_after_attempt = lambda *args, **kwargs: None
tenacity_stub.wait_exponential = lambda *args, **kwargs: None
sys.modules.setdefault("tenacity", tenacity_stub)

from main import analyze_timestamp_integrity


class AnalyzeTimestampIntegrityTests(unittest.TestCase):
    def test_detects_gap_and_missing_candles(self) -> None:
        timestamps = pd.Series(
            pd.to_datetime(
                [
                    "2026-01-01T00:00:00Z",
                    "2026-01-01T00:15:00Z",
                    "2026-01-01T00:45:00Z",
                ],
                utc=True,
            )
        )

        result = analyze_timestamp_integrity(timestamps, "minute15")

        self.assertEqual(result["expected_rows"], 4)
        self.assertEqual(result["gap_count"], 1)
        self.assertEqual(result["missing_candles"], 1)
        self.assertFalse(result["integrity_ok"])

    def test_detects_duplicate_timestamp(self) -> None:
        timestamps = pd.Series(
            pd.to_datetime(
                [
                    "2026-01-01T00:00:00Z",
                    "2026-01-01T00:15:00Z",
                    "2026-01-01T00:15:00Z",
                ],
                utc=True,
            )
        )

        result = analyze_timestamp_integrity(timestamps, "minute15")

        self.assertEqual(result["duplicate_count"], 1)
        self.assertFalse(result["integrity_ok"])

    def test_detects_off_grid_timestamp(self) -> None:
        timestamps = pd.Series(
            pd.to_datetime(
                [
                    "2026-01-01T00:00:00Z",
                    "2026-01-01T01:05:00Z",
                ],
                utc=True,
            )
        )

        result = analyze_timestamp_integrity(timestamps, "hour1")

        self.assertEqual(result["off_grid_count"], 1)
        self.assertFalse(result["integrity_ok"])


if __name__ == "__main__":
    unittest.main()

