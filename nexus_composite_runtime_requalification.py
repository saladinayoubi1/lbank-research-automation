"""Fresh canonical Bybit runtime requalification for composite VAL-40 candidates.

This module reuses the existing ProductResearchRuntime canonical public-data
boundary and the existing composite build_features/signal_for/backtest engine.
It never selects a new strategy, mutates REG-50, activates Runtime/Paper, or
grants Live authority.  Its strongest outcome is QUALIFIED_FOR_REVIEW.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

import pandas as pd

from nexus_composite_strategy_research import (
    CompositeResearchError,
    backtest,
    build_features,
    signal_for,
)
from nexus_composite_val40_contract import verify_execution_contract
from product_research_runtime import ProductResearchError, ProductResearchRuntime

SCHEMA = "nexus.composite-runtime-requalification.v1"
VERIFY_SCHEMA = "nexus.composite-runtime-requalification-verification.v1"
QA_SCHEMA = "nexus.composite-runtime-requalification-qa.v1"
SYMBOLS = ("BTCUSDT", "ETHUSDT")
TIMEFRAMES = ("minute15", "hour1", "hour4")
PROFILES = {
    "conservative": (10.0, 5.0),
    "stress": (25.0, 15.0),
}
_SHA40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")


class CompositeRuntimeRequalificationError(RuntimeError):
    pass


DatasetLoader = Callable[[str, str, int], Mapping[str, Any]]
Evaluator = Callable[
    [Mapping[str, Any], str, Mapping[str, Mapping[str, Any]], Mapping[str, Any]],
    list[dict[str, Any]],
]


def _canonical(value: Any) -> bytes:
    try:
        return json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise CompositeRuntimeRequalificationError("runtime evidence is not canonical JSON") from exc


def digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _validate_input(execution_contract: Mapping[str, Any]) -> dict[str, Any]:
    computed = verify_execution_contract(execution_contract)
    if computed.get("decision") != "pass":
        raise CompositeRuntimeRequalificationError("VAL-40 execution contract verification rejected")
    if (
        execution_contract.get("requires_fresh_runtime_data") is not True
        or execution_contract.get("no_minimum_trade_count_gate") is not True
        or execution_contract.get("paper_only") is not True
        or execution_contract.get("qualification_authority") is not False
        or execution_contract.get("registry_mutation_authority") is not False
        or execution_contract.get("runtime_activation_authority") is not False
        or execution_contract.get("promotion_authority") is not False
        or execution_contract.get("paper_execution_authority") is not False
        or execution_contract.get("automatic_strategy_promotion") is not False
        or execution_contract.get("live_trading_authority") is not False
        or not isinstance(execution_contract.get("strategy_config"), Mapping)
        or not execution_contract.get("strategy_config")
    ):
        raise CompositeRuntimeRequalificationError("execution contract exceeds VAL-40 authority")
    return dict(execution_contract)


def _validate_dataset(
    artifact: Mapping[str, Any],
    *,
    symbol: str,
    timeframe: str,
) -> dict[str, Any]:
    rows = artifact.get("rows")
    if (
        artifact.get("paper_only") is not True
        or artifact.get("downstream_eligible") is not True
        or artifact.get("source") != "Bybit"
        or artifact.get("source_role") != "primary"
        or artifact.get("instrument") != symbol
        or artifact.get("manifest_timeframe") != timeframe
        or artifact.get("finality") != "closed_only"
        or artifact.get("row_count") != 1000
        or not _HEX64.fullmatch(str(artifact.get("binding_sha256", "")))
        or not isinstance(rows, list)
        or len(rows) != 1000
    ):
        raise CompositeRuntimeRequalificationError(
            f"canonical runtime dataset contract mismatch: {symbol}/{timeframe}"
        )
    previous = None
    expected_step = {"minute15": 900_000, "hour1": 3_600_000, "hour4": 14_400_000}[timeframe]
    for row in rows:
        if not isinstance(row, Mapping):
            raise CompositeRuntimeRequalificationError("runtime dataset row is invalid")
        at = row.get("open_time_ms")
        if isinstance(at, bool) or not isinstance(at, int) or at <= 0:
            raise CompositeRuntimeRequalificationError("runtime dataset timestamp is invalid")
        if previous is not None and at - previous != expected_step:
            raise CompositeRuntimeRequalificationError("runtime dataset chronology is incomplete")
        previous = at
        for field in ("open", "high", "low", "close", "volume"):
            value = row.get(field)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
                raise CompositeRuntimeRequalificationError("runtime dataset numeric field is invalid")
        if (
            float(row["open"]) <= 0
            or float(row["high"]) <= 0
            or float(row["low"]) <= 0
            or float(row["close"]) <= 0
            or float(row["volume"]) < 0
            or float(row["high"]) < max(float(row["open"]), float(row["close"]), float(row["low"]))
            or float(row["low"]) > min(float(row["open"]), float(row["close"]), float(row["high"]))
        ):
            raise CompositeRuntimeRequalificationError("runtime dataset OHLCV is invalid")
    return dict(artifact)


def _frame(artifact: Mapping[str, Any], symbol: str, timeframe: str) -> pd.DataFrame:
    rows = artifact["rows"]
    frame = pd.DataFrame([{
        "timestamp": pd.to_datetime(int(row["open_time_ms"]), unit="ms", utc=True),
        "open": float(row["open"]),
        "high": float(row["high"]),
        "low": float(row["low"]),
        "close": float(row["close"]),
        "volume": float(row["volume"]),
        "symbol": symbol,
        "timeframe": timeframe,
    } for row in rows])
    return frame


def _default_evaluator(
    candidate: Mapping[str, Any],
    symbol: str,
    datasets: Mapping[str, Mapping[str, Any]],
    peer_15m: Mapping[str, Any],
) -> list[dict[str, Any]]:
    frames = {
        timeframe: _frame(datasets[timeframe], symbol, timeframe)
        for timeframe in TIMEFRAMES
    }
    peer_symbol = str(peer_15m["instrument"])
    features = build_features(
        frames,
        peer_15m=_frame(peer_15m, peer_symbol, "minute15"),
    )
    config = dict(candidate["strategy_config"])
    signals = signal_for(features, config)
    rows = []
    for profile, (fee_bps, slip_bps) in PROFILES.items():
        result = backtest(
            features,
            signals,
            fee_bps=fee_bps,
            slip_bps=slip_bps,
            risk_variant=int(config["risk_variant"]),
        )
        rows.append({
            "symbol": symbol,
            "profile": profile,
            "mechanism": candidate["mechanism"],
            "timeframe": candidate["timeframe"],
            "config_fingerprint": candidate["config_fingerprint"],
            "bars": len(features),
            **result,
        })
    return rows


def _validate_runtime_rows(
    rows: list[Mapping[str, Any]],
    candidate: Mapping[str, Any],
) -> list[dict[str, Any]]:
    expected = {(symbol, profile) for symbol in SYMBOLS for profile in PROFILES}
    actual = {
        (row.get("symbol"), row.get("profile"))
        for row in rows if isinstance(row, Mapping)
    }
    if len(rows) != 4 or actual != expected:
        raise CompositeRuntimeRequalificationError("fresh runtime result grid is incomplete")
    result = []
    for row in rows:
        if (
            row.get("mechanism") != candidate.get("mechanism")
            or row.get("timeframe") != candidate.get("timeframe")
            or row.get("config_fingerprint") != candidate.get("config_fingerprint")
            or isinstance(row.get("closed_round_trips"), bool)
            or not isinstance(row.get("closed_round_trips"), int)
            or row.get("closed_round_trips") < 0
            or isinstance(row.get("net_return_pct"), bool)
            or not isinstance(row.get("net_return_pct"), (int, float))
            or not math.isfinite(float(row.get("net_return_pct")))
            or isinstance(row.get("max_drawdown_pct"), bool)
            or not isinstance(row.get("max_drawdown_pct"), (int, float))
            or not math.isfinite(float(row.get("max_drawdown_pct")))
            or row.get("trade_count_limit") is not None
            or row.get("halted_on_drawdown") not in {True, False}
        ):
            raise CompositeRuntimeRequalificationError("fresh runtime result row is invalid")
        result.append(dict(row))
    result.sort(key=lambda row: (row["symbol"], row["profile"]))
    return result


def run_requalification(
    execution_contract: Mapping[str, Any],
    *,
    execution_source_sha: str,
    now_ms: int,
    dataset_loader: DatasetLoader | None = None,
    evaluator: Evaluator = _default_evaluator,
) -> dict[str, Any]:
    row = _validate_input(execution_contract)
    if not _SHA40.fullmatch(str(execution_source_sha)):
        raise CompositeRuntimeRequalificationError("execution source SHA is invalid")
    if isinstance(now_ms, bool) or not isinstance(now_ms, int) or now_ms <= 0:
        raise CompositeRuntimeRequalificationError("runtime clock is invalid")

    if dataset_loader is None:
        runtime = ProductResearchRuntime(
            None,  # type: ignore[arg-type]
            source_sha=execution_source_sha,
            clock_ms=lambda: now_ms,
        )
        dataset_loader = lambda symbol, timeframe, limit: runtime.fetch_dataset(
            symbol=symbol, timeframe=timeframe, limit=limit
        )

    datasets: dict[str, dict[str, dict[str, Any]]] = {}
    for symbol in SYMBOLS:
        datasets[symbol] = {}
        for timeframe in TIMEFRAMES:
            try:
                artifact = dataset_loader(symbol, timeframe, 1000)
            except ProductResearchError as exc:
                raise CompositeRuntimeRequalificationError(
                    f"canonical runtime data unavailable: {symbol}/{timeframe}: {exc}"
                ) from exc
            datasets[symbol][timeframe] = _validate_dataset(
                artifact, symbol=symbol, timeframe=timeframe
            )

    runtime_rows: list[dict[str, Any]] = []
    for symbol in SYMBOLS:
        peer = SYMBOLS[1] if symbol == SYMBOLS[0] else SYMBOLS[0]
        first = evaluator(row, symbol, datasets[symbol], datasets[peer]["minute15"])
        second = evaluator(row, symbol, datasets[symbol], datasets[peer]["minute15"])
        if _canonical(first) != _canonical(second):
            raise CompositeRuntimeRequalificationError("fresh runtime replay is not deterministic")
        runtime_rows.extend(first)
    runtime_rows = _validate_runtime_rows(runtime_rows, row)

    total_trades = sum(int(item["closed_round_trips"]) for item in runtime_rows)
    all_positive = all(float(item["net_return_pct"]) > 0.0 for item in runtime_rows)
    any_halted = any(item["halted_on_drawdown"] is True for item in runtime_rows)
    if total_trades == 0:
        verdict = "REJECTED_FRESH_RUNTIME"
        reasons = ["ZERO_ACTIVITY"]
    elif any_halted:
        verdict = "REJECTED_FRESH_RUNTIME"
        reasons = ["DRAWDOWN_HALT"]
    elif not all_positive:
        verdict = "REJECTED_FRESH_RUNTIME"
        reasons = ["NON_POSITIVE_RUNTIME_CELL"]
    else:
        verdict = "QUALIFIED_FOR_REVIEW"
        reasons = ["FRESH_RUNTIME_POSITIVE_ACROSS_SYMBOLS_AND_COST_PROFILES"]

    dataset_evidence = {
        symbol: {
            timeframe: {
                "binding_sha256": datasets[symbol][timeframe]["binding_sha256"],
                "last_open_time_ms": datasets[symbol][timeframe]["rows"][-1]["open_time_ms"],
                "row_count": datasets[symbol][timeframe]["row_count"],
                "source": datasets[symbol][timeframe]["source"],
                "source_role": datasets[symbol][timeframe]["source_role"],
            }
            for timeframe in TIMEFRAMES
        }
        for symbol in SYMBOLS
    }
    core = {
        "schema_version": SCHEMA,
        "system_map_node": "VAL-40",
        "decision": verdict,
        "reason_codes": reasons,
        "qualified_for_review": verdict == "QUALIFIED_FOR_REVIEW",
        "candidate_digest": row["candidate_digest"],
        "execution_contract": dict(row),
        "execution_contract_digest": row["execution_contract_digest"],
        "candidate_source_sha": row["candidate_source_sha"],
        "execution_source_sha": execution_source_sha,
        "evaluation_clock_ms": now_ms,
        "mechanism": row["mechanism"],
        "timeframe": row["timeframe"],
        "strategy_config": dict(row["strategy_config"]),
        "config_fingerprint": row["config_fingerprint"],
        "dataset_evidence": dataset_evidence,
        "dataset_evidence_digest": digest(dataset_evidence),
        "runtime_rows": runtime_rows,
        "runtime_rows_digest": digest(runtime_rows),
        "total_runtime_round_trips": total_trades,
        "no_minimum_trade_count_gate": True,
        "deterministic_replay_verified": True,
        "data_origin": "canonical_public_bybit_runtime",
        "closed_candle_finality_verified": True,
        "research_only": True,
        "paper_only": True,
        "candidate_state_created": False,
        "qualification_authority": False,
        "registry_mutation_authority": False,
        "promotion_authority": False,
        "paper_execution_authority": False,
        "automatic_strategy_promotion": False,
        "live_trading_authority": False,
    }
    return {**core, "requalification_digest": digest(core)}


def verify_requalification(value: Mapping[str, Any]) -> dict[str, Any]:
    checks = {
        "schema": False,
        "digest": False,
        "candidate": False,
        "datasets": False,
        "runtime_rows": False,
        "decision": False,
        "authority": False,
    }
    try:
        core = dict(value)
        claimed = core.pop("requalification_digest", None)
        checks["schema"] = (
            core.get("schema_version") == SCHEMA
            and core.get("system_map_node") == "VAL-40"
        )
        checks["digest"] = isinstance(claimed, str) and claimed == digest(core)
        execution_contract = core.get("execution_contract")
        computed_contract = (
            verify_execution_contract(execution_contract)
            if isinstance(execution_contract, Mapping) else {}
        )
        checks["candidate"] = bool(
            isinstance(execution_contract, Mapping)
            and computed_contract.get("decision") == "pass"
            and core.get("execution_contract_digest")
                == execution_contract.get("execution_contract_digest")
            and core.get("candidate_digest") == execution_contract.get("candidate_digest")
            and core.get("candidate_source_sha") == execution_contract.get("candidate_source_sha")
            and core.get("mechanism") == execution_contract.get("mechanism")
            and core.get("timeframe") == execution_contract.get("timeframe")
            and core.get("strategy_config") == execution_contract.get("strategy_config")
            and core.get("config_fingerprint") == execution_contract.get("config_fingerprint")
        )
        evidence = core.get("dataset_evidence")
        checks["datasets"] = bool(
            isinstance(evidence, Mapping)
            and set(evidence) == set(SYMBOLS)
            and core.get("dataset_evidence_digest") == digest(evidence)
            and all(
                isinstance(evidence.get(symbol), Mapping)
                and set(evidence[symbol]) == set(TIMEFRAMES)
                and all(
                    isinstance(evidence[symbol][timeframe], Mapping)
                    and _HEX64.fullmatch(str(evidence[symbol][timeframe].get("binding_sha256", "")))
                    and type(evidence[symbol][timeframe].get("last_open_time_ms")) is int
                    and evidence[symbol][timeframe].get("last_open_time_ms") > 0
                    and evidence[symbol][timeframe].get("row_count") == 1000
                    and evidence[symbol][timeframe].get("source") == "Bybit"
                    and evidence[symbol][timeframe].get("source_role") == "primary"
                    for timeframe in TIMEFRAMES
                )
                for symbol in SYMBOLS
            )
        )
        rows = core.get("runtime_rows")
        cells = {
            (row.get("symbol"), row.get("profile"))
            for row in rows if isinstance(row, Mapping)
        } if isinstance(rows, list) else set()
        row_shape = bool(
            isinstance(rows, list)
            and len(rows) == 4
            and cells == {(symbol, profile) for symbol in SYMBOLS for profile in PROFILES}
            and core.get("runtime_rows_digest") == digest(rows)
            and core.get("total_runtime_round_trips")
                == sum(int(row.get("closed_round_trips", -1)) for row in rows)
            and all(
                isinstance(row.get("net_return_pct"), (int, float))
                and not isinstance(row.get("net_return_pct"), bool)
                and math.isfinite(float(row.get("net_return_pct")))
                and type(row.get("closed_round_trips")) is int
                and row.get("closed_round_trips") >= 0
                and row.get("trade_count_limit") is None
                and row.get("mechanism") == core.get("mechanism")
                and row.get("config_fingerprint") == core.get("config_fingerprint")
                for row in rows
            )
        )
        checks["runtime_rows"] = row_shape
        total = core.get("total_runtime_round_trips")
        all_positive = bool(row_shape and all(float(row["net_return_pct"]) > 0 for row in rows))
        any_halted = bool(row_shape and any(row.get("halted_on_drawdown") is True for row in rows))
        if row_shape and isinstance(total, int):
            if total == 0:
                expected_decision = "REJECTED_FRESH_RUNTIME"
                expected_reasons = ["ZERO_ACTIVITY"]
                expected_qualified = False
            elif any_halted:
                expected_decision = "REJECTED_FRESH_RUNTIME"
                expected_reasons = ["DRAWDOWN_HALT"]
                expected_qualified = False
            elif not all_positive:
                expected_decision = "REJECTED_FRESH_RUNTIME"
                expected_reasons = ["NON_POSITIVE_RUNTIME_CELL"]
                expected_qualified = False
            else:
                expected_decision = "QUALIFIED_FOR_REVIEW"
                expected_reasons = ["FRESH_RUNTIME_POSITIVE_ACROSS_SYMBOLS_AND_COST_PROFILES"]
                expected_qualified = True
            checks["decision"] = bool(
                core.get("decision") == expected_decision
                and core.get("qualified_for_review") is expected_qualified
                and core.get("reason_codes") == expected_reasons
            )
        else:
            checks["decision"] = False
        checks["authority"] = bool(
            core.get("no_minimum_trade_count_gate") is True
            and core.get("deterministic_replay_verified") is True
            and core.get("data_origin") == "canonical_public_bybit_runtime"
            and core.get("closed_candle_finality_verified") is True
            and core.get("research_only") is True
            and core.get("paper_only") is True
            and core.get("candidate_state_created") is False
            and core.get("qualification_authority") is False
            and core.get("registry_mutation_authority") is False
            and core.get("promotion_authority") is False
            and core.get("paper_execution_authority") is False
            and core.get("automatic_strategy_promotion") is False
            and core.get("live_trading_authority") is False
        )
    except Exception:
        pass
    decision = "pass" if all(checks.values()) else "reject"
    result = {
        "schema_version": VERIFY_SCHEMA,
        "decision": decision,
        "checks": checks,
        "requalification_digest": value.get("requalification_digest"),
    }
    return {**result, "verification_digest": digest(result)}


def build_qa_receipt(
    producer: Mapping[str, Any],
    replay: Mapping[str, Any],
    *,
    producer_lease_id: str,
) -> dict[str, Any]:
    producer_verification = verify_requalification(producer)
    replay_verification = verify_requalification(replay)
    if (
        producer_verification.get("decision") != "pass"
        or replay_verification.get("decision") != "pass"
        or _canonical(producer) != _canonical(replay)
        or not isinstance(producer_lease_id, str)
        or not producer_lease_id
        or len(producer_lease_id) > 160
        or not _SHA40.fullmatch(str(producer.get("execution_source_sha", "")))
        or not _HEX64.fullmatch(str(producer.get("requalification_digest", "")))
        or producer.get("candidate_digest") != replay.get("candidate_digest")
        or producer.get("decision") != replay.get("decision")
    ):
        raise CompositeRuntimeRequalificationError(
            "independent composite runtime QA replay differs from producer"
        )
    core = {
        "schema_version": QA_SCHEMA,
        "producer_lease_id": producer_lease_id,
        "producer_requalification_digest": producer["requalification_digest"],
        "source_sha": producer["execution_source_sha"],
        "candidate_digest": producer["candidate_digest"],
        "decision": producer["decision"],
        "qualified_for_review": producer["qualified_for_review"],
        "evaluation_clock_ms": producer["evaluation_clock_ms"],
        "dataset_evidence_digest": producer["dataset_evidence_digest"],
        "runtime_rows_digest": producer["runtime_rows_digest"],
        "independent_qa_complete": True,
        "qualification_authority": False,
        "registry_mutation_authority": False,
        "promotion_authority": False,
        "paper_execution_authority": False,
        "automatic_strategy_promotion": False,
        "live_trading_authority": False,
    }
    return {**core, "qa_digest": digest(core)}


def verify_qa_receipt(
    receipt: Mapping[str, Any],
    producer: Mapping[str, Any],
    *,
    producer_lease_id: str,
) -> bool:
    try:
        core = dict(receipt)
        claimed = core.pop("qa_digest", None)
        return bool(
            verify_requalification(producer).get("decision") == "pass"
            and claimed == digest(core)
            and receipt.get("schema_version") == QA_SCHEMA
            and receipt.get("producer_lease_id") == producer_lease_id
            and receipt.get("producer_requalification_digest")
                == producer.get("requalification_digest")
            and receipt.get("source_sha") == producer.get("execution_source_sha")
            and receipt.get("candidate_digest") == producer.get("candidate_digest")
            and receipt.get("decision") == producer.get("decision")
            and receipt.get("qualified_for_review") == producer.get("qualified_for_review")
            and receipt.get("evaluation_clock_ms") == producer.get("evaluation_clock_ms")
            and receipt.get("dataset_evidence_digest") == producer.get("dataset_evidence_digest")
            and receipt.get("runtime_rows_digest") == producer.get("runtime_rows_digest")
            and receipt.get("independent_qa_complete") is True
            and receipt.get("qualification_authority") is False
            and receipt.get("registry_mutation_authority") is False
            and receipt.get("promotion_authority") is False
            and receipt.get("paper_execution_authority") is False
            and receipt.get("automatic_strategy_promotion") is False
            and receipt.get("live_trading_authority") is False
        )
    except Exception:
        return False
