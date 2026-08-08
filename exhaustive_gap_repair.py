from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Callable, Any

import pandas as pd

import gap_repair
from data_readiness import generate_readiness_report

DEFAULT_STATUS_PATH = Path("data/market/_backfill_status.csv")
MAX_ROUNDS = 20
DEFAULT_MAX_ROUNDS = MAX_ROUNDS


def _status_snapshot(status_path: Path) -> dict[str, Any]:
    if not status_path.exists():
        return {
            "total_series": 0,
            "integrity_ok_series": 0,
            "blocked_series": 0,
            "missing_candles": 0,
        }
    frame = pd.read_csv(status_path)
    if frame.empty:
        return {
            "total_series": 0,
            "integrity_ok_series": 0,
            "blocked_series": 0,
            "missing_candles": 0,
        }
    integrity = frame.get("integrity_ok", pd.Series(False, index=frame.index))
    integrity = integrity.astype(str).str.strip().str.lower().isin({"true", "1", "yes"})
    missing = pd.to_numeric(frame.get("missing_candles", 0), errors="coerce").fillna(0)
    total = int(len(frame))
    ok = int(integrity.sum())
    return {
        "total_series": total,
        "integrity_ok_series": ok,
        "blocked_series": total - ok,
        "missing_candles": int(missing.sum()),
    }


def run_exhaustive_repair(
    *,
    max_rounds: int = DEFAULT_MAX_ROUNDS,
    status_path: Path = DEFAULT_STATUS_PATH,
    repair_fn: Callable[[], int] = gap_repair.repair_all,
    readiness_fn: Callable[..., dict[str, Any]] = generate_readiness_report,
) -> dict[str, Any]:
    if isinstance(max_rounds, bool) or not isinstance(max_rounds, int):
        raise ValueError("max_rounds must be an integer")
    if not 1 <= max_rounds <= MAX_ROUNDS:
        raise ValueError(f"max_rounds must be between 1 and {MAX_ROUNDS}")

    before = _status_snapshot(status_path)
    rounds: list[dict[str, Any]] = []
    recovered_total = 0

    for round_number in range(1, max_rounds + 1):
        recovered = int(repair_fn())
        recovered_total += recovered
        snapshot = _status_snapshot(status_path)
        rounds.append({
            "round": round_number,
            "recovered_candles": recovered,
            **snapshot,
        })
        if recovered == 0:
            break

    readiness = readiness_fn(status_path=status_path)
    after = _status_snapshot(status_path)
    return {
        "before": before,
        "after": after,
        "rounds_run": len(rounds),
        "recovered_candles": recovered_total,
        "stopped_because": "no_progress" if rounds and rounds[-1]["recovered_candles"] == 0 else "round_limit",
        "readiness": readiness,
        "rounds": rounds,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Repeat bounded LBank gap repair until no further candles are recovered."
    )
    parser.add_argument("--max-rounds", type=int, default=DEFAULT_MAX_ROUNDS)
    parser.add_argument("--status-path", type=Path, default=DEFAULT_STATUS_PATH)
    args = parser.parse_args()
    result = run_exhaustive_repair(max_rounds=args.max_rounds, status_path=args.status_path)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
