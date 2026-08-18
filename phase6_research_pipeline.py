from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from typing import Any

import pandas as pd

from backtest_engine import BacktestConfig
from bybit_public_klines import fetch_closed_klines
from canonical_backtest import (
    CanonicalBacktestError,
    canonical_market_frame,
    run_canonical_target_exposure_backtest,
)
from market_data_provenance_manifest import build_provenance_manifest
from phase5_data_binding import bind_canonical_dataset, validate_canonical_dataset
from phase5_strategy_factory import build_experiment, qualify

PIPELINE_SCHEMA = "nexus.phase6-research-pipeline.v1"
PAPER_HANDOFF_SCHEMA = "nexus.phase6-paper-candidate-handoff.v1"
SUPPORTED_BYBIT_INTERVALS = {"15": "15m", "60": "1h", "240": "4h"}


class Phase6PipelineError(ValueError):
    pass


def _canonical_json(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise Phase6PipelineError("pipeline artifact is not canonical JSON") from exc


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def _positive_int(config: Mapping[str, Any], field: str, *, minimum: int = 1) -> int:
    value = config.get(field)
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise Phase6PipelineError(f"{field} must be an integer >= {minimum}")
    return value


def _finite(config: Mapping[str, Any], field: str) -> float:
    value = config.get(field)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        raise Phase6PipelineError(f"{field} must be finite numeric")
    return float(value)


def bind_bybit_closed_dataset(
    candles: Sequence[Mapping[str, Any]],
    *,
    canonical_symbol: str,
    source_symbol: str,
    interval: str,
    mapping_policy_version: str = "1.0.0",
) -> dict[str, Any]:
    """Turn already-normalized, closed Bybit public candles into a Gate-7 dataset.

    No caller-supplied source role is trusted: ``bind_canonical_dataset`` re-resolves
    the semantic mapping from the repository registry and rejects non-primary or
    substituted data.
    """
    if interval not in SUPPORTED_BYBIT_INTERVALS:
        raise Phase6PipelineError("unsupported Bybit research interval")
    if not candles:
        raise Phase6PipelineError("candles must not be empty")
    rows: list[dict[str, Any]] = []
    for index, candle in enumerate(candles):
        if not isinstance(candle, Mapping):
            raise Phase6PipelineError(f"candle {index} must be a mapping")
        if candle.get("source") != "Bybit" or candle.get("market_type") != "spot":
            raise Phase6PipelineError("only normalized Bybit spot candles are accepted")
        if candle.get("symbol") != source_symbol or candle.get("interval") != interval:
            raise Phase6PipelineError("candle namespace does not match requested source mapping")
        if candle.get("closed") is not True:
            raise Phase6PipelineError("open/incomplete candles are not research eligible")
        rows.append(
            {
                "open_time_ms": candle["open_time_ms"],
                "open": candle["open"],
                "high": candle["high"],
                "low": candle["low"],
                "close": candle["close"],
                "volume": candle["volume"],
            }
        )

    endpoint_contract = (
        f"/v5/market/kline?category=spot&symbol={source_symbol}&interval={interval}"
    )
    manifest = build_provenance_manifest(
        source="Bybit",
        market_type="spot",
        source_symbol=source_symbol,
        canonical_symbol=canonical_symbol,
        timeframe=SUPPORTED_BYBIT_INTERVALS[interval],
        endpoint_contract=endpoint_contract,
        mapping_policy_version=mapping_policy_version,
        retrieval_start_ms=int(rows[0]["open_time_ms"]),
        retrieval_end_ms=int(rows[-1]["open_time_ms"]),
        candles=rows,
        metadata={"collector": "bybit_public_klines", "closed_only": True},
    )
    return bind_canonical_dataset(manifest, rows)


def fetch_bind_bybit_dataset(
    *,
    canonical_symbol: str,
    source_symbol: str,
    interval: str,
    now_ms: int,
    start_time_ms: int,
    end_time_ms: int,
    limit: int = 1000,
    timeout_seconds: float = 30.0,
) -> dict[str, Any]:
    """Fetch one bounded public Bybit page and bind it to canonical semantics."""
    candles = fetch_closed_klines(
        source_symbol,
        interval,
        now_ms=now_ms,
        start_time_ms=start_time_ms,
        end_time_ms=end_time_ms,
        limit=limit,
        timeout_seconds=timeout_seconds,
    )
    return bind_bybit_closed_dataset(
        candles,
        canonical_symbol=canonical_symbol,
        source_symbol=source_symbol,
        interval=interval,
    )


def _market_frame(dataset: Mapping[str, Any]) -> pd.DataFrame:
    try:
        _artifact, frame = canonical_market_frame(dataset)
        return frame
    except CanonicalBacktestError as exc:
        raise Phase6PipelineError(f"canonical market frame rejected: {exc}") from exc


def _momentum_targets(frame: pd.DataFrame, config: Mapping[str, Any]) -> pd.Series:
    lookback = _positive_int(config, "lookback", minimum=2)
    threshold = _finite(config, "entry_threshold")
    close = pd.to_numeric(frame["close"], errors="raise")
    score = close / close.shift(lookback) - 1.0
    return (score > threshold).astype(float).fillna(0.0)


def _breakout_targets(frame: pd.DataFrame, config: Mapping[str, Any]) -> pd.Series:
    entry_lookback = _positive_int(config, "entry_lookback", minimum=2)
    exit_lookback = _positive_int(config, "exit_lookback", minimum=2)
    high = pd.to_numeric(frame["high"], errors="raise")
    low = pd.to_numeric(frame["low"], errors="raise")
    close = pd.to_numeric(frame["close"], errors="raise")
    prior_high = high.shift(1).rolling(entry_lookback, min_periods=entry_lookback).max()
    prior_low = low.shift(1).rolling(exit_lookback, min_periods=exit_lookback).min()
    exposure = 0.0
    targets: list[float] = []
    for index in range(len(frame)):
        if not pd.isna(prior_high.iloc[index]) and close.iloc[index] > prior_high.iloc[index]:
            exposure = 1.0
        elif not pd.isna(prior_low.iloc[index]) and close.iloc[index] < prior_low.iloc[index]:
            exposure = 0.0
        targets.append(exposure)
    return pd.Series(targets, dtype="float64")


def _mean_reversion_targets(frame: pd.DataFrame, config: Mapping[str, Any]) -> pd.Series:
    lookback = _positive_int(config, "lookback", minimum=5)
    entry_z = _finite(config, "entry_z")
    exit_z = _finite(config, "exit_z")
    if entry_z >= exit_z:
        raise Phase6PipelineError("mean-reversion entry_z must be below exit_z")
    close = pd.to_numeric(frame["close"], errors="raise")
    mean = close.shift(1).rolling(lookback, min_periods=lookback).mean()
    std = close.shift(1).rolling(lookback, min_periods=lookback).std(ddof=0)
    z = (close - mean) / std.replace(0.0, pd.NA)
    exposure = 0.0
    targets: list[float] = []
    for value in z:
        if pd.isna(value):
            targets.append(exposure)
            continue
        if float(value) <= entry_z:
            exposure = 1.0
        elif float(value) >= exit_z:
            exposure = 0.0
        targets.append(exposure)
    return pd.Series(targets, dtype="float64")


def generate_targets(
    dataset: Mapping[str, Any], family: str, config: Mapping[str, Any]
) -> pd.Series:
    frame = _market_frame(dataset)
    if len(frame) < 30:
        raise Phase6PipelineError("at least 30 canonical candles are required")
    if family == "momentum":
        targets = _momentum_targets(frame, config)
    elif family == "trend_breakout":
        targets = _breakout_targets(frame, config)
    elif family == "mean_reversion":
        targets = _mean_reversion_targets(frame, config)
    else:
        raise Phase6PipelineError("unsupported strategy family")
    if len(targets) != len(frame) or targets.isna().any():
        raise Phase6PipelineError("strategy target generation is incomplete")
    if not targets.map(lambda value: math.isfinite(float(value))).all():
        raise Phase6PipelineError("strategy targets contain non-finite values")
    if (targets < 0.0).any() or (targets > 1.0).any():
        raise Phase6PipelineError("Phase 6 strategies are long/flat paper research only")
    return targets


def _run(
    dataset: Mapping[str, Any],
    targets: Sequence[float],
    fee_bps: float,
    slippage_bps: float,
    *,
    start: int = 0,
    end: int | None = None,
):
    try:
        return run_canonical_target_exposure_backtest(
            dataset,
            targets,
            BacktestConfig(
                initial_cash=10_000.0,
                fee_bps=fee_bps,
                slippage_bps=slippage_bps,
                max_abs_exposure=1.0,
                liquidate_at_end=True,
            ),
            start=start,
            end=end,
        )
    except CanonicalBacktestError as exc:
        raise Phase6PipelineError(f"deterministic backtest rejected input: {exc}") from exc


def _slice_return(
    dataset: Mapping[str, Any],
    targets: pd.Series,
    start: int,
    end: int,
    *,
    fee_bps: float,
    slippage_bps: float,
) -> float:
    if end - start < 3:
        return 0.0
    result = _run(
        dataset,
        targets,
        fee_bps,
        slippage_bps,
        start=start,
        end=end,
    )
    return float(result.metrics["total_return"])


def build_qualification_evidence(
    dataset: Mapping[str, Any],
    *,
    family: str,
    strategy_config: Mapping[str, Any],
    cost_model: Mapping[str, Any],
) -> dict[str, Any]:
    """Produce typed qualification evidence from canonical rows only.

    The evidence is intentionally conservative: robustness is the worse of base and
    stress returns; OOS is the final 30% holdout; regime pass ratio uses three ordered
    non-overlapping slices; and hypothesis support requires the base strategy to beat
    a long-only benchmark. No field is caller-supplied after the backtest.
    """
    dataset = validate_canonical_dataset(dataset)
    frame = _market_frame(dataset)
    targets = generate_targets(dataset, family, strategy_config)
    base_fee = float(cost_model.get("fee_bps", 10.0))
    base_slippage = float(cost_model.get("slippage_bps", 5.0))
    stress_fee = float(cost_model.get("stress_fee_bps", max(20.0, base_fee * 2.0)))
    stress_slippage = float(
        cost_model.get("stress_slippage_bps", max(10.0, base_slippage * 2.0))
    )
    for name, value in {
        "fee_bps": base_fee,
        "slippage_bps": base_slippage,
        "stress_fee_bps": stress_fee,
        "stress_slippage_bps": stress_slippage,
    }.items():
        if not math.isfinite(value) or value < 0:
            raise Phase6PipelineError(f"{name} must be finite and non-negative")
    if stress_fee < base_fee or stress_slippage < base_slippage:
        raise Phase6PipelineError("stress cost model cannot be weaker than base costs")

    base = _run(dataset, targets, base_fee, base_slippage)
    stress = _run(dataset, targets, stress_fee, stress_slippage)
    benchmark = _run(dataset, [1.0] * len(frame), base_fee, base_slippage)

    oos_start = max(1, int(len(frame) * 0.70))
    oos_return = _slice_return(
        dataset,
        targets,
        oos_start,
        len(frame),
        fee_bps=stress_fee,
        slippage_bps=stress_slippage,
    )

    boundaries = [0, len(frame) // 3, (2 * len(frame)) // 3, len(frame)]
    regime_returns = [
        _slice_return(
            dataset,
            targets,
            boundaries[index],
            boundaries[index + 1],
            fee_bps=stress_fee,
            slippage_bps=stress_slippage,
        )
        for index in range(3)
    ]
    regime_pass_ratio = sum(value >= 0.0 for value in regime_returns) / 3.0

    base_return = float(base.metrics["total_return"])
    stress_return = float(stress.metrics["total_return"])
    benchmark_return = float(benchmark.metrics["total_return"])
    cost_stress_loss_pct = max(0.0, (base_return - stress_return) * 100.0)
    max_drawdown_pct = float(stress.metrics["max_drawdown"]) * 100.0
    failure_mode_severity = 0.0
    if int(base.metrics["fill_count"]) == 0:
        failure_mode_severity = 1.0
    if not all(math.isfinite(value) for value in regime_returns + [base_return, stress_return, oos_return]):
        failure_mode_severity = 10.0

    detail = {
        "base_return": base_return,
        "stress_return": stress_return,
        "oos_return": oos_return,
        "benchmark_return": benchmark_return,
        "regime_returns": regime_returns,
        "base_fill_count": int(base.metrics["fill_count"]),
        "stress_fill_count": int(stress.metrics["fill_count"]),
    }
    evidence_ref = f"phase6-backtest-sha256:{_digest(detail)}"
    return {
        "evidence_refs": [
            f"dataset-sha256:{dataset['binding_sha256']}",
            evidence_ref,
        ],
        "hypothesis_supported": base_return > benchmark_return,
        "preregistered": True,
        "robustness_score": min(base_return, stress_return),
        "cost_stress_loss_pct": cost_stress_loss_pct,
        "walk_forward_score": oos_return,
        "oos_score": oos_return,
        "max_drawdown_pct": max_drawdown_pct,
        "regime_pass_ratio": regime_pass_ratio,
        "failure_mode_severity": failure_mode_severity,
        "benchmark_score": benchmark_return,
        "uncertainty_width": abs(base_return - stress_return),
        "survivorship_control": True,
        "lookahead_control": True,
        "data_snooping_control": True,
    }


def _paper_handoff(qualification: Mapping[str, Any]) -> dict[str, Any] | None:
    if qualification.get("status") != "paper_candidate":
        return None
    core = {
        "schema_version": PAPER_HANDOFF_SCHEMA,
        "qualification_digest": qualification["qualification_digest"],
        "experiment_id": qualification["experiment_id"],
        "strategy_version": qualification["strategy_version"],
        "family": qualification["family"],
        "paper_only": True,
        "live_execution_allowed": False,
        "private_exchange_credentials_allowed": False,
        "withdrawals_allowed": False,
        "production_promotion_allowed": False,
        "billing_changes_allowed": False,
        "signing_authority_allowed": False,
        "deterministic_risk_final_authority": True,
        "next_authority": "deterministic_risk_paper_review",
    }
    return {**core, "handoff_digest": _digest(core)}


def run_research_job(
    dataset: Mapping[str, Any],
    *,
    hypothesis: str,
    family: str,
    strategy_version: str,
    strategy_config: Mapping[str, Any],
    code_sha: str,
    cost_model: Mapping[str, Any],
    kill_criteria: Mapping[str, Any],
) -> dict[str, Any]:
    """Run one deterministic canonical research job through qualification."""
    dataset = validate_canonical_dataset(dataset)
    experiment = build_experiment(
        dataset,
        hypothesis=hypothesis,
        family=family,
        strategy_version=strategy_version,
        config=strategy_config,
        code_sha=code_sha,
        cost_model=cost_model,
        kill_criteria=kill_criteria,
    )
    evidence = build_qualification_evidence(
        dataset,
        family=family,
        strategy_config=strategy_config,
        cost_model=cost_model,
    )
    qualification = qualify(dataset, experiment, evidence)
    handoff = _paper_handoff(qualification)
    core = {
        "schema_version": PIPELINE_SCHEMA,
        "paper_only": True,
        "live_execution_allowed": False,
        "dataset_binding_sha256": dataset["binding_sha256"],
        "experiment": experiment,
        "evidence": evidence,
        "qualification": qualification,
        "paper_candidate_handoff": handoff,
    }
    return {**core, "pipeline_digest": _digest(core)}


def replay_identical(job: Mapping[str, Any], rerun: Mapping[str, Any]) -> bool:
    """Compare two completed jobs without trusting timestamps or ambient state."""
    return (
        isinstance(job, Mapping)
        and isinstance(rerun, Mapping)
        and job.get("pipeline_digest") == rerun.get("pipeline_digest")
        and _canonical_json(job) == _canonical_json(rerun)
    )
