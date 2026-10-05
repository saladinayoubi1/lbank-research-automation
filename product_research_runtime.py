from __future__ import annotations

import hashlib
import json
import os
import re
import time
import uuid
from dataclasses import asdict
from datetime import datetime, timezone
from decimal import Decimal, ROUND_DOWN
from pathlib import Path
from typing import Any, Callable, Mapping

from automated_signal_pipeline import run_automated_signal_pipeline
from backtest_engine import BacktestConfig
from canonical_backtest import run_canonical_target_exposure_backtest
from market_data_source_validator import load_and_validate
from phase5_data_binding import REGISTRY_PATH, validate_canonical_dataset
from phase5_strategy_factory import qualify
from phase6_research_pipeline import fetch_bind_bybit_dataset, generate_targets, run_research_job
from strategy_lifecycle import build_research_lifecycle, promote_candidate_to_paper
from strategy_registry import build_strategy_record
from product_runtime import (
    PAPER_DEFAULT_FEE_RATE,
    PAPER_DEFAULT_SLIPPAGE_BPS,
    ProductRuntime,
    _json_safe,
    _risk_policy,
    _risk_state,
    _session_signal_count,
    serialize_portfolio,
)
from paper_event_store import replay

PRODUCT_RESEARCH_CONTRACT = "nexus.product-research.v1"
PRODUCT_DATA_CONTRACT = "nexus.product-data.v1"
PRODUCT_AUTO_PAPER_CONTRACT = "nexus.product-auto-paper.v1"
PRODUCT_INDEPENDENT_QA_CONTRACT = "nexus.product-independent-qa.v1"
_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
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
COST_MODEL = {"fee_bps": 10.0, "slippage_bps": 5.0, "stress_fee_bps": 25.0, "stress_slippage_bps": 15.0}
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


def _canonical_digest(value: Any) -> str:
    try:
        payload = json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ProductResearchError("independent QA evidence is not canonical") from exc
    return hashlib.sha256(payload).hexdigest()


def _qa_identifier(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 128:
        raise ProductResearchError(f"{field} must be a bounded non-empty identifier")
    return value


def _qa_sha256(value: Any, field: str) -> str:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value.lower()):
        raise ProductResearchError(f"{field} must be a SHA-256 digest")
    return value.lower()


def _validate_independent_qa_receipt(
    value: Any, *, research: Mapping[str, Any]
) -> dict[str, Any]:
    expected = {
        "contract_version",
        "strategy_record_digest",
        "qualification_digest",
        "source_sha",
        "producer_id",
        "verifier_id",
        "producer_receipt_digest",
        "independent_verifier_evidence_sha256",
        "independent_replay_matches",
        "independent_qa_complete",
        "qualification_authority",
        "automatic_strategy_promotion",
        "paper_only",
        "live_trading_authority",
        "qa_digest",
    }
    if not isinstance(value, Mapping) or set(value) != expected:
        raise ProductResearchError("independent QA receipt schema mismatch")
    receipt = dict(value)
    if receipt.get("contract_version") != PRODUCT_INDEPENDENT_QA_CONTRACT:
        raise ProductResearchError("independent QA receipt contract mismatch")
    core = dict(receipt)
    claimed = _qa_sha256(core.pop("qa_digest", None), "independent QA digest")
    if _canonical_digest(core) != claimed:
        raise ProductResearchError("independent QA receipt digest mismatch")

    record = research.get("strategy_record")
    qualification = research.get("qualification")
    if not isinstance(record, Mapping) or not isinstance(qualification, Mapping):
        raise ProductResearchError("independent QA cannot bind missing research evidence")
    if _qa_sha256(receipt.get("strategy_record_digest"), "strategy_record_digest") != record.get("record_digest"):
        raise ProductResearchError("independent QA strategy record binding mismatch")
    if _qa_sha256(receipt.get("qualification_digest"), "qualification_digest") != qualification.get("qualification_digest"):
        raise ProductResearchError("independent QA qualification binding mismatch")
    source_sha = str(receipt.get("source_sha", "")).lower()
    if not _SHA_RE.fullmatch(source_sha) or source_sha != research.get("source_sha"):
        raise ProductResearchError("independent QA source binding mismatch")

    producer = _qa_identifier(receipt.get("producer_id"), "producer_id")
    verifier = _qa_identifier(receipt.get("verifier_id"), "verifier_id")
    if producer == verifier:
        raise ProductResearchError("independent QA producer and verifier must be distinct")
    producer_digest = _qa_sha256(receipt.get("producer_receipt_digest"), "producer_receipt_digest")
    verifier_digest = _qa_sha256(
        receipt.get("independent_verifier_evidence_sha256"),
        "independent_verifier_evidence_sha256",
    )
    if producer_digest == verifier_digest:
        raise ProductResearchError("independent QA producer and verifier evidence must be distinct")
    if (
        receipt.get("independent_replay_matches") is not True
        or receipt.get("independent_qa_complete") is not True
        or receipt.get("qualification_authority") is not False
        or receipt.get("automatic_strategy_promotion") is not False
        or receipt.get("paper_only") is not True
        or receipt.get("live_trading_authority") is not False
    ):
        raise ProductResearchError("independent QA authority or replay contract invalid")
    return receipt


def _public_mapping(registry: Mapping[str, Any], symbol: str, timeframe: str) -> tuple[dict[str, Any], dict[str, Any]]:
    spec = TIMEFRAMES.get(timeframe)
    if spec is None:
        raise ProductResearchError("unsupported product timeframe")
    source_symbol = symbol.upper().strip()
    matches: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for raw_mapping in registry.get("mappings", []):
        mapping = dict(raw_mapping)
        if mapping.get("market_category") != "spot" or mapping.get("manifest_timeframe") != spec["manifest"]:
            continue
        for raw_source in mapping.get("sources", []):
            source = dict(raw_source)
            if source.get("exchange") == "Bybit" and source.get("role") == "primary" and source.get("status") == "compatible" and source.get("symbol") == source_symbol:
                matches.append((mapping, source))
    if len(matches) != 1:
        raise ProductResearchError("requested symbol/timeframe has no unique compatible canonical Bybit primary mapping")
    return matches[0]


def _finite(value: Any) -> float:
    result = float(value)
    if not (-float("inf") < result < float("inf")):
        raise ProductResearchError("non-finite research metric")
    return result


def _serialize_backtest(result: Any, *, curve_points: int = 180, fill_limit: int = 100) -> dict[str, Any]:
    metrics = {key: (_finite(value) if isinstance(value, float) else value) for key, value in result.metrics.items()}
    curve = result.equity_curve
    stride = max(1, len(curve) // max(1, curve_points))
    points = [{
        "timestamp": row["timestamp"].isoformat(), "equity": _finite(row["equity"]),
        "drawdown": _finite(row["drawdown"]), "exposure": _finite(row["net_exposure"]),
    } for _, row in curve.iloc[::stride].tail(curve_points).iterrows()]
    fills = [{
        "execution_time": row["execution_time"].isoformat() if hasattr(row["execution_time"], "isoformat") else str(row["execution_time"]),
        "side": str(row["side"]), "fill_price": _finite(row["fill_price"]),
        "notional": _finite(row["notional"]), "fee": _finite(row["fee"]), "reason": str(row["reason"]),
    } for _, row in result.fills.tail(fill_limit).iterrows()]
    return {"metrics": metrics, "equity_curve": points, "fills": fills}


class ProductResearchRuntime:
    """Canonical public-data research plus qualification-gated automated Paper."""

    def __init__(self, product_runtime: ProductRuntime, *, source_sha: str | None = None, dataset_fetcher: Callable[..., Mapping[str, Any]] = fetch_bind_bybit_dataset, clock_ms: Callable[[], int] | None = None) -> None:
        self.product_runtime = product_runtime
        self._source_sha_value = source_sha
        self.dataset_fetcher = dataset_fetcher
        self.clock_ms = clock_ms or (lambda: int(time.time() * 1000))
        self._last_research: dict[str, Any] | None = None

    def _independent_qa_path(self, record_digest: str) -> Path:
        override = os.environ.get("NEXUS_PRODUCT_QA_RECEIPT_PATH", "").strip()
        if override:
            return Path(override)
        return self.product_runtime.root / "research_qa" / f"{record_digest}.json"

    def _load_independent_qa(self, research: Mapping[str, Any]) -> dict[str, Any] | None:
        record = research.get("strategy_record")
        if not isinstance(record, Mapping):
            raise ProductResearchError("strategy registry record is unavailable")
        record_digest = _qa_sha256(record.get("record_digest"), "strategy record digest")
        path = self._independent_qa_path(record_digest)
        if not path.exists():
            return None
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 65_536:
            raise ProductResearchError("independent QA artifact path is unsafe")
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ProductResearchError("independent QA artifact is unreadable") from exc
        return _validate_independent_qa_receipt(value, research=research)

    def registry_snapshot(self) -> dict[str, Any]:
        try: registry = load_and_validate(_registry_path())
        except Exception as exc: raise ProductResearchError(f"canonical market registry unavailable: {exc}") from exc
        rows = []
        for mapping in registry.get("mappings", []):
            rows.append({
                "mapping_id": mapping.get("mapping_id"), "canonical_symbol": mapping.get("canonical_symbol"),
                "market_category": mapping.get("market_category"), "timeframe": mapping.get("manifest_timeframe"),
                "finality": mapping.get("candle_finality"),
                "sources": [{"exchange": source.get("exchange"), "role": source.get("role"), "status": source.get("status"), "symbol": source.get("symbol"), "category": source.get("category")} for source in mapping.get("sources", [])],
            })
        return {"contract_version": PRODUCT_DATA_CONTRACT, "registry_version": registry.get("registry_version"), "authority": registry.get("authority"), "mappings": rows, "private_credentials_required": False, "paper_only": True}

    def fetch_dataset(self, *, symbol: str, timeframe: str, limit: int = 240) -> dict[str, Any]:
        if isinstance(limit, bool) or not isinstance(limit, int) or not 60 <= limit <= 500: raise ProductResearchError("dataset limit must be between 60 and 500")
        registry = load_and_validate(_registry_path()); mapping, source = _public_mapping(registry, symbol, timeframe); spec = TIMEFRAMES[timeframe]
        now_ms = self.clock_ms(); end_ms = ((now_ms - spec["step_ms"]) // spec["step_ms"]) * spec["step_ms"]; start_ms = end_ms - (limit - 1) * spec["step_ms"]
        if start_ms < 0: raise ProductResearchError("invalid bounded market window")
        try:
            dataset = self.dataset_fetcher(canonical_symbol=mapping["canonical_symbol"], source_symbol=source["symbol"], interval=spec["interval"], now_ms=now_ms, start_time_ms=start_ms, end_time_ms=end_ms, limit=limit, timeout_seconds=20.0)
            artifact = validate_canonical_dataset(dataset, registry_path=_registry_path())
        except Exception as exc:
            raise ProductResearchError(f"canonical public dataset unavailable: {exc}") from exc
        if artifact["row_count"] < 60: raise ProductResearchError("canonical dataset has insufficient closed-candle history")
        closed_at = int(artifact["rows"][-1]["open_time_ms"]) + int(spec["step_ms"]); age_ms = now_ms - closed_at
        if age_ms < 0 or age_ms > int(spec["step_ms"]) * 2: raise ProductResearchError("canonical primary data is stale or not yet final")
        return artifact

    def run_research(self, *, symbol: str, timeframe: str, family: str, limit: int = 240) -> dict[str, Any]:
        if family not in STRATEGY_PRESETS: raise ProductResearchError("unsupported approved strategy family")
        code_sha = _safe_source_sha(self._source_sha_value); dataset = self.fetch_dataset(symbol=symbol, timeframe=timeframe, limit=limit); config = dict(STRATEGY_PRESETS[family])
        try:
            job = run_research_job(dataset, hypothesis=f"Preregistered {family} research on canonical closed candles; no profitability claim.", family=family, strategy_version=f"{family}-product-v1", strategy_config=config, code_sha=code_sha, cost_model=COST_MODEL, kill_criteria=KILL_CRITERIA)
            strategy_record = build_strategy_record(
                dataset, job["experiment"], job["qualification"], job["evidence"]
            )
            research_lifecycle = build_research_lifecycle(strategy_record)
            targets = generate_targets(dataset, family, config)
            backtest = run_canonical_target_exposure_backtest(
                dataset,
                targets,
                BacktestConfig(initial_cash=10_000.0, fee_bps=COST_MODEL["fee_bps"], slippage_bps=COST_MODEL["slippage_bps"], max_abs_exposure=1.0, liquidate_at_end=True),
                registry_path=_registry_path(),
            )
        except Exception as exc:
            raise ProductResearchError(f"research qualification failed closed: {exc}") from exc
        last_row = dataset["rows"][-1]
        result = {
            "contract_version": PRODUCT_RESEARCH_CONTRACT, "paper_only": True, "live_execution_allowed": False, "profitability_claim": False, "source_sha": code_sha,
            "request": {"symbol": symbol, "timeframe": timeframe, "family": family, "limit": limit},
            "dataset": {"binding_sha256": dataset["binding_sha256"], "manifest_sha256": dataset["manifest_sha256"], "instrument": dataset["instrument"], "source": dataset["source"], "source_symbol": dataset["source_symbol"], "timeframe": dataset["manifest_timeframe"], "row_count": dataset["row_count"], "first_open_time_ms": dataset["rows"][0]["open_time_ms"], "last_open_time_ms": last_row["open_time_ms"], "last_close": last_row["close"]},
            "strategy_config": config, "cost_model": dict(COST_MODEL), "kill_criteria": dict(KILL_CRITERIA), "qualification": job["qualification"], "evidence": job["evidence"], "strategy_record": strategy_record, "research_lifecycle": list(research_lifecycle), "independent_qa": {"status": "required" if job["qualification"].get("status") == "paper_candidate" else "not_applicable", "verified": False}, "paper_candidate_handoff": job["paper_candidate_handoff"], "pipeline_digest": job["pipeline_digest"], "latest_target": float(targets.iloc[-1]), "backtest": _serialize_backtest(backtest), "_dataset": dataset, "_experiment": job["experiment"],
        }
        self._last_research = result
        return {key: value for key, value in result.items() if not key.startswith("_")}

    def last_research(self) -> dict[str, Any]:
        if self._last_research is None: return {"contract_version": PRODUCT_RESEARCH_CONTRACT, "status": "no_research_run", "paper_only": True}
        return {key: value for key, value in self._last_research.items() if not key.startswith("_")}

    @staticmethod
    def _regime(dataset: Mapping[str, Any]) -> tuple[str, str]:
        closes = [Decimal(str(row["close"])) for row in dataset["rows"][-21:]]
        if len(closes) < 2 or closes[0] <= 0: return "neutral", "0.50"
        change = closes[-1] / closes[0] - Decimal("1")
        if change >= Decimal("0.02"): return "bullish", "0.80"
        if change <= Decimal("-0.02"): return "bearish", "0.80"
        return "neutral", "0.60"

    def auto_paper(self) -> dict[str, Any]:
        research = self._last_research
        if research is None: raise ProductResearchError("run canonical research before automated Paper")
        try:
            dataset = validate_canonical_dataset(research["_dataset"], registry_path=_registry_path())
            qualification = research["qualification"]
            recomputed = qualify(dataset, research["_experiment"], research["evidence"])
        except Exception as exc:
            raise ProductResearchError(f"automated Paper rejected invalid canonical lineage: {exc}") from exc
        if recomputed != qualification:
            raise ProductResearchError("automated Paper rejected mutated qualification lineage")
        expected_evidence_ref = f"dataset-sha256:{dataset['binding_sha256']}"
        if expected_evidence_ref not in research["evidence"].get("evidence_refs", []):
            raise ProductResearchError("automated Paper rejected evidence bound to another dataset")
        dataset_summary = research.get("dataset", {})
        request = research.get("request", {})
        if dataset_summary.get("binding_sha256") != dataset["binding_sha256"] or dataset_summary.get("manifest_sha256") != dataset["manifest_sha256"]:
            raise ProductResearchError("automated Paper rejected mutated dataset summary")
        if qualification.get("dataset_binding_sha256") != dataset["binding_sha256"]:
            raise ProductResearchError("automated Paper rejected qualification bound to another dataset")
        if request.get("symbol") != dataset["source_symbol"] or TIMEFRAMES.get(request.get("timeframe"), {}).get("manifest") != dataset["manifest_timeframe"] or request.get("family") != qualification.get("family"):
            raise ProductResearchError("automated Paper rejected request outside canonical qualification tuple")
        handoff = research.get("paper_candidate_handoff")
        if qualification.get("status") == "paper_candidate":
            if not isinstance(handoff, Mapping) or handoff.get("qualification_digest") != qualification.get("qualification_digest") or handoff.get("paper_only") is not True or handoff.get("live_execution_allowed") is not False:
                raise ProductResearchError("automated Paper rejected invalid paper-candidate handoff")
        if qualification.get("status") != "paper_candidate": return {"contract_version": PRODUCT_AUTO_PAPER_CONTRACT, "paper_only": True, "accepted": False, "status": "qualification_killed", "kill_reasons": qualification.get("kill_reasons", []), "live_trading_authority": False}
        qa_receipt = self._load_independent_qa(research)
        if qa_receipt is None:
            research["independent_qa"] = {"status": "required", "verified": False}
            return {"contract_version": PRODUCT_AUTO_PAPER_CONTRACT, "paper_only": True, "accepted": False, "status": "independent_qa_required", "independent_qa": dict(research["independent_qa"]), "live_trading_authority": False}
        research["independent_qa"] = {"status": "verified", "verified": True, "qa_digest": qa_receipt["qa_digest"], "verifier_id": qa_receipt["verifier_id"]}
        if float(research.get("latest_target", 0.0)) <= 0.0: return {"contract_version": PRODUCT_AUTO_PAPER_CONTRACT, "paper_only": True, "accepted": False, "status": "no_open_signal", "independent_qa": dict(research["independent_qa"]), "live_trading_authority": False}
        spec = TIMEFRAMES[request["timeframe"]]
        strategy_record = research.get("strategy_record")
        if not isinstance(strategy_record, Mapping) or strategy_record.get("lifecycle_state") != "CANDIDATE":
            raise ProductResearchError("automated Paper requires an immutable CANDIDATE registry record")
        strategy_id = _qa_sha256(strategy_record.get("strategy_id"), "strategy_id")
        strategy_version = str(strategy_record.get("strategy_version", ""))
        current_ms = self.clock_ms()
        source_ms = int(dataset["rows"][-1]["open_time_ms"]) + int(spec["step_ms"]); source_time = _utc_ms(source_ms); occurred_at = _utc_ms(current_ms)
        if current_ms - source_ms > int(spec["step_ms"]) * 2: raise ProductResearchError("automated Paper rejected stale canonical data")
        dataset_id = f"canonical:{dataset['mapping_id']}"; dataset_revision = dataset["binding_sha256"]; regime_label, regime_confidence = self._regime(dataset); regime_id = f"regime:{dataset_revision[:20]}:{regime_label}"; correlation_id = f"auto-paper:{uuid.uuid4().hex}"
        with self.product_runtime._lock:
            existing = self.product_runtime._ensure_account(); state = replay(existing).state
            if any(row[0] == request["symbol"] for row in state.positions): return {"contract_version": PRODUCT_AUTO_PAPER_CONTRACT, "paper_only": True, "accepted": False, "status": "position_exists"}
            equity = Decimal(str(state.equity)); price = Decimal(str(dataset["rows"][-1]["close"])); quantity = ((equity * Decimal("0.05")) / price).quantize(Decimal("0.00000001"), rounding=ROUND_DOWN)
            if quantity <= 0: raise ProductResearchError("auto-paper sizing produced zero quantity")
            stop = price * Decimal("0.985"); target = price * Decimal("1.03")
            dataset_artifact = {"dataset_id": dataset_id, "dataset_revision": dataset_revision, "source_id": "Bybit", "source_timestamp": source_time, "received_timestamp": occurred_at, "symbol": request["symbol"], "timeframe": request["timeframe"], "readiness_status": "ready", "provenance_digest": dataset["manifest_sha256"]}
            approval_digest = _canonical_digest({"strategy_record_digest": strategy_record["record_digest"], "independent_qa_digest": qa_receipt["qa_digest"]})
            qualification_artifact = {"artifact_id": f"registry:{strategy_record['record_digest']}", "artifact_digest": approval_digest, "strategy_id": strategy_id, "strategy_version": strategy_version, "dataset_id": dataset_id, "dataset_revision": dataset_revision, "status": "paper_eligible", "qualified_at": occurred_at}
            regime_artifact = {"regime_id": regime_id, "regime_version": "product-regime-v1", "label": regime_label, "confidence": regime_confidence, "source_timestamp": source_time, "dataset_id": dataset_id, "dataset_revision": dataset_revision, "symbol": request["symbol"], "timeframe": request["timeframe"]}
            decision = {"decision_id": f"decision:{uuid.uuid4().hex}", "operation": "open", "side": "long", "quantity": str(quantity), "reference_price": str(price), "stop_price": str(stop), "target_price": str(target), "confidence": regime_confidence, "strategy_id": strategy_id, "strategy_version": strategy_version, "dataset_id": dataset_id, "dataset_revision": dataset_revision, "regime_id": regime_id, "regime_version": "product-regime-v1", "symbol": request["symbol"], "timeframe": request["timeframe"], "source_timestamp": source_time, "correlation_id": correlation_id, "causation_id": regime_id, "risk_policy_version": "1.0.0"}
            policy = _risk_policy(); policy["eligible_strategies"] = [{"id": strategy_id, "version": strategy_version}]; policy["max_signal_age_seconds"] = int(spec["step_ms"] // 1000) * 2 + 300
            try:
                result = run_automated_signal_pipeline(dataset=dataset_artifact, qualification=qualification_artifact, regime=regime_artifact, decision=decision, risk_state=_risk_state(state, symbol=request["symbol"], signals_today=_session_signal_count(existing)), risk_policy=policy, portfolio_state=state, occurred_at=occurred_at, fee_rate=PAPER_DEFAULT_FEE_RATE, slippage_bps=PAPER_DEFAULT_SLIPPAGE_BPS)
                if result.execution is not None:
                    replay_verified = replay(result.events, previous_valid=state).state == result.state
                    acceptance = {
                        "risk_gate_allowed": bool(result.risk_decision.allowed),
                        "replay_verified": replay_verified,
                        "paper_execution_evidence_sha256": _canonical_digest(list(result.events)),
                        "independent_verifier_evidence_sha256": qa_receipt["independent_verifier_evidence_sha256"],
                        "producer_id": "product-auto-paper-pipeline",
                        "verifier_id": qa_receipt["verifier_id"],
                    }
                    promoted = promote_candidate_to_paper(
                        strategy_record, research["research_lifecycle"], acceptance
                    )
                    research["paper_lifecycle"] = list(promoted)
                self.product_runtime._write_events([*existing, *result.events])
            except Exception as exc:
                raise ProductResearchError(f"automated Paper pipeline failed closed: {exc}") from exc
        return {"contract_version": PRODUCT_AUTO_PAPER_CONTRACT, "paper_only": True, "accepted": bool(result.risk_decision.allowed and result.execution is not None), "status": "paper_executed" if result.execution is not None else "risk_rejected", "dataset": dataset_artifact, "qualification": qualification_artifact, "registry": {"strategy_id": strategy_id, "record_digest": strategy_record["record_digest"]}, "independent_qa": dict(research["independent_qa"]), "regime": regime_artifact, "decision": decision, "signal": dict(result.signal), "risk": _json_safe(asdict(result.risk_decision)), "execution": None if result.execution is None else {"fill_price": str(result.execution.fill_price), "fee": str(result.execution.fee), "slippage_cost": str(result.execution.slippage_cost), "realized_pnl": str(result.execution.realized_pnl), "event_count": len(result.execution.events)}, "account": serialize_portfolio(result.state), "live_trading_authority": False}
