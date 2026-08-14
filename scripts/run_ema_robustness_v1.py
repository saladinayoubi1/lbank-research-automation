from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pandas as pd

from ema_robustness_v1 import run_ema_robustness
from research_data import load_research_series

ROOT = Path(__file__).resolve().parents[1]
STATUS = ROOT / "data" / "market" / "_backfill_status.csv"
OUTPUT = ROOT / "build" / "research" / "ema_robustness_v1.json"


def current_head() -> str:
    result = subprocess.run(
        ["git", "-c", f"safe.directory={ROOT}", "rev-parse", "HEAD"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def select_research_series(status: pd.DataFrame, limit: int = 2) -> list[tuple[str, str]]:
    required = {"symbol", "timeframe", "integrity_ok", "status", "rows"}
    missing = sorted(required - set(status.columns))
    if missing:
        raise RuntimeError(f"readiness status missing columns: {missing}")

    candidates = status.loc[
        (status["timeframe"] == "hour4")
        & (status["integrity_ok"].astype(str).str.lower() == "true")
        & (status["status"] == "current")
        & (pd.to_numeric(status["rows"], errors="coerce") >= 500)
    ].copy()
    candidates = candidates.sort_values(["rows", "symbol"], ascending=[False, True])
    return [
        (str(row.symbol), str(row.timeframe))
        for row in candidates.head(limit).itertuples(index=False)
    ]


def main() -> None:
    status = pd.read_csv(STATUS)
    selected = select_research_series(status)
    if not selected:
        raise RuntimeError("no research-ready hour4 series are available")

    evidence: list[dict[str, object]] = []
    for symbol, timeframe in selected:
        frame = load_research_series(
            symbol,
            timeframe,
            data_root=ROOT / "data" / "market",
            minimum_rows=500,
        )
        result = run_ema_robustness(frame)
        evidence.append(
            {
                "symbol": symbol,
                "timeframe": timeframe,
                "rows": len(frame),
                "first_candle_utc": frame.iloc[0]["timestamp"].isoformat(),
                "last_candle_utc": frame.iloc[-1]["timestamp"].isoformat(),
                "result": result,
            }
        )

    payload = {
        "schema_version": 1,
        "repository_head": current_head(),
        "selected_series": [f"{symbol}:{timeframe}" for symbol, timeframe in selected],
        "evidence": evidence,
        "authority": "research-backtest-paper-only",
        "automatic_promotion_allowed": False,
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(payload, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "ok": True,
        "repository_head": payload["repository_head"],
        "selected_series": payload["selected_series"],
        "output": str(OUTPUT.relative_to(ROOT)).replace("\\", "/"),
    }, sort_keys=True))


if __name__ == "__main__":
    main()
