from __future__ import annotations

import json

import pandas as pd
import pytest

import candle_quality_audit as audit


def raw_row(
    *,
    timestamp="2026-01-01T00:00:00+00:00",
    open_price=100,
    high=101,
    low=99,
    close=100,
    volume=10,
    reasons=None,
):
    return {
        "timestamp_utc": timestamp,
        "open": open_price,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
        "validation_reasons": reasons or [],
    }


def probe_report(rows_by_observation):
    return {
        "generated_at_utc": "2026-08-03T00:00:00+00:00",
        "summary": {"sampled_missing_timestamps": 1},
        "results": [{
            "symbol": "btc_usdt",
            "timeframe": "hour1",
            "missing_timestamp_utc": "2026-01-01T00:00:00+00:00",
            "classification": "present_but_rejected_by_validation",
            "observations": [
                {"exact_raw_rows": rows}
                for rows in rows_by_observation
            ],
        }],
    }


def test_severity_bucket_boundaries():
    assert audit.severity_bucket(0) == "none"
    assert audit.severity_bucket(1) == "rounding_le_1_bps"
    assert audit.severity_bucket(1.0001) == "minor_le_5_bps"
    assert audit.severity_bucket(5) == "minor_le_5_bps"
    assert audit.severity_bucket(10) == "moderate_le_10_bps"
    assert audit.severity_bucket(10.0001) == "material_gt_10_bps"


def test_severity_bucket_rejects_invalid_values():
    with pytest.raises(ValueError):
        audit.severity_bucket(-1)
    with pytest.raises(ValueError):
        audit.severity_bucket(float("nan"))


def test_analyze_high_shortfall_in_basis_points():
    result = audit.analyze_ohlcv_row(raw_row(
        open_price=100,
        high=99.99,
        low=90,
        close=95,
        reasons=["high_below_ohlc_max"],
    ))
    assert result["high_shortfall"] == pytest.approx(0.01)
    assert result["high_shortfall_bps"] == pytest.approx(1.0)
    assert result["severity"] == "rounding_le_1_bps"
    assert result["computed_reasons"] == ["high_below_ohlc_max"]


def test_analyze_low_excess_and_negative_volume():
    result = audit.analyze_ohlcv_row(raw_row(
        open_price=100,
        high=110,
        low=100.2,
        close=105,
        volume=-2,
    ))
    assert result["low_excess"] == pytest.approx(0.2)
    assert result["negative_volume_magnitude"] == 2
    assert result["computed_reasons"] == [
        "low_above_ohlc_min",
        "negative_volume",
    ]


def test_unique_probe_rows_deduplicates_three_anchor_copies():
    row = raw_row(
        open_price=100,
        high=99,
        low=90,
        close=95,
        reasons=["high_below_ohlc_max"],
    )
    rows = audit.unique_probe_rows(probe_report([[row], [row], [row]]))
    assert len(rows) == 1
    assert rows[0]["reason_match"] is True


def test_unique_probe_rows_detects_reason_mismatch():
    row = raw_row(
        open_price=100,
        high=99,
        low=90,
        close=95,
        reasons=["low_above_ohlc_min"],
    )
    rows = audit.unique_probe_rows(probe_report([[row]]))
    assert rows[0]["reason_match"] is False


def test_build_quality_audit_summarizes_unique_rows():
    row_one = raw_row(
        open_price=100,
        high=99.99,
        low=90,
        close=95,
        reasons=["high_below_ohlc_max"],
    )
    row_two = raw_row(
        timestamp="2026-01-01T01:00:00+00:00",
        open_price=10,
        high=20,
        low=12,
        close=15,
        reasons=["low_above_ohlc_min"],
    )
    report = probe_report([[row_one, row_two], [row_one]])
    result = audit.build_quality_audit(report)

    assert result["summary"]["unique_invalid_rows"] == 2
    assert result["summary"]["reason_counts"] == {
        "high_below_ohlc_max": 1,
        "low_above_ohlc_min": 1,
    }
    assert result["summary"]["at_or_below_1_bps"] == 1
    assert result["summary"]["above_10_bps"] == 1
    assert result["summary"]["reason_mismatch_rows"] == 0


def test_write_quality_audit_creates_three_outputs(tmp_path):
    row = raw_row(
        open_price=100,
        high=99,
        low=90,
        close=95,
        reasons=["high_below_ohlc_max"],
    )
    result = audit.build_quality_audit(probe_report([[row]]))
    audit.write_quality_audit(result, tmp_path)

    loaded = json.loads(
        (tmp_path / "_candle_quality_audit.json").read_text()
    )
    assert loaded["summary"]["unique_invalid_rows"] == 1
    assert "material_gt_10_bps" in (
        tmp_path / "_candle_quality_audit.md"
    ).read_text()
    csv = pd.read_csv(tmp_path / "_candle_quality_audit.csv")
    assert csv.loc[0, "symbol"] == "btc_usdt"
