"""Leakage-resistant four-symbol NEXUS strategy discovery.

Discovery evaluates the existing three strategy families across BTC/ETH/SOL/XRP
and 15m/1h/4h using one independently verified, bounded public Bybit snapshot.
Variant ranking is training-only. Locked chronological holdout and stress costs
are evaluated only after selection. Output is RESEARCH_PROPOSAL_ONLY and cannot
create Candidate/Paper/Live state or use private exchange credentials.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping, Sequence

import pandas as pd

import nexus_multitimeframe_strategy_discovery as legacy
import nexus_multipair_archive_snapshot as archive_snapshot
import nexus_multipair_discovery_snapshot as rest_snapshot
from nexus_multipair_discovery_snapshot import SYMBOLS, TIMEFRAME_NAMES


SCHEMA = "nexus.multipair-strategy-discovery.v1"
MANIFEST_SCHEMA = "nexus.multipair-strategy-discovery-manifest.v1"
FAMILIES = ("momentum", "trend_breakout", "mean_reversion")
SUPPORTED_SNAPSHOT_SCHEMAS = (rest_snapshot.SCHEMA, archive_snapshot.SCHEMA)


class MultiPairStrategyDiscoveryError(RuntimeError):
    pass


def _digest(value: Any) -> str:
    try:
        return legacy._digest(value)
    except Exception as exc:
        raise MultiPairStrategyDiscoveryError("discovery evidence is not canonical JSON") from exc


def _source_sha(value: str) -> str:
    try:
        return legacy._source_sha(value)
    except Exception as exc:
        raise MultiPairStrategyDiscoveryError("source_sha must be an exact Git SHA") from exc


def load_manifest(path: str | Path) -> dict[str, Any]:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise MultiPairStrategyDiscoveryError("multi-pair discovery manifest is unavailable") from exc
    required = {
        "schema_version", "experiment_id", "dataset", "symbols", "timeframes", "families",
        "train_fraction", "execution", "gates", "variants", "authority",
    }
    if not isinstance(value, dict) or set(value) != required or value.get("schema_version") != MANIFEST_SCHEMA:
        raise MultiPairStrategyDiscoveryError("multi-pair discovery manifest schema mismatch")
    if tuple(value.get("symbols", ())) != SYMBOLS:
        raise MultiPairStrategyDiscoveryError("multi-pair discovery requires the approved four-symbol surface")
    if tuple(value.get("timeframes", ())) != TIMEFRAME_NAMES:
        raise MultiPairStrategyDiscoveryError("multi-pair discovery timeframes must be 15m/1h/4h")
    if tuple(value.get("families", ())) != FAMILIES:
        raise MultiPairStrategyDiscoveryError("multi-pair discovery families mismatch")
    dataset = value.get("dataset")
    if not isinstance(dataset, dict) or set(dataset) != {"dataset_root", "snapshot_manifest"}:
        raise MultiPairStrategyDiscoveryError("multi-pair discovery dataset contract mismatch")
    if not str(dataset.get("dataset_root", "")).strip() or Path(str(dataset["snapshot_manifest"])).name != dataset["snapshot_manifest"]:
        raise MultiPairStrategyDiscoveryError("multi-pair discovery dataset path is unsafe")
    fraction = value.get("train_fraction")
    if isinstance(fraction, bool) or not isinstance(fraction, (int, float)) or not 0.55 <= float(fraction) <= 0.8:
        raise MultiPairStrategyDiscoveryError("train_fraction is outside the preregistered range")
    authority = value.get("authority")
    if authority != {
        "research_only": True,
        "paper_only": True,
        "live_trading_authority": False,
        "private_credentials_allowed": False,
        "automatic_strategy_promotion": False,
    }:
        raise MultiPairStrategyDiscoveryError("multi-pair discovery authority boundary mismatch")
    execution = value.get("execution")
    if not isinstance(execution, dict) or set(execution) != {"conservative", "stress"}:
        raise MultiPairStrategyDiscoveryError("multi-pair execution profiles mismatch")
    for profile in ("conservative", "stress"):
        row = execution.get(profile)
        if not isinstance(row, dict) or set(row) != {"fee_bps", "slippage_bps"}:
            raise MultiPairStrategyDiscoveryError("multi-pair execution profile mismatch")
        for field in ("fee_bps", "slippage_bps"):
            raw = row[field]
            if isinstance(raw, bool) or not isinstance(raw, (int, float)) or float(raw) < 0:
                raise MultiPairStrategyDiscoveryError("multi-pair execution profile is invalid")
    gates = value.get("gates")
    if not isinstance(gates, dict) or set(gates) != {"training", "locked"}:
        raise MultiPairStrategyDiscoveryError("multi-pair discovery gates mismatch")
    try:
        for gate in gates.values():
            legacy._validate_gate(gate)
    except Exception as exc:
        raise MultiPairStrategyDiscoveryError("multi-pair discovery gate is invalid") from exc
    variants = value.get("variants")
    if not isinstance(variants, dict) or set(variants) != set(FAMILIES):
        raise MultiPairStrategyDiscoveryError("multi-pair variant families are invalid")
    for family in FAMILIES:
        rows = variants.get(family)
        if not isinstance(rows, list) or not 2 <= len(rows) <= 24 or any(not isinstance(row, dict) for row in rows):
            raise MultiPairStrategyDiscoveryError("multi-pair variant grid is missing or unbounded")
        ids = [legacy._variant_id(family, row) for row in rows]
        if len(ids) != len(set(ids)):
            raise MultiPairStrategyDiscoveryError("multi-pair variant grid contains duplicates")
    return value


def _verify_snapshot_by_schema(root: Path, value: Mapping[str, Any]) -> dict[str, Any]:
    schema = value.get("schema_version")
    if schema == rest_snapshot.SCHEMA:
        return rest_snapshot.verify_snapshot(root, value)
    if schema == archive_snapshot.SCHEMA:
        return archive_snapshot.verify_snapshot(root, value)
    raise MultiPairStrategyDiscoveryError("unsupported multi-pair snapshot schema")


def _snapshot_as_of_ms(value: Mapping[str, Any]) -> int:
    if value.get("schema_version") == rest_snapshot.SCHEMA:
        raw = value.get("as_of_ms")
        if isinstance(raw, bool) or not isinstance(raw, int) or raw <= 0:
            raise MultiPairStrategyDiscoveryError("REST snapshot as_of_ms is invalid")
        return raw
    if value.get("schema_version") == archive_snapshot.SCHEMA:
        cells = value.get("cells")
        if not isinstance(cells, list) or len(cells) != len(SYMBOLS) * len(TIMEFRAME_NAMES):
            raise MultiPairStrategyDiscoveryError("archive snapshot cells are invalid")
        opens = [row.get("last_open_time_ms") for row in cells if isinstance(row, Mapping)]
        if len(opens) != len(cells) or any(isinstance(item, bool) or not isinstance(item, int) or item <= 0 for item in opens):
            raise MultiPairStrategyDiscoveryError("archive snapshot as-of boundary is invalid")
        return max(opens)
    raise MultiPairStrategyDiscoveryError("unsupported multi-pair snapshot schema")


def _snapshot_data_origin(value: Mapping[str, Any]) -> str:
    schema = value.get("schema_version")
    if schema == archive_snapshot.SCHEMA:
        origin = value.get("data_origin")
        if origin != "official_public_bybit_spot_trade_archive_aggregated":
            raise MultiPairStrategyDiscoveryError("archive snapshot data origin mismatch")
        return str(origin)
    if schema == rest_snapshot.SCHEMA:
        return "canonical_public_bybit_rest_closed_candles"
    raise MultiPairStrategyDiscoveryError("unsupported multi-pair snapshot schema")


def _load_snapshot(manifest: Mapping[str, Any], *, source_sha: str) -> tuple[Path, dict[str, Any]]:
    root = Path(str(manifest["dataset"]["dataset_root"])).resolve()
    snapshot_path = root / str(manifest["dataset"]["snapshot_manifest"])
    try:
        value = json.loads(snapshot_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise MultiPairStrategyDiscoveryError("verified multi-pair snapshot manifest is unavailable") from exc
    if not isinstance(value, dict):
        raise MultiPairStrategyDiscoveryError("verified multi-pair snapshot manifest is invalid")
    verification = _verify_snapshot_by_schema(root, value)
    if verification.get("decision") != "pass":
        raise MultiPairStrategyDiscoveryError("multi-pair discovery snapshot verification failed")
    if value.get("source_sha") != source_sha:
        raise MultiPairStrategyDiscoveryError("snapshot source SHA does not match discovery source SHA")
    if value.get("symbols") != list(SYMBOLS) or value.get("timeframes") != list(TIMEFRAME_NAMES):
        raise MultiPairStrategyDiscoveryError("snapshot surface does not match discovery surface")
    if value.get("schema_version") == archive_snapshot.SCHEMA and value.get("runtime_freshness_claimed") is not False:
        raise MultiPairStrategyDiscoveryError("historical archive snapshot cannot claim runtime freshness")
    _snapshot_as_of_ms(value)
    _snapshot_data_origin(value)
    return root, value


def _load_frame(root: Path, symbol: str, timeframe: str) -> pd.DataFrame:
    path = root / "bybit_market" / symbol / f"{timeframe}.parquet"
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 20_000_000:
        raise MultiPairStrategyDiscoveryError(f"verified snapshot frame missing: {symbol}/{timeframe}")
    frame = pd.read_parquet(path)
    if frame.columns.tolist() != legacy.REQUIRED_COLUMNS:
        raise MultiPairStrategyDiscoveryError(f"snapshot schema mismatch: {symbol}/{timeframe}")
    frame = frame.copy()
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True)
    frame = frame.sort_values("timestamp").reset_index(drop=True)
    if len(frame) < 160 or frame["timestamp"].duplicated().any() or not frame["timestamp"].is_monotonic_increasing:
        raise MultiPairStrategyDiscoveryError(f"snapshot history is insufficient: {symbol}/{timeframe}")
    step = pd.Timedelta(milliseconds=legacy.TIMEFRAME_STEP_MS[timeframe])
    if not bool((frame["timestamp"].diff().iloc[1:] == step).all()):
        raise MultiPairStrategyDiscoveryError(f"snapshot cadence is not gap-free: {symbol}/{timeframe}")
    if set(frame["symbol"].astype(str)) != {symbol} or set(frame["timeframe"].astype(str)) != {timeframe}:
        raise MultiPairStrategyDiscoveryError(f"snapshot identity mismatch: {symbol}/{timeframe}")
    return frame


def _validate_alignment(frames: Mapping[str, pd.DataFrame], timeframe: str) -> None:
    if set(frames) != set(SYMBOLS):
        raise MultiPairStrategyDiscoveryError("four-symbol discovery surface is incomplete")
    reference = frames[SYMBOLS[0]]["timestamp"].reset_index(drop=True)
    for symbol in SYMBOLS[1:]:
        if not reference.equals(frames[symbol]["timestamp"].reset_index(drop=True)):
            raise MultiPairStrategyDiscoveryError(f"four-symbol snapshot timestamps are not aligned: {timeframe}")


def _evaluate_variant(
    frames: Mapping[str, pd.DataFrame],
    family: str,
    config: Mapping[str, Any],
    start_by_symbol: Mapping[str, int],
    end_by_symbol: Mapping[str, int],
    profile: Mapping[str, Any],
    *,
    timeframe: str,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    rows: list[dict[str, Any]] = []
    for symbol in SYMBOLS:
        target = legacy.generate_targets(frames[symbol], family, config)
        metric = legacy._simulate(
            frames[symbol], target, start_by_symbol[symbol], end_by_symbol[symbol], profile,
            bars_per_year=legacy.TIMEFRAME_BARS_PER_YEAR[timeframe],
        )
        rows.append({"symbol": symbol, **metric})
    return legacy._aggregate(rows), rows


def discover(manifest: Mapping[str, Any], *, source_sha: str) -> dict[str, Any]:
    source_sha = _source_sha(source_sha)
    root, snapshot = _load_snapshot(manifest, source_sha=source_sha)
    fraction = float(manifest["train_fraction"])
    cells: list[dict[str, Any]] = []
    proposals: list[dict[str, Any]] = []

    for timeframe in TIMEFRAME_NAMES:
        frames = {symbol: _load_frame(root, symbol, timeframe) for symbol in SYMBOLS}
        _validate_alignment(frames, timeframe)
        split = {
            symbol: max(80, min(len(frame) - 40, int(len(frame) * fraction)))
            for symbol, frame in frames.items()
        }
        train_start = {symbol: 0 for symbol in SYMBOLS}
        locked_end = {symbol: len(frame) for symbol, frame in frames.items()}
        for family in FAMILIES:
            training_rows: list[dict[str, Any]] = []
            for config in manifest["variants"][family]:
                summary, _ = _evaluate_variant(
                    frames, family, config, train_start, split,
                    manifest["execution"]["conservative"], timeframe=timeframe,
                )
                checks = legacy._gate(summary, manifest["gates"]["training"])
                training_rows.append({
                    "variant_id": legacy._variant_id(family, config),
                    "config": dict(config),
                    "summary": summary,
                    "gate_checks": checks,
                    "passes_training_gate": all(checks.values()),
                })
            training_rows.sort(key=lambda row: (-float(row["summary"]["score"]), row["variant_id"]))
            passers = [row for row in training_rows if row["passes_training_gate"]]
            selected = (passers or training_rows)[0]
            locked_profiles: dict[str, Any] = {}
            locked_pass = True
            for profile_name in ("conservative", "stress"):
                summary, per_symbol = _evaluate_variant(
                    frames, family, selected["config"], split, locked_end,
                    manifest["execution"][profile_name], timeframe=timeframe,
                )
                checks = legacy._gate(summary, manifest["gates"]["locked"])
                locked_profiles[profile_name] = {
                    "summary": summary,
                    "per_symbol": per_symbol,
                    "gate_checks": checks,
                    "passes": all(checks.values()),
                }
                locked_pass = locked_pass and all(checks.values())
            eligible = bool(selected["passes_training_gate"] and locked_pass)
            cell_core = {
                "timeframe": timeframe,
                "family": family,
                "eligible_symbols": list(SYMBOLS),
                "variant_count": len(training_rows),
                "training_gate_passers": len(passers),
                "selected_variant_id": selected["variant_id"],
                "selected_config": selected["config"],
                "selection_source": "training_only",
                "training_summary": selected["summary"],
                "locked_profiles": locked_profiles,
                "proposal_eligible": eligible,
                "automatic_candidate_created": False,
                "automatic_paper_forward_started": False,
                "live_trading_enabled": False,
            }
            cell = {**cell_core, "cell_digest": _digest(cell_core)}
            cells.append(cell)
            if eligible:
                proposal_core = {
                    "proposal_state": "RESEARCH_PROPOSAL_ONLY",
                    "family": family,
                    "timeframe": timeframe,
                    "eligible_symbols": list(SYMBOLS),
                    "strategy_config": selected["config"],
                    "variant_id": selected["variant_id"],
                    "cell_digest": cell["cell_digest"],
                    "dataset_snapshot_sha256": snapshot["snapshot_digest"],
                    "requires_independent_runtime_requalification": True,
                    "paper_only": True,
                    "live_trading_authority": False,
                    "promotion_authority": False,
                }
                proposals.append({**proposal_core, "proposal_digest": _digest(proposal_core)})

    snapshot_schema = str(snapshot["schema_version"])
    core = {
        "schema_version": SCHEMA,
        "source_sha": source_sha,
        "experiment_id": manifest["experiment_id"],
        "dataset_snapshot_sha256": snapshot["snapshot_digest"],
        "snapshot_schema_version": snapshot_schema,
        "snapshot_data_origin": _snapshot_data_origin(snapshot),
        "snapshot_runtime_freshness_claimed": snapshot.get("runtime_freshness_claimed") if snapshot_schema == archive_snapshot.SCHEMA else True,
        "snapshot_as_of_ms": _snapshot_as_of_ms(snapshot),
        "snapshot_history_limit": snapshot["history_limit"],
        "symbols": list(SYMBOLS),
        "timeframes": list(TIMEFRAME_NAMES),
        "families": list(FAMILIES),
        "hypothesis_count": len(TIMEFRAME_NAMES) * len(FAMILIES),
        "selection_policy": "Variant selection is training-only; locked chronological holdout is not used for ranking.",
        "multiplicity_policy": "All 9 family/timeframe hypotheses are reported across all four symbols; no proposal is automatically promoted.",
        "cells": sorted(cells, key=lambda row: (row["timeframe"], row["family"])),
        "research_proposals": sorted(proposals, key=lambda row: (row["timeframe"], row["family"])),
        "research_proposal_count": len(proposals),
        "research_only": True,
        "paper_only": True,
        "live_trading_authority": False,
        "private_credentials_used": False,
        "automatic_strategy_promotion": False,
        "automatic_paper_forward_started": False,
    }
    return {**core, "discovery_digest": _digest(core)}


def verify_discovery(value: Mapping[str, Any]) -> dict[str, Any]:
    checks = {"schema": False, "digest": False, "authority": False, "shape": False, "proposals": False, "snapshot": False}
    try:
        core = dict(value)
        claimed = core.pop("discovery_digest", None)
        checks["schema"] = bool(core.get("schema_version") == SCHEMA and _source_sha(str(core.get("source_sha", ""))) == core.get("source_sha"))
        checks["digest"] = claimed == _digest(core)
        cells = core.get("cells")
        proposals = core.get("research_proposals")
        checks["shape"] = bool(
            core.get("symbols") == list(SYMBOLS)
            and core.get("timeframes") == list(TIMEFRAME_NAMES)
            and core.get("families") == list(FAMILIES)
            and core.get("hypothesis_count") == 9
            and isinstance(cells, list) and len(cells) == 9
            and {(row.get("timeframe"), row.get("family")) for row in cells if isinstance(row, Mapping)}
                == {(timeframe, family) for timeframe in TIMEFRAME_NAMES for family in FAMILIES}
            and isinstance(proposals, list)
            and core.get("research_proposal_count") == len(proposals)
        )
        snapshot_schema = core.get("snapshot_schema_version")
        checks["snapshot"] = bool(
            snapshot_schema in SUPPORTED_SNAPSHOT_SCHEMAS
            and isinstance(core.get("snapshot_as_of_ms"), int)
            and not isinstance(core.get("snapshot_as_of_ms"), bool)
            and int(core.get("snapshot_as_of_ms")) > 0
            and isinstance(core.get("snapshot_history_limit"), int)
            and int(core.get("snapshot_history_limit")) >= 160
            and (
                (
                    snapshot_schema == archive_snapshot.SCHEMA
                    and core.get("snapshot_data_origin") == "official_public_bybit_spot_trade_archive_aggregated"
                    and core.get("snapshot_runtime_freshness_claimed") is False
                )
                or (
                    snapshot_schema == rest_snapshot.SCHEMA
                    and core.get("snapshot_data_origin") == "canonical_public_bybit_rest_closed_candles"
                    and core.get("snapshot_runtime_freshness_claimed") is True
                )
            )
        )
        checks["authority"] = bool(
            core.get("research_only") is True
            and core.get("paper_only") is True
            and core.get("live_trading_authority") is False
            and core.get("private_credentials_used") is False
            and core.get("automatic_strategy_promotion") is False
            and core.get("automatic_paper_forward_started") is False
        )
        checks["proposals"] = bool(
            isinstance(proposals, list)
            and all(
                isinstance(row, Mapping)
                and row.get("proposal_state") == "RESEARCH_PROPOSAL_ONLY"
                and row.get("eligible_symbols") == list(SYMBOLS)
                and row.get("family") in FAMILIES
                and row.get("timeframe") in TIMEFRAME_NAMES
                and row.get("requires_independent_runtime_requalification") is True
                and row.get("promotion_authority") is False
                and row.get("live_trading_authority") is False
                and row.get("paper_only") is True
                and row.get("dataset_snapshot_sha256") == core.get("dataset_snapshot_sha256")
                and row.get("proposal_digest") == _digest({key: item for key, item in row.items() if key != "proposal_digest"})
                for row in proposals
            )
        )
    except Exception:
        pass
    evidence = {
        "schema_version": "nexus.multipair-strategy-discovery-verification.v1",
        "decision": "pass" if all(checks.values()) else "reject",
        "checks": checks,
        "discovery_digest": value.get("discovery_digest"),
    }
    return {**evidence, "verification_digest": _digest(evidence)}


def run(manifest_path: str | Path, output_root: str | Path, *, source_sha: str) -> dict[str, Any]:
    manifest = load_manifest(manifest_path)
    result = discover(manifest, source_sha=source_sha)
    verification = verify_discovery(result)
    if verification["decision"] != "pass":
        raise MultiPairStrategyDiscoveryError("independent multi-pair discovery verification failed")
    output = Path(output_root).resolve()
    legacy._atomic_json(output / "multipair_strategy_discovery.json", result)
    queue_core = {
        "schema_version": "nexus.multipair-strategy-research-proposal-queue.v1",
        "source_discovery_sha": result["source_sha"],
        "source_discovery_digest": result["discovery_digest"],
        "dataset_snapshot_sha256": result["dataset_snapshot_sha256"],
        "symbols": list(SYMBOLS),
        "proposals": result["research_proposals"],
        "research_only": True,
        "paper_only": True,
        "automatic_strategy_promotion": False,
        "live_trading_authority": False,
    }
    queue = {**queue_core, "queue_digest": _digest(queue_core)}
    legacy._atomic_json(output / "research_proposals.json", queue)
    legacy._atomic_json(output / "verification.json", verification)
    return result
