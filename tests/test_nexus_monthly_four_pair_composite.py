"""Synthetic-only regression: full-month four-pair causal Research is never Demo."""
from __future__ import annotations

import pandas as pd
import pytest
import nexus_monthly_four_pair_pre_demo as month
import nexus_monthly_four_pair_composite as target
from nexus_multipair_trusted_surface import SYMBOLS, TIMEFRAMES

SHA = "e" * 40


def fixture_frames():
    frames = {}
    for tf, freq in (("minute15", "15min"), ("hour1", "1h"), ("hour4", "4h")):
        ts = pd.date_range(month.START_DATE, periods=month.EXPECTED_ROWS[tf], freq=freq, tz="UTC")
        for i, symbol in enumerate(SYMBOLS):
            price = pd.Series([100 + 10 * i + n * .005 + (n % 27) * .025 for n in range(len(ts))])
            frames[symbol, tf] = pd.DataFrame({"timestamp": ts, "open": price, "high": price + 1,
                "low": price - 1, "close": price + .1, "volume": 1.0,
                "symbol": symbol.replace("USDT", "/USDT"), "timeframe": tf})
    return frames


def test_all_five_causal_mechanisms_four_pairs_two_costs_three_folds():
    frames = fixture_frames()
    hashes = {key: target._frame_digest(f) for key, f in frames.items()}
    baseline = {"origin": "official_public_bybit_spot_trade_archive_aggregated",
        "verified_three_month_source_manifest_sha256": "7" * 64, "source_manifest_sha256": "8" * 64,
        "result_sha256": "9" * 64}
    report = target.calculate(frames, baseline, hashes, source_sha=SHA)
    assert report["total_rows"] == 240
    assert report["distinct_causal_mechanisms"] == 5
    assert {x["symbol"] for x in report["rows"]} == set(SYMBOLS)
    assert all(x["trade_count_limit"] is None and x["demo_promoted"] is False and x["live_enabled"] is False for x in report["rows"])
    assert report["historical_final_partition_pristine"] is False
    assert report["independent_numeric_QA_complete"] is False
    assert report["report_digest"] == target.composite.digest({k:v for k,v in report.items() if k != "report_digest"})
    frames["SOLUSDT", "minute15"] = frames["SOLUSDT", "minute15"].iloc[:-1]
    with pytest.raises(target.FourPairCompositeResearchError):
        target.calculate(frames, baseline, hashes, source_sha=SHA)
