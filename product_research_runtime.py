from __future__ import annotations

import os
import re
import time
import uuid
from dataclasses import asdict
from datetime import datetime, timezone
from decimal import Decimal, ROUND_DOWN
from pathlib import Path
from typing import Any, Callable, Mapping

import pandas as pd

from automated_signal_pipeline import AutomatedSignalPipelineError, run_automated_signal_pipeline
from backtest_engine import BacktestConfig, run_target_exposure_backtest
from market_data_source_validator import load_and_validate
from phase5_data_binding import REGISTRY_PATH, validate_canonical_dataset
from phase6_research_pipeline import (
    Phase6PipelineError,
    fetch_bind_bybit_dataset,
    generate_targets,
    run_research_job,
)
from product_runtime import (
    PAPER_DEFAULT_FEE_RATE,
    PAPER_DEFAULT_SLIPPAGE_BPS,
    ProductRuntime,
    ProductRuntimeError,
    _json_safe,
    _risk_policy,
    _risk_state,
    serialize_portfolio,
)
from paper_event_store import replay

PRODUCT_RESEARCH_CONTRACT = "nexus.product-research.v1"
PRODUCT_DATA_CONTRACT = "nexus.product-data.v1"
PRODUCT_AUTO_PAPER_CONTRACT = "nexus.product-auto-paper.v1"
_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
TIMEFRAMES = {
    "minute15": {"interval": "15", "manifest": "15m", "step_ms": 900_000},
    "hour1": {"interval": "60", "manifest": "1h", "step_ms": 3_600_000},
    "hour4": {"interval": "240", "manifest": "4h", "step_ms": 14_400_000},
}
STRATEGY_PRESETS: dict[str, dict[str, Any]] = {
    "momentum": {"lookback": 12, "entry_threshold": 0.002},
    "trend_breakout": {"entry_lookback": 20, "exit_lookback": 10},
    "mean_reversion": {"lookback": 20, "entry_z": -1.5, "exit_z": 0.0},
}
COST_MODEL = {
    "fee_bps": 10.0,
    "slippage_bps": 5.0,
    "stress_fee_bps": 25.0,
    "stress_slippage_bps": 15.0,
}
KILL_CRITERIA = {
    "min_robustness_score": -0.02,
    "max_cost_stress_loss_pct": 5.0,
    "min_walk_forward_score": -0.02,
    "min_oos_score": -0.02,
    "max_drawdown_pct": 25.0,
    "min_regime_pass_ratio": 1.0 / 3.0,
    "max_failure_mode_severity": 1.0,
}


class ProductResearchError(RuntimeError):
    pass


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _utc_ms(value: int) -> str:
    return datetime.fromtimestamp(value / 1000, tz=timezone.utc).isoformat().replace("+00:00", "Z")


def _safe_source_sha(value: str | None) -> str:
    candidate = (value or os.environ.get("NEXUS_SOURCE_SHA") or "").strip().lower()
    if not _SHA_RE.fullmatch(candidate):
        raise ProductResearchError("release source SHA is unavailable; research qualification fails closed")
    return candidate


def _registry_path() -> Path:
    return Path(os.environ.get("NEXUS_MARKET_REGISTRY_PATH", str(REGISTRY_PATH)))


def _public_mapping(registry: Mapping[str, Any], symbol: str, timeframe: str) -> tuple[dict[str, Any], dict[str, Any]]:
    tf = TIMEFRAMES.get(timeframe)
    if tf is None:
        raise ProductResearchError("unsupported product timeframe")
    source_symbol = symbol.upper().strip()
    matches: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for raw_mapping in registry.get("mappings", []):
        mapping = dict(raw_mapping)
        if mapping.get("market_category") != "spot" or mapping.get("manifest_timeframe") != tf["manifest"]:
            continue
        sources = [dict(row) for row in mapping.get("sources", []) if row.get("exchange") == "Bybit" and row.get("role") == "primary" and row.get("status") == "compatible"]
        for source in sources:
            if source.get("symbol") == source_symbol:
                matches.append((mapping, source))
    if len(matches) != 1:
        raise ProductResearchError("requested symbol/timeframe has no unique canonical Bybit primary mapping")
    return matches[0]


def _frame(dataset: Mapping[str, Any]) -> pd.DataFrame:
    artifact = validate_canonical_dataset(dataset, registry_path=_registry_path())
    frame = pd.DataFrame(artifact["rows"])
    frame["timestamp"] = pd.to_datetime(frame["open_time_ms"], unit="ms", utc=True)
    return frame[["timestamp", "open", "high", "low", "close"]].copy()


def _clean_number(value: Any) -> float:
    number = float(value)
    if number != number or number in (float("inf"), float("-inf")):
        raise ProductResearchError("non-finite research metric")
    return number


def _serialize_backtest(result: Any, *, curve_points: int = 180, fill_limit: int = 100) -> dict[str, Any]:
    metrics = {key: (_clean_number(value) if isinstance(value, float) else value) for key, value in result.metrics.items()}
    curve = result.equity_curve
    stride = max(1, len(curve) // max(1, curve_points))
    points = []
    for _, row in curve.iloc[::stride].tail(curve_points).iterrows():
        points.append({
            "timestamp": row["timestamp"].isoformat(),
            "equity": _clean_number(row["equity"]),
            "drawdown": _clean_number(row["drawdown"]),
            "exposure": _clean_number(row["net_exposure"]),
        })
    fills = []
    for _, row in result.fills.tail(fill_limit).iterrows():
        fills.append({
            "execution_time": row["execution_time"].isoformat() if hasattr(row["execution_time"], "isoformat") else str(row["execution_time"]),
            "side": str(row["side"]),
            "fill_price": _clean_number(row["fill_price"]),
            "notional": _clean_number(row["notional"]),
            "fee": _clean_number(row["fee"]),
            "reason": str(row["reason"]),
        })
    return {"metrics": metrics, "equity_curve": points, "fills": fills}


class ProductResearchRuntime:
    """Canonical public-data research and deterministic auto-paper service.

    This service does not accept strategy thresholds from the UI. Presets and kill
    criteria are frozen here so an interactive product action cannot silently tune
    around qualification controls. Only a real ``paper_candidate`` can advance to
    the automated deterministic Risk/Paper path.
    """

    def __init__(
        self,
        product_runtime: ProductRuntime,
        *,
        source_sha: str | None = None,
        dataset_fetcher: Callable[..., Mapping[str, Any]] = fetch_bind_bybit_dataset,
        clock_ms: Callable[[], int] | None = None,
    ) -> None:
        self.product_runtime = product_runtime
        self._source_sha_value = source_sha
        self.dataset_fetcher = dataset_fetcher
        self.clock_ms = clock_ms or (lambda: int(time.time() * 1000))
        self._last_research: dict[str, Any] | None = None

    def registry_snapshot(self) -> dict[str, Any]:
        try:
            registry = load_and_validate(_registry_path())
        except Exception as exc:
            raise ProductResearchError(f"canonical market registry unavailable: {exc}") from exc
        rows = []
        for mapping in registry.get("mappings", []):
            sources = []
            for source in mapping.get("sources", []):
                sources.append({
                    "exchange": source.get("exchange"),
                    "role": source.get("role"),
                    "status": source.get("status"),
                    "symbol": source.get("symbol"),
                    "category": source.get("category"),
                })
            rows.append({
                "mapping_id": mapping.get("mapping_id"),
                "canonical_symbol": mapping.get("canonical_symbol"),
                "market_category": mapping.get("market_category"),
                "timeframe": mapping.get("manifest_timeframe"),
                "finality": mapping.get("candle_finality"),
                "sources": sources,
            })
        return {
            "contract_version": PRODUCT_DATA_CONTRACT,
            "registry_version": registry.get("registry_version"),
            "authority": registry.get("authority"),
            "mappings": rows,
            "private_credentials_required": False,
            "paper_only": True,
        }

    def fetch_dataset(self, *, symbol: str, timeframe: str, limit: int = 240) -> dict[str, Any]:
        if isinstance(limit, bool) or not isinstance(limit, int) or not 60 <= limit <= 500:
            raise ProductResearchError("dataset limit must be between 60 and 500")
        registry = load_and_validate(_registry_path())
        mapping, source = _public_mapping(registry, symbol, timeframe)
        spec = TIMEFRAMES[timeframe]
        now_ms = self.clock_ms()
        end_ms = ((now_ms - spec["step_ms"]) // spec["step_ms"]) * spec["step_ms"]
        start_ms = end_ms - (limit - 1) * spec["step_ms"]
        if start_ms < 0:
            raise ProductResearchError("invalid bounded market window")
        try:
            dataset = self.dataset_fetcher(
                canonical_symbol=mapping["canonical_symbol"],
                source_symbol=source["symbol"],
                interval=spec["interval"],
                now_ms=now_ms,
                start_time_ms=start_ms,
                end_time_ms=end_ms,
                limit=limit,
                timeout_seconds=20.0,
            )
            return validate_canonical_dataset(dataset, registry_path=_registry_path())
        except Exception as exc:
            raise ProductResearchError(f"canonical public dataset unavailable: {exc}") from exc

    def run_research(self, *, symbol: str, timeframe: str, family: str, limit: int = 240) -> dict[str, Any]:
        if family not in STRATEGY_PRESETS:
            raise ProductResearchError("unsupported approved strategy family")
        code_sha = _safe_source_sha(self._source_sha_value)
        dataset = self.fetch_dataset(symbol=symbol, timeframe=timeframe, limit=limit)
        config = dict(STRATEGY_PRESETS[family])
        try:
            job = run_research_job(
                dataset,
                hypothesis=f"Preregistered {family} research on canonical closed candles; no profitability claim.",
                family=family,
                strategy_version=f"{family}-product-v1",
                strategy_config=config,
                code_sha=code_sha,
                cost_model=COST_MODEL,
                kill_criteria=KILL_CRITERIA,
            )
            targets = generate_targets(dataset, family, config)
            frame = _frame(dataset)
            backtest = run_target_exposure_backtest(
                frame,
                targets,
                BacktestConfig(initial_cash=10_000.0, fee_bps=COST_MODEL["fee_bps"], slippage_bps=COST_MODEL["slippage_bps"], max_abs_exposure=1.0, liquidate_at_end=True),
            )
        except Exception as exc:
            raise ProductResearchError(f"research qualification failed closed: {exc}") from exc
        last_row = dataset["rows"][-1]
        result = {
            "contract_version": PRODUCT_RESEARCH_CONTRACT,
            "paper_only": True,
            "live_execution_allowed": False,
            "profitability_claim": False,
            "source_sha": code_sha,
            "request": {"symbol": symbol, "timeframe": timeframe, "family": family, "limit": limit},
            "dataset": {
                "binding_sha256": dataset["binding_sha256"],
                "manifest_sha256": dataset["manifest_sha256"],
                "instrument": dataset["instrument"],
                "source": dataset["source"],
                "source_symbol": dataset["source_symbol"],
                "timeframe": dataset["manifest_timeframe"],
                "row_count": dataset["row_count"],
                "first_open_time_ms": dataset["rows"][0]["open_time_ms"],
                "last_open_time_ms": last_row["open_time_ms"],
                "last_close": last_row["close"],
            },
            "strategy_config": config,
            "cost_model": dict(COST_MODEL),
            "kill_criteria": dict(KILL_CRITERIA),
            "qualification": job["qualification"],
            "evidence": job["evidence"],
            "paper_candidate_handoff": job["paper_candidate_handoff"],
            "pipeline_digest": job["pipeline_digest"],
            "latest_target": float(targets.iloc[-1]),
            "backtest": _serialize_backtest(backtest),
            "_dataset": dataset,
        }
        self._last_research = result
        return {key: value for key, value in result.items() if key != "_dataset"}

    def last_research(self) -> dict[str, Any]:
        if self._last_research is None:
            return {"contract_version": PRODUCT_RESEARCH_CONTRACT, "status": "no_research_run", "paper_only": True}
        return {key: value for key, value in self._last_research.items() if key != "_dataset"}

    def _regime(self, dataset: Mapping[str, Any]) -> tuple[str, str]:
        closes = [Decimal(str(row["close"])) for row in dataset["rows"][-21:]]
        if len(closes) < 2 or closes[0] <= 0:
            return "neutral", "0.50"
        change = closes[-1] / closes[0] - Decimal("1")
        if change >= Decimal("0.02"):
            return "bullish", "0.80"
        if change <= Decimal("-0.02"):
            return "bearish", "0.80"
        return "neutral", "0.60"

    def auto_paper(self) -> dict[str, Any]:
        research = self._last_research
        if research is None:
            raise ProductResearchError("run canonical research before automated Paper")
        qualification = research["qualification"]
        if qualification.get("status") != "paper_candidate":
            return {
                "contract_version": PRODUCT_AUTO_PAPER_CONTRACT,
                "paper_only": True,
                "accepted": False,
                "status": "qualification_killed",
                "kill_reasons": qualification.get("kill_reasons", []),
            }
        if float(research.get("latest_target", 0.0)) <= 0.0:
            return {"contract_version": PRODUCT_AUTO_PAPER_CONTRACT, "paper_only": True, "accepted": False, "status": "no_open_signal"}

        dataset = research["_dataset"]
        family = research["request"]["family"]
        strategy_version = qualification["strategy_version"]
        source_ms = int(dataset["rows"][-1]["open_time_ms"])
        source_time = _utc_ms(source_ms)
        occurred_at = _utc_now()
        dataset_id = f"canonical:{dataset['mapping_id']}"
        dataset_revision = dataset["binding_sha256"]
        regime_label, regime_confidence = self._regime(dataset)
        regime_id = f"regime:{dataset_revision[:20]}:{regime_label}"
        correlation_id = f"auto-paper:{uuid.uuid4().hex}"
        portfolio = self.product_runtime.paper_snapshot()["account"]
        if any(row["symbol"] == research["request"]["symbol"] for row in portfolio.get("positions", [])):
            return {"contract_version": PRODUCT_AUTO_PAPER_CONTRACT, "paper_only": True, "accepted": False, "status": "position_exists"}
        equity = Decimal(str(portfolio["equity"]))
        price = Decimal(str(dataset["rows"][-1]["close"]))
        notional = max(equity * Decimal("0.05"), Decimal("0"))
        quantity = (notional / price).quantize(Decimal("0.00000001"), rounding=ROUND_DOWN)
        if quantity <= 0:
            raise ProductResearchError("auto-paper sizing produced zero quantity")
        stop = price * Decimal("0.985")
        target = price * Decimal("1.03")
        dataset_artifact = {
            "dataset_id": dataset_id,
            "dataset_revision": dataset_revision,
            "source_id": "Bybit",
            "source_timestamp": source_time,
            "received_timestamp": occurred_at,
            "symbol": research["request"]["symbol"],
            "timeframe": research["request"]["timeframe"],
            "readiness_status": "ready",
            "provenance_digest": dataset["manifest_sha256"],
        }
        qualification_artifact = {
            "artifact_id": qualification["experiment_id"],
            "artifact_digest": qualification["qualification_digest"],
            "strategy_id": family,
            "strategy_version": strategy_version,
            "dataset_id": dataset_id,
            "dataset_revision": dataset_revision,
            "status": "paper_eligible",
            "qualified_at": occurred_at,
        }
        regime_artifact = {
            "regime_id": regime_id,
            "regime_version": "product-regime-v1",
            "label": regime_label,
            "confidence": regime_confidence,
            "source_timestamp": source_time,
            "dataset_id": dataset_id,
            "dataset_revision": dataset_revision,
            "symbol": research["request"]["symbol"],
            "timeframe": research["request"]["timeframe"],
        }
        decision = {
            "decision_id": f"decision:{uuid.uuid4().hex}",
            "operation": "open",
            "side": "long",
            "quantity": str(quantity),
            "reference_price": str(price),
            "stop_price": str(stop),
            "target_price": str(target),
            "confidence": regime_confidence,
            "strategy_id": family,
            "strategy_version": strategy_version,
            "dataset_id": dataset_id,
            "dataset_revision": dataset_revision,
            "regime_id": regime_id,
            "regime_version": "product-regime-v1",
            "symbol": research["request"]["symbol"],
            "timeframe": research["request"]["timeframe"],
            "source_timestamp": source_time,
            "correlation_id": correlation_id,
            "causation_id": regime_id,
            "risk_policy_version": "1.0.0",
        }
        policy = _risk_policy()
        policy["eligible_strategies"] = [{"id": family, "version": strategy_version}]
        try:
            with self.product_runtime._lock:
                existing = self.product_runtime._ensure_account()
                state = replay(existing).state
                result = run_automated_signal_pipeline(
                    dataset=dataset_artifact,
                    qualification=qualification_artifact,
                    regime=regime_artifact,
                    decision=decision,
                    risk_state=_risk_state(state, symbol=research["request"]["symbol"]),
                    risk_policy=policy,
                    portfolio_state=state,
                    occurred_at=occurred_at,
                    fee_rate=PAPER_DEFAULT_FEE_RATE,
                    slippage_bps=PAPER_DEFAULT_SLIPPAGE_BPS,
                )
                self.product_runtime._write_events([*existing, *result.events])
        except (AutomatedSignalPipelineError, ProductRuntimeError, Exception) as exc:
            raise ProductResearchError(f"automated Paper pipeline failed closed: {exc}") from exc
        return {
            "contract_version": PRODUCT_AUTO_PAPER_CONTRACT,
            "paper_only": True,
            "accepted": bool(result.risk_decision.allowed and result.execution is not None),
            "status": "paper_executed" if result.execution is not None else "risk_rejected",
            "dataset": dataset_artifact,
            "qualification": qualification_artifact,
            "regime": regime_artifact,
            "decision": decision,
            "signal": dict(result.signal),
            "risk": _json_safe(asdict(result.risk_decision)),
            "execution": None if result.execution is None else {
                "fill_price": str(result.execution.fill_price),
                "fee": str(result.execution.fee),
                "slippage_cost": str(result.execution.slippage_cost),
                "realized_pnl": str(result.execution.realized_pnl),
                "event_count": len(result.execution.events),
            },
            "account": serialize_portfolio(result.state),
            "live_trading_authority": False,
        }
