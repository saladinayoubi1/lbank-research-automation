"""Prepare canonical proposal-only inputs for the regime strategy runtime.

This adapter deliberately stops before automated signal execution.  It rechecks
the same canonical research lineage used by ProductResearchRuntime.auto_paper(),
builds a deterministic proposal, Risk state/policy, and an isolated PortfolioState,
and returns them for nexus_regime_strategy_runtime.  Deterministic Risk remains
the only authority that can accept a proposal and this module never persists a
fill or grants Live authority.
"""
from __future__ import annotations

import hashlib
import json
from decimal import Decimal, ROUND_DOWN
from typing import Any, Mapping

from nexus_isolated_product_runtime import IsolatedProductRuntime
from paper_event_store import replay
from phase5_data_binding import validate_canonical_dataset
from phase5_strategy_factory import qualify
from product_research_runtime import (
    PRODUCT_AUTO_PAPER_CONTRACT,
    TIMEFRAMES,
    ProductResearchError,
    ProductResearchRuntime,
    _registry_path,
    _utc_ms,
)
from product_runtime import (
    PAPER_DEFAULT_FEE_RATE,
    PAPER_DEFAULT_SLIPPAGE_BPS,
    _risk_policy,
    _risk_state,
    _session_signal_count,
)

PREPARATION_SCHEMA = "nexus.regime-paper-lane-preparation.v1"


def _canonical(value: Any) -> bytes:
    try:
        return json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ProductResearchError("regime Paper proposal is not canonical JSON") from exc


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _non_actionable(
    *, family: str, status: str, account_id: str, details: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    core = {
        "schema_version": PREPARATION_SCHEMA,
        "family": family,
        "status": status,
        "account_id": account_id,
        "lane_ready": False,
        "execution_performed": False,
        "paper_only": True,
        "live_trading_authority": False,
        "deterministic_risk_final_authority": True,
        "details": dict(details or {}),
    }
    return {**core, "preparation_digest": _digest(core), "lane": None}


def prepare_regime_paper_lane(research_runtime: ProductResearchRuntime) -> dict[str, Any]:
    """Build one verified proposal lane without running Risk or Paper execution."""
    if not isinstance(research_runtime, ProductResearchRuntime):
        raise ProductResearchError("regime Paper preparation requires ProductResearchRuntime")
    product_runtime = research_runtime.product_runtime
    if not isinstance(product_runtime, IsolatedProductRuntime):
        raise ProductResearchError("regime Paper preparation requires an isolated Paper runtime")

    research = research_runtime._last_research
    if research is None:
        raise ProductResearchError("run canonical research before regime Paper preparation")
    try:
        dataset = validate_canonical_dataset(research["_dataset"], registry_path=_registry_path())
        qualification = research["qualification"]
        recomputed = qualify(dataset, research["_experiment"], research["evidence"])
    except Exception as exc:
        raise ProductResearchError(f"regime Paper rejected invalid canonical lineage: {exc}") from exc
    if recomputed != qualification:
        raise ProductResearchError("regime Paper rejected mutated qualification lineage")

    expected_evidence_ref = f"dataset-sha256:{dataset['binding_sha256']}"
    if expected_evidence_ref not in research["evidence"].get("evidence_refs", []):
        raise ProductResearchError("regime Paper rejected evidence bound to another dataset")
    dataset_summary = research.get("dataset", {})
    request = research.get("request", {})
    if (
        dataset_summary.get("binding_sha256") != dataset["binding_sha256"]
        or dataset_summary.get("manifest_sha256") != dataset["manifest_sha256"]
    ):
        raise ProductResearchError("regime Paper rejected mutated dataset summary")
    if qualification.get("dataset_binding_sha256") != dataset["binding_sha256"]:
        raise ProductResearchError("regime Paper rejected qualification bound to another dataset")
    if (
        request.get("symbol") != dataset["source_symbol"]
        or TIMEFRAMES.get(request.get("timeframe"), {}).get("manifest") != dataset["manifest_timeframe"]
        or request.get("family") != qualification.get("family")
    ):
        raise ProductResearchError("regime Paper rejected request outside canonical qualification tuple")

    family = str(request.get("family", ""))
    handoff = research.get("paper_candidate_handoff")
    if qualification.get("status") == "paper_candidate":
        if (
            not isinstance(handoff, Mapping)
            or handoff.get("qualification_digest") != qualification.get("qualification_digest")
            or handoff.get("paper_only") is not True
            or handoff.get("live_execution_allowed") is not False
        ):
            raise ProductResearchError("regime Paper rejected invalid paper-candidate handoff")
    else:
        return _non_actionable(
            family=family,
            status="qualification_killed",
            account_id=product_runtime.account_id,
            details={"kill_reasons": list(qualification.get("kill_reasons", []))},
        )

    if float(research.get("latest_target", 0.0)) <= 0.0:
        return _non_actionable(
            family=family, status="no_open_signal", account_id=product_runtime.account_id
        )

    spec = TIMEFRAMES[request["timeframe"]]
    current_ms = research_runtime.clock_ms()
    if isinstance(current_ms, bool) or not isinstance(current_ms, int) or current_ms <= 0:
        raise ProductResearchError("regime Paper clock must be a positive integer")
    source_ms = int(dataset["rows"][-1]["open_time_ms"]) + int(spec["step_ms"])
    age_ms = current_ms - source_ms
    if age_ms < 0 or age_ms > int(spec["step_ms"]) * 2:
        raise ProductResearchError("regime Paper rejected stale or future canonical data")
    source_time = _utc_ms(source_ms)
    occurred_at = _utc_ms(current_ms)

    dataset_id = f"canonical:{dataset['mapping_id']}"
    dataset_revision = dataset["binding_sha256"]
    regime_label, regime_confidence = research_runtime._regime(dataset)
    regime_id = f"regime:{dataset_revision[:20]}:{regime_label}"
    strategy_version = qualification["strategy_version"]

    with product_runtime._lock:
        existing = product_runtime._ensure_account()
        state = replay(existing).state
        if state.aggregate_id != product_runtime.account_id:
            raise ProductResearchError("regime Paper isolated portfolio binding mismatch")
        if any(row[0] == request["symbol"] for row in state.positions):
            return _non_actionable(
                family=family, status="position_exists", account_id=product_runtime.account_id
            )
        equity = Decimal(str(state.equity))
        price = Decimal(str(dataset["rows"][-1]["close"]))
        quantity = ((equity * Decimal("0.05")) / price).quantize(
            Decimal("0.00000001"), rounding=ROUND_DOWN
        )
        if quantity <= 0:
            raise ProductResearchError("regime Paper sizing produced zero quantity")
        stop = price * Decimal("0.985")
        target = price * Decimal("1.03")

        binding = _digest({
            "source_sha": research["source_sha"],
            "dataset_revision": dataset_revision,
            "qualification_digest": qualification["qualification_digest"],
            "account_id": product_runtime.account_id,
            "symbol": request["symbol"],
            "timeframe": request["timeframe"],
            "family": family,
            "occurred_at": occurred_at,
        })
        dataset_artifact = {
            "dataset_id": dataset_id,
            "dataset_revision": dataset_revision,
            "source_id": "Bybit",
            "source_timestamp": source_time,
            "received_timestamp": occurred_at,
            "symbol": request["symbol"],
            "timeframe": request["timeframe"],
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
            "symbol": request["symbol"],
            "timeframe": request["timeframe"],
        }
        decision = {
            "decision_id": f"proposal:{binding[:40]}",
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
            "symbol": request["symbol"],
            "timeframe": request["timeframe"],
            "source_timestamp": source_time,
            "correlation_id": f"proposal:{binding[:32]}",
            "causation_id": regime_id,
            "risk_policy_version": "1.0.0",
        }
        policy = _risk_policy()
        policy["eligible_strategies"] = [{"id": family, "version": strategy_version}]
        policy["max_signal_age_seconds"] = int(spec["step_ms"] // 1000) * 2 + 300
        lane = {
            "family": family,
            "dataset": dataset_artifact,
            "qualification": qualification_artifact,
            "regime": regime_artifact,
            "decision": decision,
            "risk_state": _risk_state(
                state,
                symbol=request["symbol"],
                signals_today=_session_signal_count(existing),
            ),
            "risk_policy": policy,
            "portfolio_state": state,
            "fee_rate": PAPER_DEFAULT_FEE_RATE,
            "slippage_bps": PAPER_DEFAULT_SLIPPAGE_BPS,
        }

    core = {
        "schema_version": PREPARATION_SCHEMA,
        "contract_version": PRODUCT_AUTO_PAPER_CONTRACT,
        "family": family,
        "strategy_version": strategy_version,
        "strategy_record_digest": research["strategy_record"]["record_digest"],
        "qualification_digest": qualification["qualification_digest"],
        "dataset_binding_sha256": dataset_revision,
        "account_id": product_runtime.account_id,
        "status": "ready",
        "lane_ready": True,
        "execution_performed": False,
        "paper_only": True,
        "live_trading_authority": False,
        "deterministic_risk_final_authority": True,
        "proposal_binding": binding,
    }
    return {**core, "preparation_digest": _digest(core), "lane": lane}
