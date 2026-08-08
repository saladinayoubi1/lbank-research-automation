from __future__ import annotations

from pathlib import Path

import pandas as pd

import exhaustive_gap_repair as runner


def write_status(path: Path, *, ok: int, blocked: int, missing: int) -> None:
    rows = []
    for index in range(ok):
        rows.append({"symbol": f"ok{index}", "timeframe": "hour1", "integrity_ok": True, "missing_candles": 0})
    for index in range(blocked):
        rows.append({"symbol": f"bad{index}", "timeframe": "hour1", "integrity_ok": False, "missing_candles": missing if index == 0 else 0})
    pd.DataFrame(rows).to_csv(path, index=False)


def test_repeats_until_no_progress(tmp_path):
    status = tmp_path / "status.csv"
    write_status(status, ok=1, blocked=1, missing=3)
    recoveries = iter([2, 1, 0])

    def repair():
        value = next(recoveries)
        if value == 1:
            write_status(status, ok=2, blocked=0, missing=0)
        return value

    result = runner.run_exhaustive_repair(
        max_rounds=10,
        status_path=status,
        repair_fn=repair,
        readiness_fn=lambda **_: {"all_ready": True},
    )

    assert result["rounds_run"] == 3
    assert result["recovered_candles"] == 3
    assert result["stopped_because"] == "no_progress"
    assert result["after"]["blocked_series"] == 0


def test_stops_at_round_limit(tmp_path):
    status = tmp_path / "status.csv"
    write_status(status, ok=0, blocked=1, missing=5)

    result = runner.run_exhaustive_repair(
        max_rounds=2,
        status_path=status,
        repair_fn=lambda: 1,
        readiness_fn=lambda **_: {"all_ready": False},
    )

    assert result["rounds_run"] == 2
    assert result["recovered_candles"] == 2
    assert result["stopped_because"] == "round_limit"
    assert result["after"]["blocked_series"] == 1


def test_rejects_invalid_round_limit(tmp_path):
    status = tmp_path / "status.csv"
    try:
        runner.run_exhaustive_repair(
            max_rounds=0,
            status_path=status,
            repair_fn=lambda: 0,
            readiness_fn=lambda **_: {},
        )
    except ValueError as exc:
        assert "max_rounds" in str(exc)
    else:
        raise AssertionError("expected ValueError")
