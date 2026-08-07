from __future__ import annotations

import argparse
import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

import pandas as pd

DEFAULT_STATUS_PATH = Path("data/market/_backfill_status.csv")
RESEARCH_READY_STATUSES = {"current", "backfilling"}
FRESHNESS_POLICY_VERSION = "1.0.0"
_MAX_APPROVED_FRESHNESS_HOURS = MappingProxyType(
    {
        "minute15": 1.0,
        "hour1": 3.0,
        "hour4": 8.0,
    }
)
DEFAULT_FRESHNESS_LIMIT_HOURS = MappingProxyType(
    {
        "minute15": 1.0,
        "hour1": 3.0,
        "hour4": 8.0,
    }
)
REQUIRED_COLUMNS = {
    "symbol",
    "timeframe",
    "rows",
    "last_candle_utc",
    "status",
    "integrity_ok",
    "missing_candles",
    "gap_count",
    "duplicate_count",
    "off_grid_count",
}


def _validate_freshness_policy(policy: Mapping[str, Any]) -> dict[str, float]:
    expected_keys = set(_MAX_APPROVED_FRESHNESS_HOURS)
    actual_keys = set(policy)
    if actual_keys != expected_keys:
        missing = sorted(expected_keys - actual_keys)
        unknown = sorted(actual_keys - expected_keys)
        raise ValueError(
            f"freshness policy keys must match registered timeframes; missing={missing}, unknown={unknown}"
        )

    validated: dict[str, float] = {}
    for timeframe in sorted(expected_keys):
        raw = policy[timeframe]
        if isinstance(raw, bool):
            raise ValueError(f"freshness limit for {timeframe} must be a finite number")
        try:
            value = float(raw)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"freshness limit for {timeframe} must be a finite number"
            ) from exc
        maximum = float(_MAX_APPROVED_FRESHNESS_HOURS[timeframe])
        if not math.isfinite(value) or not 0 < value <= maximum:
            raise ValueError(
                f"freshness limit for {timeframe} must be finite and within (0, {maximum}]"
            )
        validated[timeframe] = value
    return validated


_ACTIVE_FRESHNESS_LIMIT_HOURS = MappingProxyType(
    _validate_freshness_policy(DEFAULT_FRESHNESS_LIMIT_HOURS)
)
_FRESHNESS_POLICY_CANONICAL = json.dumps(
    {
        "version": FRESHNESS_POLICY_VERSION,
        "limits_hours": dict(_ACTIVE_FRESHNESS_LIMIT_HOURS),
    },
    sort_keys=True,
    separators=(",", ":"),
).encode("utf-8")
FRESHNESS_POLICY_DIGEST = hashlib.sha256(_FRESHNESS_POLICY_CANONICAL).hexdigest()


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


def _normalize_as_of(as_of_utc: datetime | None) -> pd.Timestamp:
    if as_of_utc is None:
        return pd.Timestamp(datetime.now(timezone.utc))
    timestamp = pd.Timestamp(as_of_utc)
    if timestamp.tzinfo is None:
        timestamp = timestamp.tz_localize("UTC")
    else:
        timestamp = timestamp.tz_convert("UTC")
    return timestamp


def evaluate_readiness(
    status_frame: pd.DataFrame,
    minimum_rows: int = 0,
    *,
    as_of_utc: datetime | None = None,
    freshness_limits_hours: dict[str, float] | None = None,
) -> pd.DataFrame:
    """Add deterministic, fail-closed research-readiness fields to a status report."""
    missing_columns = REQUIRED_COLUMNS.difference(status_frame.columns)
    if missing_columns:
        joined = ", ".join(sorted(missing_columns))
        raise ValueError(f"Status report is missing required columns: {joined}")
    if minimum_rows < 0:
        raise ValueError("minimum_rows must be non-negative")
    if freshness_limits_hours is not None:
        raise ValueError(
            "runtime freshness policy overrides are not allowed; use a registered policy version"
        )

    limits = dict(_ACTIVE_FRESHNESS_LIMIT_HOURS)
    result = status_frame.copy()
    result["rows"] = pd.to_numeric(result["rows"], errors="coerce").fillna(0).astype(int)
    result["integrity_ok"] = result["integrity_ok"].map(normalize_bool)
    result["status"] = result["status"].astype(str).str.strip().str.lower()
    result["timeframe"] = result["timeframe"].astype(str).str.strip().str.lower()

    as_of = _normalize_as_of(as_of_utc)
    evaluated_at_utc = as_of.isoformat()
    last_candle = pd.to_datetime(result["last_candle_utc"], utc=True, errors="coerce")
    freshness_hours = (as_of - last_candle).dt.total_seconds() / 3600.0
    result["freshness_hours"] = freshness_hours.round(4)
    result["freshness_limit_hours"] = result["timeframe"].map(limits)
    result["freshness_policy_version"] = FRESHNESS_POLICY_VERSION
    result["freshness_policy_digest"] = FRESHNESS_POLICY_DIGEST
    result["evaluated_at_utc"] = evaluated_at_utc
    result["freshness_ok"] = (
        last_candle.notna()
        & result["freshness_limit_hours"].notna()
        & result["freshness_hours"].ge(0)
        & (result["freshness_hours"] <= result["freshness_limit_hours"])
    )

    reasons: list[str] = []
    ready_flags: list[bool] = []

    for row in result.to_dict("records"):
        if not row["integrity_ok"]:
            reason = "integrity_failed"
        elif pd.isna(row["freshness_limit_hours"]):
            reason = "freshness_policy_missing"
        elif pd.isna(row["freshness_hours"]) or float(row["freshness_hours"]) < 0:
            reason = "last_candle_invalid"
        elif not row["freshness_ok"]:
            reason = "stale_data"
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

    evaluated_values = readiness_frame["evaluated_at_utc"].dropna().unique().tolist()
    evaluated_at_utc = evaluated_values[0] if len(evaluated_values) == 1 else None
    lines = [
        "# LBank Data Readiness",
        "",
        f"- Total series: {summary['total_series']}",
        f"- Ready for research: {summary['ready_series']}",
        f"- Blocked: {summary['blocked_series']}",
        f"- All ready: {summary['all_ready']}",
        f"- Evaluated at UTC: {evaluated_at_utc}",
        f"- Freshness policy version: {FRESHNESS_POLICY_VERSION}",
        f"- Freshness policy digest: {FRESHNESS_POLICY_DIGEST}",
        "",
        "| Symbol | Timeframe | Rows | Status | Integrity OK | Freshness h | Freshness limit h | Fresh | Missing | Gaps | Duplicates | Off-grid | Ready | Reason |",
        "|---|---|---:|---|---|---:|---:|---|---:|---:|---:|---:|---|---|",
    ]
    for row in readiness_frame.sort_values(["symbol", "timeframe"]).to_dict("records"):
        lines.append(
            "| {symbol} | {timeframe} | {rows} | {status} | {integrity_ok} | "
            "{freshness_hours} | {freshness_limit_hours} | {freshness_ok} | "
            "{missing_candles} | {gap_count} | {duplicate_count} | "
            "{off_grid_count} | {ready_for_research} | {readiness_reason} |".format(**row)
        )
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    payload = {
        "summary": summary,
        "evaluated_at_utc": evaluated_at_utc,
        "freshness_policy": {
            "version": FRESHNESS_POLICY_VERSION,
            "digest": FRESHNESS_POLICY_DIGEST,
        },
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
    *,
    as_of_utc: datetime | None = None,
) -> dict[str, Any]:
    if not status_path.exists():
        raise FileNotFoundError(f"Status report not found: {status_path}")

    status_frame = pd.read_csv(status_path)
    readiness_frame = evaluate_readiness(
        status_frame,
        minimum_rows=minimum_rows,
        as_of_utc=as_of_utc,
    )
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
