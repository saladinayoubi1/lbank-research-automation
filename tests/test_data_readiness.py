from pathlib import Path

import pandas as pd
import pytest

from data_readiness import (
    build_summary,
    evaluate_readiness,
    generate_readiness_report,
    normalize_bool,
)


def sample_frame() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "symbol": "btc_usdt",
                "timeframe": "hour1",
                "rows": 100,
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

    result = evaluate_readiness(frame)

    assert result["ready_for_research"].tolist() == [True, True]
    assert result["readiness_reason"].tolist() == ["ready", "ready"]


def test_integrity_failure_takes_priority_over_status():
    frame = sample_frame().iloc[[0]].copy()
    frame["integrity_ok"] = "False"
    frame["status"] = "current"

    result = evaluate_readiness(frame)

    assert result.iloc[0]["ready_for_research"] == False
    assert result.iloc[0]["readiness_reason"] == "integrity_failed"


def test_minimum_rows_can_block_otherwise_healthy_series():
    frame = sample_frame().iloc[[0]].copy()

    result = evaluate_readiness(frame, minimum_rows=101)

    assert result.iloc[0]["readiness_reason"] == "insufficient_rows"


def test_missing_required_columns_raise_clear_error():
    with pytest.raises(ValueError, match="missing required columns"):
        evaluate_readiness(pd.DataFrame({"symbol": ["btc_usdt"]}))


def test_generate_report_writes_csv_markdown_and_json(tmp_path: Path):
    status_path = tmp_path / "_backfill_status.csv"
    sample_frame().to_csv(status_path, index=False)

    summary = generate_readiness_report(status_path)

    assert summary == {
        "total_series": 2,
        "ready_series": 1,
        "blocked_series": 1,
        "all_ready": False,
        "reason_counts": {"ready": 1, "integrity_failed": 1},
    }
    assert (tmp_path / "_data_readiness.csv").exists()
    assert (tmp_path / "_data_readiness.md").exists()
    assert (tmp_path / "_data_readiness.json").exists()


def test_build_summary_handles_empty_input():
    frame = sample_frame().iloc[0:0].copy()
    frame["ready_for_research"] = pd.Series(dtype=bool)
    frame["readiness_reason"] = pd.Series(dtype=str)

    summary = build_summary(frame)

    assert summary["total_series"] == 0
    assert summary["all_ready"] is False
