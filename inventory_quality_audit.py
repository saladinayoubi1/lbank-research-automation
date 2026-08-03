from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import candle_quality_audit

DEFAULT_INVENTORY_JSON = Path("build/gap_probe/_gap_inventory.json")
DEFAULT_OUTPUT_ROOT = Path("build/gap_probe")


def inventory_to_probe_report(inventory: dict[str, Any]) -> dict[str, Any]:
    """Adapt inventory rows to the established quality-audit input contract."""
    results: list[dict[str, Any]] = []
    for row in inventory.get("rows", []):
        raw_row = {
            "timestamp_utc": row["timestamp_utc"],
            "open": row["open"],
            "high": row["high"],
            "low": row["low"],
            "close": row["close"],
            "volume": row["volume"],
            "validation_reasons": row.get("validation_reasons", []),
        }
        results.append({
            "symbol": row["symbol"],
            "timeframe": row["timeframe"],
            "missing_timestamp_utc": row["timestamp_utc"],
            "classification": (
                "recoverable_validated"
                if row.get("canonical_valid")
                else "present_but_rejected_by_validation"
            ),
            "observations": [{"exact_raw_rows": [raw_row]}],
        })

    return {
        "generated_at_utc": inventory.get("generated_at_utc"),
        "summary": inventory.get("summary", {}),
        "results": results,
    }


def build_inventory_quality_audit(inventory: dict[str, Any]) -> dict[str, Any]:
    audit = candle_quality_audit.build_quality_audit(
        inventory_to_probe_report(inventory)
    )
    audit["source_inventory_summary"] = inventory.get("summary", {})
    audit["source_type"] = "cached_gap_inventory"
    return audit


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Measure OHLCV severity for every missing row observed in cached probe responses."
    )
    parser.add_argument(
        "--inventory-json",
        type=Path,
        default=DEFAULT_INVENTORY_JSON,
    )
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    inventory = json.loads(args.inventory_json.read_text(encoding="utf-8"))
    audit = build_inventory_quality_audit(inventory)
    candle_quality_audit.write_quality_audit(audit, args.output_root)
    print(json.dumps(audit["summary"], sort_keys=True))


if __name__ == "__main__":
    main()
