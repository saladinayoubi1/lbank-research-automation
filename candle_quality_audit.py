from __future__ import annotations

import argparse
import json
import math
from collections import Counter
from pathlib import Path
from statistics import median
from typing import Any

import pandas as pd

DEFAULT_PROBE_JSON = Path("build/gap_probe/_gap_probe.json")
DEFAULT_OUTPUT_ROOT = Path("build/gap_probe")
THRESHOLD_ABS_TOLERANCE = 1e-9


def finite_number(value: Any, field: str) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{field} must be finite: {value!r}")
    return number


def at_or_below(value: float, threshold: float) -> bool:
    return value <= threshold or math.isclose(
        value,
        threshold,
        rel_tol=0.0,
        abs_tol=THRESHOLD_ABS_TOLERANCE,
    )


def severity_bucket(violation_bps: float) -> str:
    if violation_bps < 0 or not math.isfinite(violation_bps):
        raise ValueError("violation_bps must be finite and non-negative")
    if math.isclose(
        violation_bps,
        0.0,
        rel_tol=0.0,
        abs_tol=THRESHOLD_ABS_TOLERANCE,
    ):
        return "none"
    if at_or_below(violation_bps, 1):
        return "rounding_le_1_bps"
    if at_or_below(violation_bps, 5):
        return "minor_le_5_bps"
    if at_or_below(violation_bps, 10):
        return "moderate_le_10_bps"
    return "material_gt_10_bps"


def analyze_ohlcv_row(row: dict[str, Any]) -> dict[str, Any]:
    open_price = finite_number(row["open"], "open")
    high = finite_number(row["high"], "high")
    low = finite_number(row["low"], "low")
    close = finite_number(row["close"], "close")
    volume = finite_number(row["volume"], "volume")

    high_required = max(open_price, close, low)
    low_required = min(open_price, close, high)
    high_shortfall = max(0.0, high_required - high)
    low_excess = max(0.0, low - low_required)
    negative_volume = max(0.0, -volume)

    price_reference = max(abs(open_price), abs(close), 1e-30)
    high_shortfall_bps = high_shortfall / price_reference * 10_000
    low_excess_bps = low_excess / price_reference * 10_000
    max_violation_bps = max(high_shortfall_bps, low_excess_bps)

    reasons: list[str] = []
    if high_shortfall > 0:
        reasons.append("high_below_ohlc_max")
    if low_excess > 0:
        reasons.append("low_above_ohlc_min")
    if negative_volume > 0:
        reasons.append("negative_volume")

    return {
        "open": open_price,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
        "high_shortfall": high_shortfall,
        "low_excess": low_excess,
        "negative_volume_magnitude": negative_volume,
        "high_shortfall_bps": high_shortfall_bps,
        "low_excess_bps": low_excess_bps,
        "max_violation_bps": max_violation_bps,
        "severity": severity_bucket(max_violation_bps),
        "computed_reasons": reasons,
    }


def unique_probe_rows(probe_report: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()

    for result in probe_report.get("results", []):
        symbol = result["symbol"]
        timeframe = result["timeframe"]
        target = result["missing_timestamp_utc"]

        for observation in result.get("observations", []):
            for raw_row in observation.get("exact_raw_rows", []):
                key = (
                    symbol,
                    timeframe,
                    target,
                    str(raw_row.get("open")),
                    str(raw_row.get("high")),
                    str(raw_row.get("low")),
                    str(raw_row.get("close")),
                    str(raw_row.get("volume")),
                )
                if key in seen:
                    continue
                seen.add(key)

                analysis = analyze_ohlcv_row(raw_row)
                recorded_reasons = sorted(set(raw_row.get("validation_reasons", [])))
                computed_reasons = sorted(set(analysis.pop("computed_reasons")))
                rows.append({
                    "symbol": symbol,
                    "timeframe": timeframe,
                    "timestamp_utc": target,
                    "probe_classification": result.get("classification"),
                    "recorded_reasons": recorded_reasons,
                    "computed_reasons": computed_reasons,
                    "reason_match": recorded_reasons == computed_reasons,
                    **analysis,
                })

    return sorted(
        rows,
        key=lambda row: (row["symbol"], row["timeframe"], row["timestamp_utc"]),
    )


def build_quality_audit(probe_report: dict[str, Any]) -> dict[str, Any]:
    rows = unique_probe_rows(probe_report)
    reason_counts: Counter[str] = Counter()
    severity_counts: Counter[str] = Counter()
    for row in rows:
        reason_counts.update(row["computed_reasons"])
        severity_counts[row["severity"]] += 1

    violation_values = [row["max_violation_bps"] for row in rows]
    return {
        "generated_at_utc": pd.Timestamp.now(tz="UTC").isoformat(),
        "source_probe_generated_at_utc": probe_report.get("generated_at_utc"),
        "source_probe_summary": probe_report.get("summary", {}),
        "summary": {
            "unique_invalid_rows": len(rows),
            "reason_counts": dict(sorted(reason_counts.items())),
            "severity_counts": dict(sorted(severity_counts.items())),
            "reason_mismatch_rows": sum(not row["reason_match"] for row in rows),
            "maximum_violation_bps": max(violation_values, default=0.0),
            "median_violation_bps": median(violation_values) if violation_values else 0.0,
            "at_or_below_1_bps": sum(
                at_or_below(value, 1) for value in violation_values
            ),
            "at_or_below_5_bps": sum(
                at_or_below(value, 5) for value in violation_values
            ),
            "at_or_below_10_bps": sum(
                at_or_below(value, 10) for value in violation_values
            ),
            "above_10_bps": sum(
                not at_or_below(value, 10) for value in violation_values
            ),
        },
        "rows": rows,
    }


def render_markdown(audit: dict[str, Any]) -> str:
    summary = audit["summary"]
    lines = [
        "# LBank Candle Quality Severity Audit",
        "",
        f"Generated at: {audit['generated_at_utc']}",
        f"Source probe generated at: {audit['source_probe_generated_at_utc']}",
        "",
        "This report measures invalid public OHLCV rows. It does not repair, clamp, "
        "or admit them into canonical Parquet.",
        "",
        "## Summary",
        "",
        f"- Unique invalid rows: {summary['unique_invalid_rows']}",
        f"- Reason mismatches: {summary['reason_mismatch_rows']}",
        f"- Median violation: {summary['median_violation_bps']:.6f} bps",
        f"- Maximum violation: {summary['maximum_violation_bps']:.6f} bps",
        f"- At or below 1 bps: {summary['at_or_below_1_bps']}",
        f"- At or below 5 bps: {summary['at_or_below_5_bps']}",
        f"- At or below 10 bps: {summary['at_or_below_10_bps']}",
        f"- Above 10 bps: {summary['above_10_bps']}",
        "",
        "### Rejection reasons",
        "",
    ]
    for reason, count in summary["reason_counts"].items():
        lines.append(f"- `{reason}`: {count}")

    lines.extend([
        "",
        "### Severity buckets",
        "",
    ])
    for severity, count in summary["severity_counts"].items():
        lines.append(f"- `{severity}`: {count}")

    lines.extend([
        "",
        "## Rows",
        "",
        "| Symbol | Timeframe | Timestamp UTC | Reasons | Violation bps | Severity |",
        "|---|---|---|---|---:|---|",
    ])
    for row in audit["rows"]:
        reasons = ", ".join(row["computed_reasons"]) or "none"
        lines.append(
            f"| {row['symbol']} | {row['timeframe']} | {row['timestamp_utc']} | "
            f"{reasons} | {row['max_violation_bps']:.6f} | {row['severity']} |"
        )

    lines.extend([
        "",
        "## Interpretation",
        "",
        "- `rounding_le_1_bps` is compatible with small precision discrepancies, but is not automatically accepted.",
        "- `minor_le_5_bps` and `moderate_le_10_bps` require explicit source-policy review.",
        "- `material_gt_10_bps` is a substantial candle inconsistency and must remain excluded.",
        "- Mixed severity across the same source prevents a single global tolerance from being a safe repair policy.",
        "",
    ])
    return "\n".join(lines)


def write_quality_audit(
    audit: dict[str, Any],
    output_root: Path = DEFAULT_OUTPUT_ROOT,
) -> None:
    output_root.mkdir(parents=True, exist_ok=True)
    (output_root / "_candle_quality_audit.json").write_text(
        json.dumps(audit, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (output_root / "_candle_quality_audit.md").write_text(
        render_markdown(audit),
        encoding="utf-8",
    )

    csv_rows = []
    for row in audit["rows"]:
        csv_rows.append({
            **row,
            "recorded_reasons": ",".join(row["recorded_reasons"]),
            "computed_reasons": ",".join(row["computed_reasons"]),
        })
    pd.DataFrame(csv_rows).to_csv(
        output_root / "_candle_quality_audit.csv",
        index=False,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Measure severity of invalid raw candle rows from a gap probe."
    )
    parser.add_argument("--probe-json", type=Path, default=DEFAULT_PROBE_JSON)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    probe_report = json.loads(args.probe_json.read_text(encoding="utf-8"))
    audit = build_quality_audit(probe_report)
    write_quality_audit(audit, args.output_root)
    print(json.dumps(audit["summary"], sort_keys=True))


if __name__ == "__main__":
    main()
