from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pandas as pd

DEFAULT_STATUS_PATH = Path("data/market/_backfill_status.csv")
RESEARCH_READY_STATUSES = {"current", "backfilling"}
REQUIRED_COLUMNS = {
    "symbol",
    "timeframe",
    "rows",
    "status",
    "integrity_ok",
    "missing_candles",
    "gap_count",
    "duplicate_count",
    "off_grid_count",
}


def normalize_bool(value: Any) -> bool:
    """Convert common CSV boolean values to a strict boolean."""
    if isinstance(value, bool):
        return value
    if pd.isna(value):
        return False
    normalized = str(value).strip().lower()
    if normalized in {"true", "1", "yes"}:
        return True
    if normalized in {"false", "0", "no", ""}:
        return False
    raise ValueError(f"Unsupported boolean value: {value!r}")


def evaluate_readiness(
    status_frame: pd.DataFrame,
    minimum_rows: int = 0,
) -> pd.DataFrame:
    """Add deterministic research-readiness fields to a status report."""
    missing_columns = REQUIRED_COLUMNS.difference(status_frame.columns)
    if missing_columns:
        joined = ", ".join(sorted(missing_columns))
        raise ValueError(f"Status report is missing required columns: {joined}")
    if minimum_rows < 0:
        raise ValueError("minimum_rows must be non-negative")

    result = status_frame.copy()
    result["rows"] = pd.to_numeric(result["rows"], errors="coerce").fillna(0).astype(int)
    result["integrity_ok"] = result["integrity_ok"].map(normalize_bool)
    result["status"] = result["status"].astype(str).str.strip().str.lower()

    reasons: list[str] = []
    ready_flags: list[bool] = []

    for row in result.to_dict("records"):
        if not row["integrity_ok"]:
            reason = "integrity_failed"
        elif row["status"] not in RESEARCH_READY_STATUSES:
            reason = f"status_{row['status'] or 'unknown'}"
        elif int(row["rows"]) < minimum_rows:
            reason = "insufficient_rows"
        else:
            reason = "ready"

        reasons.append(reason)
        ready_flags.append(reason == "ready")

    result["ready_for_research"] = ready_flags
    result["readiness_reason"] = reasons
    return result


def build_summary(readiness_frame: pd.DataFrame) -> dict[str, Any]:
    total = int(len(readiness_frame))
    ready = int(readiness_frame["ready_for_research"].sum())
    reason_counts = {
        str(reason): int(count)
        for reason, count in readiness_frame["readiness_reason"].value_counts().items()
    }
    return {
        "total_series": total,
        "ready_series": ready,
        "blocked_series": total - ready,
        "all_ready": total > 0 and ready == total,
        "reason_counts": reason_counts,
    }


def write_reports(
    readiness_frame: pd.DataFrame,
    output_root: Path,
) -> dict[str, Any]:
    output_root.mkdir(parents=True, exist_ok=True)
    summary = build_summary(readiness_frame)

    csv_path = output_root / "_data_readiness.csv"
    md_path = output_root / "_data_readiness.md"
    json_path = output_root / "_data_readiness.json"

    readiness_frame.to_csv(csv_path, index=False)

    lines = [
        "# LBank Data Readiness",
        "",
        f"- Total series: {summary['total_series']}",
        f"- Ready for research: {summary['ready_series']}",
        f"- Blocked: {summary['blocked_series']}",
        f"- All ready: {summary['all_ready']}",
        "",
        "| Symbol | Timeframe | Rows | Status | Integrity OK | Missing | Gaps | Duplicates | Off-grid | Ready | Reason |",
        "|---|---|---:|---|---|---:|---:|---:|---:|---|---|",
    ]
    for row in readiness_frame.sort_values(["symbol", "timeframe"]).to_dict("records"):
        lines.append(
            "| {symbol} | {timeframe} | {rows} | {status} | {integrity_ok} | "
            "{missing_candles} | {gap_count} | {duplicate_count} | "
            "{off_grid_count} | {ready_for_research} | {readiness_reason} |".format(**row)
        )
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    payload = {
        "summary": summary,
        "ready_series": readiness_frame.loc[
            readiness_frame["ready_for_research"], ["symbol", "timeframe"]
        ].to_dict("records"),
        "blocked_series": readiness_frame.loc[
            ~readiness_frame["ready_for_research"],
            ["symbol", "timeframe", "readiness_reason"],
        ].to_dict("records"),
    }
    json_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return summary


def generate_readiness_report(
    status_path: Path = DEFAULT_STATUS_PATH,
    minimum_rows: int = 0,
) -> dict[str, Any]:
    if not status_path.exists():
        raise FileNotFoundError(f"Status report not found: {status_path}")

    status_frame = pd.read_csv(status_path)
    readiness_frame = evaluate_readiness(status_frame, minimum_rows=minimum_rows)
    return write_reports(readiness_frame, status_path.parent)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate deterministic research-readiness reports from integrity status."
    )
    parser.add_argument(
        "--status-path",
        type=Path,
        default=DEFAULT_STATUS_PATH,
    )
    parser.add_argument(
        "--minimum-rows",
        type=int,
        default=0,
        help="Optional minimum row count required for a series to be research-ready.",
    )
    parser.add_argument(
        "--require-all-ready",
        action="store_true",
        help="Exit non-zero when any series is blocked.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    summary = generate_readiness_report(
        status_path=args.status_path,
        minimum_rows=args.minimum_rows,
    )
    print(json.dumps(summary, sort_keys=True))
    if args.require_all_ready and not summary["all_ready"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
