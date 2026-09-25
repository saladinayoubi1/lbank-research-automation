"""Reproducible historical DEVELOPMENT diagnostics for the frozen 4h low-turnover grid.

Never opens the future holdout or qualifies a candidate. Public Bybit spot only.
Old Paper #984 is excluded from this bounded historical development cutoff.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

import pandas as pd

from market_data_source_validator import load_and_validate
from phase5_data_binding import validate_canonical_dataset
from phase6_research_pipeline import fetch_bind_bybit_dataset
from product_research_runtime import _public_mapping, _registry_path
import nexus_low_turnover_hypothesis_v1 as low
import nexus_multitimeframe_strategy_discovery as executor

SCHEMA = "nexus.low-turnover-historical-training-diagnostics.v1"
SOURCE_SHA = "aca436fff20f1d208d4ec67f54099f7d3fc75d89"
CUTOFF = pd.Timestamp("2026-08-20T00:00:00Z")
COUNT = 320
STEP_MS = 4 * 60 * 60 * 1000
START_MS = int(CUTOFF.timestamp() * 1000) - (COUNT - 1) * STEP_MS
END_MS = int(CUTOFF.timestamp() * 1000)


class HistoricalTrainingError(ValueError):
    pass


def _digest(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _frame(dataset: Mapping[str, Any], symbol: str) -> pd.DataFrame:
    validated = validate_canonical_dataset(dataset, registry_path=_registry_path())
    if (validated.get("source") != "Bybit" or validated.get("source_symbol") != symbol
            or validated.get("manifest_timeframe") != "4h"
            or validated.get("row_count") != COUNT):
        raise HistoricalTrainingError("development dataset binding or length mismatch")
    rows = validated["rows"]
    opens = [int(row["open_time_ms"]) for row in rows]
    if opens != list(range(START_MS, END_MS + STEP_MS, STEP_MS)):
        raise HistoricalTrainingError("development chronology/cutoff mismatch")
    return pd.DataFrame({
        "timestamp": pd.to_datetime(opens, unit="ms", utc=True),
        "open": [float(row["open"]) for row in rows],
        "high": [float(row["high"]) for row in rows],
        "low": [float(row["low"]) for row in rows],
        "close": [float(row["close"]) for row in rows],
        "volume": [float(row["volume"]) for row in rows],
    })


def _metrics(frame: pd.DataFrame, targets: pd.Series, profile: Mapping[str, Any]) -> dict:
    windows = {"full": (0, COUNT), "early_training": (0, 240),
               "late_training": (80, COUNT)}
    return {
        name: {k: float(v) if k != "fill_count" else int(v)
               for k, v in executor._simulate(
                   frame, targets, start, end, profile, bars_per_year=2190.0
               ).items()}
        for name, (start, end) in windows.items()
    }


def evaluate(manifest: Mapping[str, Any], datasets: Mapping[str, Any]) -> dict:
    if low._canonical(manifest) != low._canonical(low.EXPECTED_MANIFEST):
        raise HistoricalTrainingError("frozen hypothesis manifest mismatch")
    if set(datasets) != {"BTCUSDT", "ETHUSDT"}:
        raise HistoricalTrainingError("development requires exact BTC/ETH surface")
    cells = []
    dataset_provenance = {}
    for symbol in ("BTCUSDT", "ETHUSDT"):
        dataset = datasets[symbol]
        frame = _frame(dataset, symbol)
        dataset_provenance[symbol] = {
            "binding_sha256": dataset["binding_sha256"],
            "manifest_sha256": dataset["manifest_sha256"],
            "row_count": COUNT,
            "last_open_time_ms": END_MS,
            "latest_data_used_for_selection": False,
        }
        targets_by_name = {
            "control_existing_12bar_momentum": executor.generate_targets(
                frame, "momentum", {"lookback": 12, "entry_threshold": 0.002}
            ),
        }
        for index, config in enumerate(manifest["variants"], 1):
            targets_by_name[f"frozen_variant_{index}"] = low.generate_targets(frame, config)
        for name, targets in targets_by_name.items():
            cells.append({
                "symbol": symbol, "strategy": name,
                "profiles": {
                    profile_name: _metrics(frame, targets, costs)
                    for profile_name, costs in manifest["execution"].items()
                },
            })
    core = {
        "schema_version": SCHEMA, "hypothesis_source_sha": SOURCE_SHA,
        "hypothesis_manifest_digest": _digest(manifest),
        "status": "historical_development_diagnostics_only",
        "dataset_provenance": dataset_provenance,
        "training_boundary_last_open_utc": CUTOFF.isoformat(),
        "training_uses_previously_inspected_history": True,
        "failed_prior_paper_period_excluded": True,
        "locked_holdout_evaluated": False,
        "future_holdout_used_for_selection": False,
        "qualifies_for_paper_review": False, "automatic_paper_started": False,
        "research_only": True, "paper_only": True, "live_trading_authority": False,
        "evaluated_cells": cells,
    }
    return {**core, "diagnostics_sha256": _digest(core)}


def collect_public() -> dict:
    registry = load_and_validate(_registry_path())
    result = {}
    for symbol in ("BTCUSDT", "ETHUSDT"):
        mapping, source = _public_mapping(registry, symbol, "hour4")
        result[symbol] = fetch_bind_bybit_dataset(
            canonical_symbol=mapping["canonical_symbol"],
            source_symbol=source["symbol"], interval="240",
            now_ms=END_MS + STEP_MS + 1,
            start_time_ms=START_MS, end_time_ms=END_MS,
            limit=COUNT, timeout_seconds=20.0,
        )
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path,
                        default=Path("experiments/nexus_low_turnover_hypothesis_v1.json"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--reuse-datasets", action="store_true")
    args = parser.parse_args()
    manifest = low.load_manifest(args.manifest)
    root = args.output.resolve()
    if args.reuse_datasets:
        datasets = {
            symbol: json.loads((root / f"{symbol}-public-training.json").read_text("utf-8"))
            for symbol in ("BTCUSDT", "ETHUSDT")
        }
    else:
        root.mkdir(parents=True, exist_ok=False)
        datasets = collect_public()
        for symbol, data in datasets.items():
            (root / f"{symbol}-public-training.json").write_text(
                json.dumps(data, indent=2, sort_keys=True, allow_nan=False) + "\n",
                encoding="utf-8",
            )
    report = evaluate(manifest, datasets)
    (root / "training-diagnostics.json").write_text(
        json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"status": report["status"],
                      "diagnostics_sha256": report["diagnostics_sha256"],
                      "cell_count": len(report["evaluated_cells"])}))


if __name__ == "__main__":
    main()
