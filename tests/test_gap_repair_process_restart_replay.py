from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import textwrap


ROOT = Path(__file__).resolve().parents[1]


CHILD = textwrap.dedent(
    r"""
    import json
    import os
    from pathlib import Path
    import sys
    import types

    import pandas as pd

    state_root = Path(sys.argv[1])

    fake_main = types.ModuleType("main")

    class LBankError(RuntimeError):
        pass

    fake_main.LBankError = LBankError
    fake_main.OUTPUT_ROOT = state_root
    fake_main.SYMBOLS = ["btc_usdt"]
    fake_main.TIMEFRAMES = ["minute15"]
    fake_main.TIMEFRAME_SECONDS = {
        "minute15": 900,
        "hour1": 3600,
        "hour4": 14400,
    }

    existing = pd.DataFrame(
        {
            "timestamp": pd.to_datetime(
                [
                    "2026-01-01T00:00:00Z",
                    "2026-01-01T00:30:00Z",
                    "2026-01-01T01:00:00Z",
                ]
            )
        }
    )

    requested = []

    def get_klines(symbol, timeframe, start):
        requested.append(pd.to_datetime(start, unit="s", utc=True).isoformat())
        return []

    fake_main.get_klines = get_klines
    fake_main.read_existing = lambda path: existing.copy()
    fake_main.rows_to_frame = lambda *args, **kwargs: pd.DataFrame(columns=["timestamp"])
    fake_main.save_merged = lambda current, incoming, path: len(current)
    fake_main.write_backfill_status = lambda: None
    sys.modules["main"] = fake_main

    import gap_repair
    from gap_repair_checkpoint import read_checkpoint

    gap_repair.MAX_GAP_WINDOWS_PER_SERIES_PER_RUN = 1
    repaired, failures, outcomes = gap_repair.repair_series_with_outcomes(
        "btc_usdt", "minute15"
    )

    gap_starts = gap_repair.find_gap_starts(existing["timestamp"], "minute15")
    checkpoint = read_checkpoint(
        state_root / "_gap_repair_checkpoints" / "btc_usdt" / "minute15.json",
        symbol="btc_usdt",
        timeframe="minute15",
        gap_starts=[value.isoformat() for value in gap_starts],
    )

    print(
        json.dumps(
            {
                "pid": os.getpid(),
                "requested": requested,
                "cursor": checkpoint.cursor,
                "statuses": [outcome.status for outcome in outcomes],
                "repaired": repaired,
                "failures": failures,
            },
            sort_keys=True,
        )
    )
    """
)


def _run_clean_process(state_root: Path) -> dict:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT)
    completed = subprocess.run(
        [sys.executable, "-c", CHILD, str(state_root)],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )
    return json.loads(completed.stdout.strip().splitlines()[-1])


def test_gap_repair_restart_resumes_from_same_durable_checkpoint(tmp_path: Path) -> None:
    """A genuinely fresh process must resume at the next bounded gap window."""
    state_root = tmp_path / "durable-gap-state"

    first = _run_clean_process(state_root)
    second = _run_clean_process(state_root)

    assert first["pid"] != second["pid"]
    assert first["repaired"] == second["repaired"] == 0
    assert first["failures"] == second["failures"] == 0

    assert first["requested"] == ["2026-01-01T00:15:00+00:00"]
    assert second["requested"] == ["2026-01-01T00:45:00+00:00"]

    assert first["cursor"] == 1
    assert second["cursor"] == 0

    assert first["statuses"] == ["source_unavailable", "deferred_budget"]
    assert second["statuses"] == ["source_unavailable", "deferred_budget"]
