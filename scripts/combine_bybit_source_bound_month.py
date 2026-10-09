"""Combine only independently verified same-model BTC/ETH monthly parts."""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pandas as pd
import bybit_spot_backfill as backfill
import stream_bybit_symbol_month as stream


def combine(parts_root, pattern, output, start_date, end_date):
    roots = sorted(parts_root.glob(pattern))
    if len(roots) != 2 or any(root.is_symlink() for root in roots):
        raise ValueError("two regular source-bound monthly parts required")
    if output.exists():
        raise ValueError("combined output must be new; preserve prior evidence")
    expected_model = stream.candle_model_receipt()
    sources, statuses, runs, units = [], [], [], []
    for root in roots:
        model = json.loads((root / "_candle_model.json").read_text())
        report = json.loads((root / "_backfill_report.json").read_text())
        manifest = json.loads((root / "_source_manifest.json").read_text())
        checkpoint = json.loads((root / "_checkpoint.json").read_text())
        qa = json.loads((root / "_independent_csv_qa.json").read_text())
        if (model != expected_model or report.get("candle_model") != model
                or len(manifest) != 1 or manifest[0].get("candle_model") != model):
            raise ValueError("missing, stale or mixed candle-model provenance")
        source = manifest[0]
        if (qa.get("passed") is not True or qa.get("source_archive_sha256") != source["sha256"]
                or qa.get("source_rows") != source["valid_trade_rows"]
                or qa.get("live_trading_authority") is not False
                or qa.get("automatic_strategy_promotion") is not False):
            raise ValueError("independent monthly CSV QA missing or mismatched")
        files = {str(p.relative_to(root)).replace("\\", "/"): hashlib.sha256(p.read_bytes()).hexdigest()
                 for p in sorted((root / "bybit_market").glob("*/*.parquet"))}
        if len(files) != 3 or qa.get("output_parquet_sha256") != files:
            raise ValueError("independently checked monthly output hashes changed")
        canonical = stream.collector.canonical_symbol(source["symbol"])
        for timeframe in ("minute15", "hour1", "hour4"):
            frame = pd.read_parquet(root / "bybit_market" / canonical / f"{timeframe}.parquet")
            if (not frame["symbol"].eq(canonical).all()
                    or not frame["timeframe"].eq(timeframe).all()):
                raise ValueError("monthly canonical symbol or timeframe mismatch")
            _, status = stream.collector.evaluate_series(frame, source["symbol"], timeframe, start_date, end_date)
            if not status["integrity_ok"] or status["status"] != "ready":
                raise ValueError("actual combined monthly series is not ready")
        if (source.get("start_date") != start_date or source.get("end_date") != end_date
                or len(report["statuses"]) != 3
                or not all(x["integrity_ok"] is True and x["status"] == "ready" for x in report["statuses"])
                or len(checkpoint["completed_units"]) != 1):
            raise ValueError("monthly part coverage or integrity mismatch")
        sources.extend(manifest)
        statuses.extend(report["statuses"])
        runs.extend(checkpoint.get("runs", []))
        units.extend(checkpoint["completed_units"])
    if {s["symbol"] for s in sources} != {"BTCUSDT", "ETHUSDT"} or len({u["unit_id"] for u in units}) != 1:
        raise ValueError("combined monthly symbols or units mismatch")
    output.mkdir(parents=True)
    for root in roots:
        shutil.copytree(root / "bybit_market", output / "bybit_market", dirs_exist_ok=True)
        symbol = json.loads((root / "_source_manifest.json").read_text())[0]["symbol"]
        shutil.copy2(root / "_independent_csv_qa.json", output / f"_independent_csv_qa_{symbol}.json")
    unit = {**units[0], "filenames": {s["symbol"]: s["filename"] for s in sources}}
    checkpoint = {"schema_version": 1, "completed_units": [unit], "failed_units": [], "runs": runs}
    report = {
        "candle_model": expected_model, "generated_at_utc": pd.Timestamp.now(tz="UTC").isoformat(),
        "configuration": {"start_date": start_date, "end_date": end_date,
                          "symbols": ["BTCUSDT", "ETHUSDT"], "max_archives_per_run": 2},
        "summary": {"plan_units": 1, "plan_archives": 2, "completed_units": 1,
                    "remaining_units": 0, "units_completed_this_run": 1,
                    "archives_completed_this_run": 2, "run_failures": 0,
                    "backfill_complete": True, "current_dataset_integrity_ok": True},
        "completed_this_run": [unit], "sources_this_run": sources,
        "run_failures": [], "statuses": statuses,
    }
    for name, value in (("_candle_model.json", expected_model), ("_checkpoint.json", checkpoint),
                        ("_source_manifest.json", sources), ("_backfill_report.json", report)):
        backfill.write_json(output / name, value)
    pd.DataFrame(sources).to_csv(output / "_source_manifest.csv", index=False)
    pd.DataFrame(statuses).to_csv(output / "_backfill_status.csv", index=False)
    backfill.validate_candle_model_state(output)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--parts-root", type=Path, required=True)
    parser.add_argument("--pattern", required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--start-date", required=True)
    parser.add_argument("--end-date", required=True)
    args = parser.parse_args()
    result = combine(args.parts_root, args.pattern, args.output_root, args.start_date, args.end_date)
    print(json.dumps(result["summary"], sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
