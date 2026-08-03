from __future__ import annotations

import inventory_quality_audit as adapter


def inventory_report():
    return {
        "generated_at_utc": "2026-08-03T00:00:00+00:00",
        "summary": {
            "unique_missing_timestamps_observed_raw": 2,
            "unique_missing_timestamps_invalid": 1,
            "unique_missing_timestamps_valid": 1,
        },
        "rows": [
            {
                "symbol": "btc_usdt",
                "timeframe": "hour1",
                "timestamp_utc": "2026-01-01T00:15:00+00:00",
                "open": 10,
                "high": 9,
                "low": 8,
                "close": 10,
                "volume": 5,
                "validation_reasons": ["high_below_ohlc_max"],
                "canonical_valid": False,
            },
            {
                "symbol": "btc_usdt",
                "timeframe": "hour1",
                "timestamp_utc": "2026-01-01T00:30:00+00:00",
                "open": 10,
                "high": 11,
                "low": 9,
                "close": 10,
                "volume": 5,
                "validation_reasons": [],
                "canonical_valid": True,
            },
        ],
    }


def test_inventory_to_probe_report_excludes_valid_rows():
    converted = adapter.inventory_to_probe_report(inventory_report())

    assert converted["generated_at_utc"] == "2026-08-03T00:00:00+00:00"
    assert len(converted["results"]) == 1
    assert converted["results"][0]["missing_timestamp_utc"] == (
        "2026-01-01T00:15:00+00:00"
    )
    assert converted["results"][0]["classification"] == (
        "present_but_rejected_by_validation"
    )


def test_build_inventory_quality_audit_preserves_source_summary():
    result = adapter.build_inventory_quality_audit(inventory_report())

    assert result["source_type"] == "cached_gap_inventory"
    assert result["source_inventory_summary"][
        "unique_missing_timestamps_observed_raw"
    ] == 2
    assert result["summary"]["unique_invalid_rows"] == 1
    assert result["summary"]["reason_counts"] == {
        "high_below_ohlc_max": 1
    }
