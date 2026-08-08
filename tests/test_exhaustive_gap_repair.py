from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

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


@pytest.mark.parametrize("max_rounds", [1, 2, runner.MAX_ROUNDS])
def test_accepts_values_within_hard_round_bound(tmp_path, max_rounds):
    status = tmp_path / f"status-{max_rounds}.csv"
    write_status(status, ok=0, blocked=1, missing=5)
    calls = 0

    def repair():
        nonlocal calls
        calls += 1
        return 1

    result = runner.run_exhaustive_repair(
        max_rounds=max_rounds,
        status_path=status,
        repair_fn=repair,
        readiness_fn=lambda **_: {"all_ready": False},
    )

    assert result["rounds_run"] == max_rounds
    assert calls == max_rounds
    assert result["stopped_because"] == "round_limit"


@pytest.mark.parametrize(
    "max_rounds",
    [0, -1, runner.MAX_ROUNDS + 1, 10**9, True, 1.5, float("inf")],
)
def test_rejects_invalid_or_pathological_round_limit_before_side_effects(tmp_path, max_rounds):
    status = tmp_path / "status.csv"
    write_status(status, ok=0, blocked=1, missing=5)
    before = status.read_bytes()
    repair_calls = 0
    readiness_calls = 0

    def repair():
        nonlocal repair_calls
        repair_calls += 1
        return 1

    def readiness(**_):
        nonlocal readiness_calls
        readiness_calls += 1
        return {"all_ready": False}

    with pytest.raises(ValueError, match="max_rounds"):
        runner.run_exhaustive_repair(
            max_rounds=max_rounds,
            status_path=status,
            repair_fn=repair,
            readiness_fn=readiness,
        )

    assert repair_calls == 0
    assert readiness_calls == 0
    assert status.read_bytes() == before


def test_recovery_after_rejected_pathological_limit_is_deterministic(tmp_path):
    status = tmp_path / "status.csv"
    write_status(status, ok=0, blocked=1, missing=2)
    before = status.read_bytes()

    with pytest.raises(ValueError, match="max_rounds"):
        runner.run_exhaustive_repair(
            max_rounds=runner.MAX_ROUNDS + 1,
            status_path=status,
            repair_fn=lambda: 1,
            readiness_fn=lambda **_: {"all_ready": False},
        )

    assert status.read_bytes() == before
    recoveries = iter([2, 0])
    repair_calls = 0

    def repair():
        nonlocal repair_calls
        repair_calls += 1
        recovered = next(recoveries)
        if recovered:
            write_status(status, ok=1, blocked=0, missing=0)
        return recovered

    result = runner.run_exhaustive_repair(
        max_rounds=2,
        status_path=status,
        repair_fn=repair,
        readiness_fn=lambda **_: {"all_ready": True},
    )

    assert repair_calls == 2
    assert result["rounds_run"] == 2
    assert result["recovered_candles"] == 2
    assert result["stopped_because"] == "no_progress"
    assert result["after"]["blocked_series"] == 0
