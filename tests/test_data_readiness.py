import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pytest

from data_readiness import (
    FRESHNESS_POLICY_DIGEST,
    FRESHNESS_POLICY_VERSION,
    _validate_freshness_policy,
    build_summary,
    evaluate_readiness,
    generate_readiness_report,
    normalize_bool,
)


AS_OF = datetime(2026, 8, 6, 13, 30, tzinfo=timezone.utc)


def sample_frame() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "symbol": "btc_usdt",
                "timeframe": "hour1",
                "rows": 100,
                "last_candle_utc": "2026-08-06T13:00:00+00:00",
                "status": "current",
                "integrity_ok": True,
                "missing_candles": 0,
                "gap_count": 0,
                "duplicate_count": 0,
                "off_grid_count": 0,
            },
            {
                "symbol": "eth_usdt",
                "timeframe": "hour1",
                "rows": 90,
                "last_candle_utc": "2026-08-06T13:00:00+00:00",
                "status": "invalid",
                "integrity_ok": False,
                "missing_candles": 2,
                "gap_count": 2,
                "duplicate_count": 0,
                "off_grid_count": 0,
            },
        ]
    )


@pytest.mark.parametrize(
    ("value", "expected"),
    [(True, True), (False, False), ("True", True), ("false", False), (1, True), (0, False)],
)
def test_normalize_bool(value, expected):
    assert normalize_bool(value) is expected


def test_evaluate_readiness_accepts_current_and_healthy_backfilling():
    frame = sample_frame()
    backfilling = frame.iloc[[0]].copy()
    backfilling["status"] = "backfilling"
    frame = pd.concat([frame.iloc[[0]], backfilling], ignore_index=True)

    result = evaluate_readiness(frame, as_of_utc=AS_OF)

    assert result["ready_for_research"].tolist() == [True, True]
    assert result["readiness_reason"].tolist() == ["ready", "ready"]
    assert result["freshness_ok"].tolist() == [True, True]
    assert result["freshness_policy_version"].unique().tolist() == [FRESHNESS_POLICY_VERSION]
    assert result["freshness_policy_digest"].unique().tolist() == [FRESHNESS_POLICY_DIGEST]
    assert result["evaluated_at_utc"].unique().tolist() == ["2026-08-06T13:30:00+00:00"]


def test_integrity_failure_takes_priority_over_status():
    frame = sample_frame().iloc[[0]].copy()
    frame["integrity_ok"] = "False"
    frame["status"] = "current"

    result = evaluate_readiness(frame, as_of_utc=AS_OF)

    assert result.iloc[0]["ready_for_research"] == False
    assert result.iloc[0]["readiness_reason"] == "integrity_failed"


def test_stale_series_is_fail_closed_even_when_integrity_and_status_are_green():
    frame = sample_frame().iloc[[0]].copy()
    frame["last_candle_utc"] = "2026-08-06T08:00:00+00:00"

    result = evaluate_readiness(frame, as_of_utc=AS_OF)

    assert result.iloc[0]["integrity_ok"] == True
    assert result.iloc[0]["status"] == "current"
    assert result.iloc[0]["freshness_ok"] == False
    assert result.iloc[0]["ready_for_research"] == False
    assert result.iloc[0]["readiness_reason"] == "stale_data"


def test_unknown_timeframe_is_fail_closed():
    frame = sample_frame().iloc[[0]].copy()
    frame["timeframe"] = "minute5"

    result = evaluate_readiness(frame, as_of_utc=AS_OF)

    assert result.iloc[0]["ready_for_research"] == False
    assert result.iloc[0]["readiness_reason"] == "freshness_policy_missing"


def test_invalid_last_candle_is_fail_closed():
    frame = sample_frame().iloc[[0]].copy()
    frame["last_candle_utc"] = "not-a-timestamp"

    result = evaluate_readiness(frame, as_of_utc=AS_OF)

    assert result.iloc[0]["ready_for_research"] == False
    assert result.iloc[0]["readiness_reason"] == "last_candle_invalid"


def test_minimum_rows_can_block_otherwise_healthy_series():
    frame = sample_frame().iloc[[0]].copy()

    result = evaluate_readiness(frame, minimum_rows=101, as_of_utc=AS_OF)

    assert result.iloc[0]["readiness_reason"] == "insufficient_rows"


def test_missing_required_columns_raise_clear_error():
    with pytest.raises(ValueError, match="missing required columns"):
        evaluate_readiness(pd.DataFrame({"symbol": ["btc_usdt"]}), as_of_utc=AS_OF)


@pytest.mark.parametrize(
    "override",
    [
        {"minute15": float("inf")},
        {"hour1": float("nan")},
        {"hour4": 999999.0},
        {"minute15": 0.5, "hour1": 3.0, "hour4": 8.0},
    ],
)
def test_runtime_freshness_policy_override_is_fail_closed(override):
    with pytest.raises(ValueError, match="runtime freshness policy overrides are not allowed"):
        evaluate_readiness(
            sample_frame().iloc[[0]].copy(),
            as_of_utc=AS_OF,
            freshness_limits_hours=override,
        )


@pytest.mark.parametrize("bad_value", [float("inf"), float("-inf"), float("nan"), 0, -1, True, "bad"])
def test_policy_validator_rejects_nonfinite_or_invalid_limits(bad_value):
    policy = {"minute15": 1.0, "hour1": 3.0, "hour4": 8.0}
    policy["hour1"] = bad_value
    with pytest.raises(ValueError, match="freshness limit"):
        _validate_freshness_policy(policy)


def test_policy_validator_rejects_widening_and_unknown_keys():
    with pytest.raises(ValueError, match="within"):
        _validate_freshness_policy({"minute15": 1.0, "hour1": 3.1, "hour4": 8.0})
    with pytest.raises(ValueError, match="registered timeframes"):
        _validate_freshness_policy(
            {"minute15": 1.0, "hour1": 3.0, "hour4": 8.0, "day1": 48.0}
        )


def test_generate_report_writes_csv_markdown_and_json(tmp_path: Path):
    status_path = tmp_path / "_backfill_status.csv"
    sample_frame().to_csv(status_path, index=False)

    summary = generate_readiness_report(status_path, as_of_utc=AS_OF)

    assert summary == {
        "total_series": 2,
        "ready_series": 1,
        "blocked_series": 1,
        "all_ready": False,
        "reason_counts": {"ready": 1, "integrity_failed": 1},
    }
    readiness = pd.read_csv(tmp_path / "_data_readiness.csv")
    assert {
        "freshness_hours",
        "freshness_limit_hours",
        "freshness_ok",
        "freshness_policy_version",
        "freshness_policy_digest",
        "evaluated_at_utc",
    }.issubset(readiness.columns)
    assert readiness["freshness_policy_version"].unique().tolist() == [FRESHNESS_POLICY_VERSION]
    assert readiness["freshness_policy_digest"].unique().tolist() == [FRESHNESS_POLICY_DIGEST]

    payload = json.loads((tmp_path / "_data_readiness.json").read_text(encoding="utf-8"))
    assert payload["evaluated_at_utc"] == "2026-08-06T13:30:00+00:00"
    assert payload["freshness_policy"] == {
        "version": FRESHNESS_POLICY_VERSION,
        "digest": FRESHNESS_POLICY_DIGEST,
    }
    assert (tmp_path / "_data_readiness.md").exists()


def test_build_summary_handles_empty_input():
    frame = sample_frame().iloc[0:0].copy()
    frame["ready_for_research"] = pd.Series(dtype=bool)
    frame["readiness_reason"] = pd.Series(dtype=str)

    summary = build_summary(frame)

    assert summary["total_series"] == 0
    assert summary["all_ready"] is False
