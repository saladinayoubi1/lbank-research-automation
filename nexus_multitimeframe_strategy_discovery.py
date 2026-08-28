"""Leakage-resistant multi-timeframe strategy discovery over immutable Bybit history.

This module searches only bounded, preregistered variants of the three strategy
families already executable by the NEXUS Demo runtime. Variant selection uses
training data only. The locked chronological holdout is evaluated after selection
and can produce a RESEARCH_PROPOSAL only; it cannot create Candidate/Paper state,
execute trades, use private credentials, or grant Live/L4 authority.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
from statistics import median
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

SCHEMA = "nexus.multitimeframe-strategy-discovery.v1"
MANIFEST_SCHEMA = "nexus.multitimeframe-strategy-discovery-manifest.v1"
APPROVED_SYMBOLS = ("BTCUSDT", "ETHUSDT")
APPROVED_TIMEFRAMES = ("minute15", "hour1", "hour4")
APPROVED_FAMILIES = ("momentum", "trend_breakout", "mean_reversion")
REQUIRED_COLUMNS = ["timestamp", "open", "high", "low", "close", "volume", "symbol", "timeframe"]
TIMEFRAME_STEP_MS = {"minute15": 900_000, "hour1": 3_600_000, "hour4": 14_400_000}
TIMEFRAME_BARS_PER_YEAR = {
    "minute15": 365.25 * 96.0,
    "hour1": 365.25 * 24.0,
    "hour4": 365.25 * 6.0,
}


class MultiTimeframeDiscoveryError(RuntimeError):
    pass


def _canonical(value: Any) -> bytes:
    try:
        return json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise MultiTimeframeDiscoveryError("discovery evidence is not canonical JSON") from exc


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _source_sha(value: str) -> str:
    normalized = str(value).strip().lower()
    if (
        len(normalized) != 40
        or any(character not in "0123456789abcdef" for character in normalized)
    ):
        raise MultiTimeframeDiscoveryError("source_sha must be an exact Git SHA")
    return normalized


def _atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    target = Path(path).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + f".{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(dict(value), indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, target)


def _gate_fields() -> set[str]:
    return {
        "minimum_positive_ratio", "minimum_median_return", "minimum_worst_return",
        "maximum_drawdown", "minimum_median_sharpe", "minimum_sharpe", "minimum_fill_count",
    }


def _validate_gate(gate: Mapping[str, Any]) -> None:
    if not isinstance(gate, Mapping) or set(gate) != _gate_fields():
        raise MultiTimeframeDiscoveryError("gate schema mismatch")
    for key, value in gate.items():
        if key == "minimum_fill_count":
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise MultiTimeframeDiscoveryError("gate minimum_fill_count is invalid")
        elif isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
            raise MultiTimeframeDiscoveryError(f"gate {key} is invalid")
    if not 0.0 <= float(gate["minimum_positive_ratio"]) <= 1.0:
        raise MultiTimeframeDiscoveryError("gate positive ratio is invalid")
    if float(gate["maximum_drawdown"]) < 0.0:
        raise MultiTimeframeDiscoveryError("gate drawdown is invalid")


def _variant_id(family: str, config: Mapping[str, Any]) -> str:
    return _digest({"family": family, "config": dict(config)})[:16]


def load_manifest(path: str | Path) -> dict[str, Any]:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise MultiTimeframeDiscoveryError("discovery manifest is unavailable") from exc
    required = {
        "schema_version", "experiment_id", "dataset", "symbols", "timeframes", "families",
        "train_fraction", "execution", "gates", "variants", "authority",
    }
    if not isinstance(value, dict) or set(value) != required or value.get("schema_version") != MANIFEST_SCHEMA:
        raise MultiTimeframeDiscoveryError("discovery manifest schema mismatch")
    if tuple(value.get("symbols", ())) != APPROVED_SYMBOLS:
        raise MultiTimeframeDiscoveryError("discovery symbols must be the approved BTC/ETH pair")
    if tuple(value.get("timeframes", ())) != APPROVED_TIMEFRAMES:
        raise MultiTimeframeDiscoveryError("discovery timeframes must be 15m/1h/4h")
    if tuple(value.get("families", ())) != APPROVED_FAMILIES:
        raise MultiTimeframeDiscoveryError("discovery families must match the Demo runtime")
    fraction = value.get("train_fraction")
    if isinstance(fraction, bool) or not isinstance(fraction, (int, float)) or not 0.55 <= float(fraction) <= 0.8:
        raise MultiTimeframeDiscoveryError("train_fraction is outside the preregistered range")
    dataset = value.get("dataset")
    if not isinstance(dataset, dict) or set(dataset) != {"dataset_root", "archive_sha256"}:
        raise MultiTimeframeDiscoveryError("dataset contract mismatch")
    archive_sha = dataset.get("archive_sha256")
    if not isinstance(archive_sha, str) or len(archive_sha) != 64 or any(ch not in "0123456789abcdef" for ch in archive_sha):
        raise MultiTimeframeDiscoveryError("dataset archive digest is invalid")
    authority = value.get("authority")
    if authority != {
        "research_only": True,
        "paper_only": True,
        "live_trading_authority": False,
        "private_credentials_allowed": False,
        "automatic_strategy_promotion": False,
    }:
        raise MultiTimeframeDiscoveryError("discovery authority boundary mismatch")
    execution = value.get("execution")
    if not isinstance(execution, dict) or set(execution) != {"conservative", "stress"}:
        raise MultiTimeframeDiscoveryError("execution profiles mismatch")
    for profile in ("conservative", "stress"):
        row = execution.get(profile)
        if not isinstance(row, dict) or set(row) != {"fee_bps", "slippage_bps"}:
            raise MultiTimeframeDiscoveryError("execution profile mismatch")
        if any(
            isinstance(row[key], bool)
            or not isinstance(row[key], (int, float))
            or not math.isfinite(float(row[key]))
            or float(row[key]) < 0
            for key in row
        ):
            raise MultiTimeframeDiscoveryError("execution profile is invalid")
    gates = value.get("gates")
    if not isinstance(gates, dict) or set(gates) != {"training", "locked"}:
        raise MultiTimeframeDiscoveryError("discovery gates mismatch")
    for gate in gates.values():
        _validate_gate(gate)
    variants = value.get("variants")
    if not isinstance(variants, dict) or set(variants) != set(APPROVED_FAMILIES):
        raise MultiTimeframeDiscoveryError("variant families are invalid")
    for family in APPROVED_FAMILIES:
        rows = variants.get(family)
        if not isinstance(rows, list) or not 2 <= len(rows) <= 24 or any(not isinstance(row, dict) for row in rows):
            raise MultiTimeframeDiscoveryError("variant grid is missing or unbounded")
        ids = [_variant_id(family, row) for row in rows]
        if len(ids) != len(set(ids)):
            raise MultiTimeframeDiscoveryError("variant grid contains duplicates")
    return value


def load_frame(root: Path, symbol: str, timeframe: str) -> pd.DataFrame:
    if symbol not in APPROVED_SYMBOLS or timeframe not in APPROVED_TIMEFRAMES:
        raise MultiTimeframeDiscoveryError("archive request is outside approved discovery scope")
    path = Path(root) / "bybit_market" / symbol / f"{timeframe}.parquet"
    if path.is_symlink() or not path.is_file():
        raise MultiTimeframeDiscoveryError(f"immutable archive frame missing: {symbol}/{timeframe}")
    frame = pd.read_parquet(path)
    if frame.columns.tolist() != REQUIRED_COLUMNS:
        raise MultiTimeframeDiscoveryError(f"archive schema mismatch: {symbol}/{timeframe}")
    frame = frame.copy()
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True)
    frame = frame.sort_values("timestamp").reset_index(drop=True)
    if len(frame) < 160 or frame["timestamp"].duplicated().any() or not frame["timestamp"].is_monotonic_increasing:
        raise MultiTimeframeDiscoveryError(f"archive history is insufficient or non-monotonic: {symbol}/{timeframe}")
    expected_step = pd.Timedelta(milliseconds=TIMEFRAME_STEP_MS[timeframe])
    deltas = frame["timestamp"].diff().iloc[1:]
    if len(deltas) != len(frame) - 1 or not bool((deltas == expected_step).all()):
        raise MultiTimeframeDiscoveryError(f"archive cadence is not gap-free: {symbol}/{timeframe}")
    if set(frame["symbol"].astype(str)) != {symbol} or set(frame["timeframe"].astype(str)) != {timeframe}:
        raise MultiTimeframeDiscoveryError(f"archive identity mismatch: {symbol}/{timeframe}")
    numeric = frame[["open", "high", "low", "close", "volume"]].astype(float)
    if (
        not np.isfinite(numeric.to_numpy()).all()
        or (numeric[["open", "high", "low", "close"]] <= 0).any().any()
        or (numeric["volume"] < 0).any()
    ):
        raise MultiTimeframeDiscoveryError(f"archive contains invalid market values: {symbol}/{timeframe}")
    return frame


def _positive_int(config: Mapping[str, Any], field: str, minimum: int) -> int:
    value = config.get(field)
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise MultiTimeframeDiscoveryError(f"{field} is invalid")
    return value


def _finite(config: Mapping[str, Any], field: str) -> float:
    value = config.get(field)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        raise MultiTimeframeDiscoveryError(f"{field} is invalid")
    return float(value)


def generate_targets(frame: pd.DataFrame, family: str, config: Mapping[str, Any]) -> pd.Series:
    close = frame["close"].astype(float)
    if family == "momentum":
        if set(config) != {"lookback", "entry_threshold"}:
            raise MultiTimeframeDiscoveryError("momentum variant schema mismatch")
        lookback = _positive_int(config, "lookback", 2)
        threshold = _finite(config, "entry_threshold")
        score = close / close.shift(lookback) - 1.0
        target = (score > threshold).astype(float).fillna(0.0)
    elif family == "trend_breakout":
        if set(config) != {"entry_lookback", "exit_lookback"}:
            raise MultiTimeframeDiscoveryError("breakout variant schema mismatch")
        entry = _positive_int(config, "entry_lookback", 2)
        exit_ = _positive_int(config, "exit_lookback", 2)
        if exit_ >= entry:
            raise MultiTimeframeDiscoveryError("breakout exit lookback must be shorter than entry lookback")
        prior_high = frame["high"].astype(float).shift(1).rolling(entry, min_periods=entry).max()
        prior_low = frame["low"].astype(float).shift(1).rolling(exit_, min_periods=exit_).min()
        state = 0.0
        values: list[float] = []
        for index in range(len(frame)):
            if not pd.isna(prior_high.iloc[index]) and close.iloc[index] > prior_high.iloc[index]:
                state = 1.0
            elif not pd.isna(prior_low.iloc[index]) and close.iloc[index] < prior_low.iloc[index]:
                state = 0.0
            values.append(state)
        target = pd.Series(values, dtype="float64")
    elif family == "mean_reversion":
        if set(config) != {"lookback", "entry_z", "exit_z"}:
            raise MultiTimeframeDiscoveryError("mean-reversion variant schema mismatch")
        lookback = _positive_int(config, "lookback", 5)
        entry_z = _finite(config, "entry_z")
        exit_z = _finite(config, "exit_z")
        if entry_z >= exit_z:
            raise MultiTimeframeDiscoveryError("mean-reversion entry must be below exit")
        mean = close.shift(1).rolling(lookback, min_periods=lookback).mean()
        std = close.shift(1).rolling(lookback, min_periods=lookback).std(ddof=0).replace(0.0, np.nan)
        zscore = (close - mean) / std
        state = 0.0
        values = []
        for value in zscore:
            if not pd.isna(value):
                if float(value) <= entry_z:
                    state = 1.0
                elif float(value) >= exit_z:
                    state = 0.0
            values.append(state)
        target = pd.Series(values, dtype="float64")
    else:
        raise MultiTimeframeDiscoveryError("unsupported strategy family")
    if len(target) != len(frame) or target.isna().any() or not target.map(lambda x: math.isfinite(float(x))).all():
        raise MultiTimeframeDiscoveryError("target generation failed")
    if (target < 0).any() or (target > 1).any():
        raise MultiTimeframeDiscoveryError("discovery targets must remain long/flat")
    return target


def _simulate(
    frame: pd.DataFrame,
    target: pd.Series,
    start: int,
    end: int,
    profile: Mapping[str, Any],
    *,
    bars_per_year: float,
) -> dict[str, Any]:
    if not 0 <= start < end <= len(frame) or end - start < 20:
        raise MultiTimeframeDiscoveryError("evaluation slice is invalid")
    if not math.isfinite(float(bars_per_year)) or float(bars_per_year) <= 0:
        raise MultiTimeframeDiscoveryError("annualization factor is invalid")
    fee_rate = float(profile["fee_bps"]) / 10000.0
    slippage = float(profile["slippage_bps"]) / 10000.0
    cash = 10_000.0
    qty = 0.0
    equity: list[float] = []
    fills = 0
    turnover = 0.0
    sliced = frame.iloc[start:end].reset_index(drop=True)
    desired = target.iloc[start:end].reset_index(drop=True).astype(float).to_numpy()
    for index, row in sliced.iterrows():
        if index > 0:
            reference = float(row["open"])
            equity_open = cash + qty * reference
            wanted_qty = equity_open * desired[index - 1] / reference
            delta = wanted_qty - qty
            if abs(delta) > 1e-12:
                fill = reference * (1.0 + slippage if delta > 0 else 1.0 - slippage)
                notional = abs(delta * fill)
                cash -= delta * fill + notional * fee_rate
                qty += delta
                fills += 1
                turnover += notional / 10_000.0
        equity.append(cash + qty * float(row["close"]))
    if abs(qty) > 1e-12:
        reference = float(sliced.iloc[-1]["close"])
        delta = -qty
        fill = reference * (1.0 + slippage if delta > 0 else 1.0 - slippage)
        notional = abs(delta * fill)
        cash -= delta * fill + notional * fee_rate
        qty = 0.0
        fills += 1
        turnover += notional / 10_000.0
        equity[-1] = cash
    curve = np.asarray(equity, dtype=float)
    if not np.isfinite(curve).all() or np.any(curve <= 0):
        raise MultiTimeframeDiscoveryError("evaluation equity became invalid")
    returns = pd.Series(curve).pct_change().replace([np.inf, -np.inf], np.nan).dropna().to_numpy(float)
    running_max = np.maximum.accumulate(curve)
    drawdown = curve / running_max - 1.0
    std = float(np.std(returns, ddof=0)) if len(returns) else 0.0
    sharpe = float(np.mean(returns) / std * math.sqrt(float(bars_per_year))) if std > 0 else 0.0
    total_return = float(curve[-1] / 10_000.0 - 1.0)
    max_drawdown = float(-drawdown.min())
    score = sharpe + 1.5 * total_return - 1.25 * max_drawdown - 0.002 * turnover
    return {
        "total_return": total_return,
        "max_drawdown": max_drawdown,
        "sharpe": sharpe,
        "fill_count": fills,
        "turnover": turnover,
        "score": score,
    }


def _aggregate(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    if not rows:
        raise MultiTimeframeDiscoveryError("evaluation produced no rows")
    returns = [float(row["total_return"]) for row in rows]
    drawdowns = [float(row["max_drawdown"]) for row in rows]
    sharpes = [float(row["sharpe"]) for row in rows]
    fills = [int(row["fill_count"]) for row in rows]
    turnovers = [float(row["turnover"]) for row in rows]
    scores = [float(row["score"]) for row in rows]
    return {
        "count": len(rows),
        "positive_ratio": sum(value > 0 for value in returns) / len(returns),
        "median_return": float(median(returns)),
        "worst_return": float(min(returns)),
        "worst_drawdown": float(max(drawdowns)),
        "median_sharpe": float(median(sharpes)),
        "minimum_sharpe": float(min(sharpes)),
        "minimum_fill_count": int(min(fills)),
        "median_turnover": float(median(turnovers)),
        "score": float(median(scores)),
    }


def _gate(summary: Mapping[str, Any], gate: Mapping[str, Any]) -> dict[str, bool]:
    _validate_gate(gate)
    return {
        "positive_ratio": float(summary["positive_ratio"]) >= float(gate["minimum_positive_ratio"]),
        "median_return": float(summary["median_return"]) >= float(gate["minimum_median_return"]),
        "worst_return": float(summary["worst_return"]) >= float(gate["minimum_worst_return"]),
        "drawdown": float(summary["worst_drawdown"]) <= float(gate["maximum_drawdown"]),
        "median_sharpe": float(summary["median_sharpe"]) >= float(gate["minimum_median_sharpe"]),
        "minimum_sharpe": float(summary["minimum_sharpe"]) >= float(gate["minimum_sharpe"]),
        "fills": int(summary["minimum_fill_count"]) >= int(gate["minimum_fill_count"]),
    }


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
    if timeframe not in TIMEFRAME_BARS_PER_YEAR:
        raise MultiTimeframeDiscoveryError("unsupported evaluation timeframe")
    rows: list[dict[str, Any]] = []
    for symbol in APPROVED_SYMBOLS:
        frame = frames[symbol]
        target = generate_targets(frame, family, config)
        metric = _simulate(
            frame,
            target,
            start_by_symbol[symbol],
            end_by_symbol[symbol],
            profile,
            bars_per_year=TIMEFRAME_BARS_PER_YEAR[timeframe],
        )
        rows.append({"symbol": symbol, **metric})
    return _aggregate(rows), rows


def _validate_pair_alignment(frames: Mapping[str, pd.DataFrame], timeframe: str) -> None:
    if set(frames) != set(APPROVED_SYMBOLS):
        raise MultiTimeframeDiscoveryError("archive pair surface is incomplete")
    btc = frames["BTCUSDT"]["timestamp"].reset_index(drop=True)
    eth = frames["ETHUSDT"]["timestamp"].reset_index(drop=True)
    if not btc.equals(eth):
        raise MultiTimeframeDiscoveryError(f"BTC/ETH archive timestamps are not aligned: {timeframe}")


def discover(manifest: Mapping[str, Any], *, source_sha: str) -> dict[str, Any]:
    source_sha = _source_sha(source_sha)
    root = Path(manifest["dataset"]["dataset_root"])
    fraction = float(manifest["train_fraction"])
    cells: list[dict[str, Any]] = []
    proposals: list[dict[str, Any]] = []
    hypothesis_count = len(APPROVED_TIMEFRAMES) * len(APPROVED_FAMILIES)

    for timeframe in APPROVED_TIMEFRAMES:
        frames = {symbol: load_frame(root, symbol, timeframe) for symbol in APPROVED_SYMBOLS}
        _validate_pair_alignment(frames, timeframe)
        split = {
            symbol: max(80, min(len(frame) - 40, int(len(frame) * fraction)))
            for symbol, frame in frames.items()
        }
        train_start = {symbol: 0 for symbol in APPROVED_SYMBOLS}
        train_end = split
        locked_start = split
        locked_end = {symbol: len(frame) for symbol, frame in frames.items()}
        for family in APPROVED_FAMILIES:
            training_rows: list[dict[str, Any]] = []
            for config in manifest["variants"][family]:
                summary, _rows = _evaluate_variant(
                    frames,
                    family,
                    config,
                    train_start,
                    train_end,
                    manifest["execution"]["conservative"],
                    timeframe=timeframe,
                )
                checks = _gate(summary, manifest["gates"]["training"])
                training_rows.append({
                    "variant_id": _variant_id(family, config),
                    "config": dict(config),
                    "summary": summary,
                    "gate_checks": checks,
                    "passes_training_gate": all(checks.values()),
                })
            training_rows.sort(key=lambda row: (-float(row["summary"]["score"]), row["variant_id"]))
            training_passers = [row for row in training_rows if row["passes_training_gate"]]
            selected = (training_passers or training_rows)[0]
            locked_profiles: dict[str, Any] = {}
            locked_pass = True
            for profile_name in ("conservative", "stress"):
                summary, per_symbol = _evaluate_variant(
                    frames,
                    family,
                    selected["config"],
                    locked_start,
                    locked_end,
                    manifest["execution"][profile_name],
                    timeframe=timeframe,
                )
                checks = _gate(summary, manifest["gates"]["locked"])
                locked_profiles[profile_name] = {
                    "summary": summary,
                    "per_symbol": per_symbol,
                    "gate_checks": checks,
                    "passes": all(checks.values()),
                }
                locked_pass = locked_pass and all(checks.values())
            proposal_eligible = bool(selected["passes_training_gate"] and locked_pass)
            cell_core = {
                "timeframe": timeframe,
                "family": family,
                "variant_count": len(training_rows),
                "training_gate_passers": len(training_passers),
                "selected_variant_id": selected["variant_id"],
                "selected_config": selected["config"],
                "selection_source": "training_only",
                "training_summary": selected["summary"],
                "locked_profiles": locked_profiles,
                "proposal_eligible": proposal_eligible,
                "automatic_candidate_created": False,
                "automatic_paper_forward_started": False,
                "live_trading_enabled": False,
            }
            cell = {**cell_core, "cell_digest": _digest(cell_core)}
            cells.append(cell)
            if proposal_eligible:
                proposal_core = {
                    "proposal_state": "RESEARCH_PROPOSAL",
                    "family": family,
                    "timeframe": timeframe,
                    "strategy_config": selected["config"],
                    "variant_id": selected["variant_id"],
                    "cell_digest": cell["cell_digest"],
                    "dataset_archive_sha256": manifest["dataset"]["archive_sha256"],
                    "requires_independent_runtime_requalification": True,
                    "paper_only": True,
                    "live_trading_authority": False,
                    "promotion_authority": False,
                }
                proposals.append({**proposal_core, "proposal_digest": _digest(proposal_core)})

    core = {
        "schema_version": SCHEMA,
        "source_sha": source_sha,
        "experiment_id": manifest["experiment_id"],
        "dataset_archive_sha256": manifest["dataset"]["archive_sha256"],
        "symbols": list(APPROVED_SYMBOLS),
        "timeframes": list(APPROVED_TIMEFRAMES),
        "families": list(APPROVED_FAMILIES),
        "hypothesis_count": hypothesis_count,
        "selection_policy": "Variant selection is training-only; the locked chronological holdout is not used for ranking.",
        "multiplicity_policy": "All 9 family/timeframe hypotheses are reported; no discovered proposal is automatically promoted.",
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
    checks = {"schema": False, "digest": False, "authority": False, "shape": False, "proposals": False}
    try:
        core = dict(value)
        claimed = core.pop("discovery_digest", None)
        checks["schema"] = bool(
            core.get("schema_version") == SCHEMA
            and _source_sha(str(core.get("source_sha", ""))) == core.get("source_sha")
        )
        checks["digest"] = isinstance(claimed, str) and claimed == _digest(core)
        cells = core.get("cells")
        proposals = core.get("research_proposals")
        checks["shape"] = bool(
            isinstance(cells, list)
            and len(cells) == 9
            and {(row.get("timeframe"), row.get("family")) for row in cells if isinstance(row, Mapping)}
            == {(timeframe, family) for timeframe in APPROVED_TIMEFRAMES for family in APPROVED_FAMILIES}
            and isinstance(proposals, list)
            and core.get("research_proposal_count") == len(proposals)
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
                and row.get("proposal_state") == "RESEARCH_PROPOSAL"
                and row.get("family") in APPROVED_FAMILIES
                and row.get("timeframe") in APPROVED_TIMEFRAMES
                and row.get("requires_independent_runtime_requalification") is True
                and row.get("promotion_authority") is False
                and row.get("live_trading_authority") is False
                and row.get("paper_only") is True
                and row.get("proposal_digest")
                == _digest({key: item for key, item in row.items() if key != "proposal_digest"})
                for row in proposals
            )
        )
    except Exception:
        pass
    decision = "pass" if all(checks.values()) else "reject"
    evidence = {
        "schema_version": "nexus.multitimeframe-strategy-discovery-verification.v1",
        "decision": decision,
        "checks": checks,
        "discovery_digest": value.get("discovery_digest"),
    }
    return {**evidence, "verification_digest": _digest(evidence)}


def run(
    manifest_path: str | Path,
    output_root: str | Path,
    *,
    source_sha: str,
) -> dict[str, Any]:
    manifest = load_manifest(manifest_path)
    result = discover(manifest, source_sha=source_sha)
    verification = verify_discovery(result)
    if verification["decision"] != "pass":
        raise MultiTimeframeDiscoveryError("independent discovery verification failed")
    output = Path(output_root)
    _atomic_json(output / "multitimeframe_strategy_discovery.json", result)
    _atomic_json(output / "verification.json", verification)
    _atomic_json(output / "research_proposals.json", {
        "schema_version": "nexus.strategy-research-proposal-queue.v1",
        "source_discovery_sha": result["source_sha"],
        "source_discovery_digest": result["discovery_digest"],
        "proposals": result["research_proposals"],
        "automatic_strategy_promotion": False,
        "live_trading_authority": False,
    })
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--manifest", type=Path,
        default=Path("experiments/nexus_multitimeframe_strategy_discovery_v1.json"),
    )
    parser.add_argument(
        "--output", type=Path,
        default=Path("build/nexus_multitimeframe_strategy_discovery"),
    )
    parser.add_argument("--source-sha", required=True)
    args = parser.parse_args()
    result = run(args.manifest, args.output, source_sha=args.source_sha)
    print(json.dumps({
        "research_proposal_count": result["research_proposal_count"],
        "discovery_digest": result["discovery_digest"],
        "automatic_strategy_promotion": False,
        "live_trading_authority": False,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
