"""Fresh canonical public-data requalification for composite mechanisms.

Consumes one verified VAL-40 composite candidate. The exact reviewed mechanism
and factory contract are replayed on a fresh bounded Bybit window through the
existing DATA-20/21 ProductResearchRuntime boundary and existing composite
feature/signal/backtest engine.

Passing means only QUALIFIED_FOR_REVIEW. This module never creates Candidate,
QUAL-42, REG-50, Runtime, Paper, automatic promotion, or Live authority.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping
from typing import Any, Callable

import pandas as pd

from canonical_backtest import CanonicalBacktestError, canonical_ohlcv_frame
from nexus_composite_strategy_research import (
    ENTRY_FEE_BPS,
    ENTRY_SLIP_BPS,
    FACTORY_SPECS,
    STRESS_FEE_BPS,
    STRESS_SLIP_BPS,
    backtest,
    build_features,
    signal_for,
)
from nexus_composite_validation_candidate import verify_candidate
from product_research_runtime import ProductResearchError, ProductResearchRuntime

SCHEMA = "nexus.composite-runtime-requalification.v1"
VERIFY_SCHEMA = "nexus.composite-runtime-requalification-verification.v1"
SYMBOLS = ("BTCUSDT", "ETHUSDT")
TIMEFRAMES = ("minute15", "hour1", "hour4")
LIMITS = {"minute15": 960, "hour1": 240, "hour4": 60}
_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")


class CompositeRuntimeRequalificationError(ValueError):
    pass


RuntimeEvaluator = Callable[[Mapping[str, Any], str, int], Mapping[str, Any]]


def _canonical(value: Any) -> bytes:
    try:
        return json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise CompositeRuntimeRequalificationError(
            "composite requalification evidence is not canonical JSON"
        ) from exc


def digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _source_sha(value: str) -> str:
    text = str(value)
    if not _HEX40.fullmatch(text):
        raise CompositeRuntimeRequalificationError(
            "requalification source SHA is invalid"
        )
    return text


def _validate_candidate(
    candidate: Mapping[str, Any],
    candidate_verification: Mapping[str, Any],
) -> dict[str, Any]:
    computed = verify_candidate(candidate)
    if computed.get("decision") != "pass" or dict(candidate_verification) != computed:
        raise CompositeRuntimeRequalificationError(
            "VAL-40 composite candidate verification is missing, stale, or rejected"
        )
    if (
        candidate.get("proposal_kind") != "composite_mechanism"
        or candidate.get("decision") != "FORWARD_TO_VAL40"
        or candidate.get("eligible_for_fresh_runtime_requalification") is not True
        or candidate.get("requires_fresh_runtime_data") is not True
        or candidate.get("research_only") is not True
        or candidate.get("paper_only") is not True
        or candidate.get("candidate_state_created") is not False
        or candidate.get("qualification_authority") is not False
        or candidate.get("registry_mutation_authority") is not False
        or candidate.get("promotion_authority") is not False
        or candidate.get("paper_execution_authority") is not False
        or candidate.get("automatic_strategy_promotion") is not False
        or candidate.get("live_trading_authority") is not False
    ):
        raise CompositeRuntimeRequalificationError(
            "VAL-40 composite candidate authority boundary is invalid"
        )
    config = candidate.get("strategy_config")
    mechanism = candidate.get("mechanism")
    if (
        not isinstance(config, Mapping)
        or set(config) != {
            "mechanism", "risk_variant", "entry_model", "factory_contract_digest",
        }
        or config.get("mechanism") != mechanism
        or mechanism not in FACTORY_SPECS
        or config.get("entry_model") != "closed_4h_1h_15m_next_open"
        or config.get("risk_variant") != 0
        or config.get("factory_contract_digest")
        != FACTORY_SPECS[mechanism]["contract_digest"]
    ):
        raise CompositeRuntimeRequalificationError(
            "composite factory contract changed since Research evidence"
        )
    return dict(candidate)


def _numeric_frame(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    for column in ("open", "high", "low", "close", "volume"):
        try:
            result[column] = pd.to_numeric(result[column], errors="raise")
        except (KeyError, TypeError, ValueError) as exc:
            raise CompositeRuntimeRequalificationError(
                "canonical OHLCV cannot feed composite features"
            ) from exc
    return result


def _profile(result: Mapping[str, Any]) -> dict[str, Any]:
    row = {
        "net_return_pct": result.get("net_return_pct"),
        "max_drawdown_pct": result.get("max_drawdown_pct"),
        "closed_round_trips": result.get("closed_round_trips"),
        "halted_on_drawdown": result.get("halted_on_drawdown"),
        "fee_bps": result.get("fee_bps"),
        "slippage_bps": result.get("slippage_bps"),
        "trade_count_limit": result.get("trade_count_limit"),
    }
    if (
        isinstance(row["net_return_pct"], bool)
        or not isinstance(row["net_return_pct"], (int, float))
        or not math.isfinite(float(row["net_return_pct"]))
        or isinstance(row["max_drawdown_pct"], bool)
        or not isinstance(row["max_drawdown_pct"], (int, float))
        or not math.isfinite(float(row["max_drawdown_pct"]))
        or isinstance(row["closed_round_trips"], bool)
        or not isinstance(row["closed_round_trips"], int)
        or row["closed_round_trips"] < 0
        or row["halted_on_drawdown"] not in {True, False}
        or row["trade_count_limit"] is not None
    ):
        raise CompositeRuntimeRequalificationError(
            "composite runtime profile is incomplete or capped"
        )
    return row


def _default_evaluator(
    candidate: Mapping[str, Any],
    source_sha: str,
    now_ms: int,
) -> dict[str, Any]:
    """Fetch one immutable current window and deterministically replay it twice."""
    if isinstance(now_ms, bool) or not isinstance(now_ms, int) or now_ms <= 0:
        raise CompositeRuntimeRequalificationError(
            "runtime anchor must be positive integer"
        )
    source_sha = _source_sha(source_sha)
    config = dict(candidate["strategy_config"])
    mechanism = str(candidate["mechanism"])
    spec = FACTORY_SPECS.get(mechanism)
    if (
        spec is None
        or spec["contract_digest"] != config["factory_contract_digest"]
        or spec["peer_required"] not in {True, False}
    ):
        raise CompositeRuntimeRequalificationError(
            "current composite mechanism contract does not match candidate"
        )

    runtime = ProductResearchRuntime(
        None,  # type: ignore[arg-type]
        source_sha=source_sha,
        clock_ms=lambda: now_ms,
    )
    frames: dict[str, dict[str, pd.DataFrame]] = {}
    bindings: dict[str, dict[str, Any]] = {}
    for symbol in SYMBOLS:
        frames[symbol] = {}
        bindings[symbol] = {}
        for timeframe in TIMEFRAMES:
            limit = LIMITS[timeframe]
            dataset = runtime.fetch_dataset(
                symbol=symbol, timeframe=timeframe, limit=limit
            )
            artifact, frame = canonical_ohlcv_frame(dataset)
            if artifact.get("row_count") != limit or len(frame) != limit:
                raise ProductResearchError(
                    f"canonical {symbol} {timeframe} window is incomplete"
                )
            rows = artifact.get("rows")
            if (
                not isinstance(rows, list)
                or not rows
                or not isinstance(rows[-1], Mapping)
            ):
                raise ProductResearchError("canonical runtime rows are unavailable")
            binding = str(artifact.get("binding_sha256", ""))
            last_open = rows[-1].get("open_time_ms")
            if (
                not _HEX64.fullmatch(binding)
                or isinstance(last_open, bool)
                or not isinstance(last_open, int)
                or last_open <= 0
            ):
                raise ProductResearchError("canonical runtime binding is invalid")
            frames[symbol][timeframe] = _numeric_frame(frame)
            bindings[symbol][timeframe] = {
                "binding_sha256": binding,
                "last_open_time_ms": last_open,
                "row_count": limit,
            }

    def run_once() -> list[dict[str, Any]]:
        evaluations: list[dict[str, Any]] = []
        for symbol in SYMBOLS:
            peer_symbol = SYMBOLS[1] if symbol == SYMBOLS[0] else SYMBOLS[0]
            feature_frame = build_features(
                frames[symbol],
                peer_15m=(
                    frames[peer_symbol]["minute15"]
                    if spec["peer_required"] is True
                    else None
                ),
            )
            signals = signal_for(feature_frame, config)
            conservative = _profile(
                backtest(
                    feature_frame,
                    signals,
                    fee_bps=ENTRY_FEE_BPS,
                    slip_bps=ENTRY_SLIP_BPS,
                    risk_variant=config["risk_variant"],
                )
            )
            stress = _profile(
                backtest(
                    feature_frame,
                    signals,
                    fee_bps=STRESS_FEE_BPS,
                    slip_bps=STRESS_SLIP_BPS,
                    risk_variant=config["risk_variant"],
                )
            )
            profiles = {"conservative": conservative, "stress": stress}
            total_trades = sum(
                int(row["closed_round_trips"]) for row in profiles.values()
            )
            reasons: list[str] = []
            if total_trades == 0:
                reasons.append("ZERO_ACTIVITY")
            if any(
                row["halted_on_drawdown"] is True for row in profiles.values()
            ):
                reasons.append("DRAWDOWN_HALT")
            if any(
                float(row["net_return_pct"]) <= 0.0 for row in profiles.values()
            ):
                reasons.append("NON_POSITIVE_FRESH_RUNTIME_PROFILE")
            status = "paper_candidate" if not reasons else "killed"
            evaluations.append(
                {
                    "symbol": symbol,
                    "timeframe": "minute15_with_completed_1h_4h",
                    "dataset_windows": dict(bindings[symbol]),
                    "profiles": profiles,
                    "total_closed_round_trips": total_trades,
                    "qualification_status": status,
                    "kill_reasons": reasons,
                    "deterministic_replay_verified": True,
                    "closed_candle_finality_verified": True,
                    "data_origin": "canonical_public_bybit_runtime",
                    "paper_only": True,
                    "live_trading_authority": False,
                    "paper_execution_started": False,
                    "automatic_strategy_promotion": False,
                }
            )
        return evaluations

    first = run_once()
    second = run_once()
    if _canonical(first) != _canonical(second):
        raise CompositeRuntimeRequalificationError(
            "fresh composite runtime replay is not deterministic"
        )
    return {
        "runtime_anchor_ms": now_ms,
        "mechanism_contract_digest": spec["contract_digest"],
        "peer_required": spec["peer_required"],
        "evaluations": first,
        "deterministic_replay_verified": True,
    }


def _validate_profile(row: Mapping[str, Any], *, stress: bool) -> bool:
    try:
        return bool(
            isinstance(row, Mapping)
            and isinstance(row.get("net_return_pct"), (int, float))
            and not isinstance(row.get("net_return_pct"), bool)
            and math.isfinite(float(row.get("net_return_pct")))
            and isinstance(row.get("max_drawdown_pct"), (int, float))
            and not isinstance(row.get("max_drawdown_pct"), bool)
            and math.isfinite(float(row.get("max_drawdown_pct")))
            and isinstance(row.get("closed_round_trips"), int)
            and not isinstance(row.get("closed_round_trips"), bool)
            and row.get("closed_round_trips") >= 0
            and row.get("halted_on_drawdown") in {True, False}
            and row.get("trade_count_limit") is None
            and float(row.get("fee_bps"))
            == (STRESS_FEE_BPS if stress else ENTRY_FEE_BPS)
            and float(row.get("slippage_bps"))
            == (STRESS_SLIP_BPS if stress else ENTRY_SLIP_BPS)
        )
    except (TypeError, ValueError):
        return False


def _validate_runtime_result(
    value: Mapping[str, Any],
    candidate: Mapping[str, Any],
    *,
    now_ms: int,
) -> dict[str, Any]:
    row = dict(value)
    mechanism = candidate["mechanism"]
    spec = FACTORY_SPECS[mechanism]
    evaluations = row.get("evaluations")
    if (
        row.get("runtime_anchor_ms") != now_ms
        or row.get("mechanism_contract_digest") != spec["contract_digest"]
        or row.get("peer_required") is not spec["peer_required"]
        or row.get("deterministic_replay_verified") is not True
        or not isinstance(evaluations, list)
        or len(evaluations) != len(SYMBOLS)
        or {
            item.get("symbol")
            for item in evaluations
            if isinstance(item, Mapping)
        }
        != set(SYMBOLS)
    ):
        raise CompositeRuntimeRequalificationError(
            "fresh composite runtime result contract mismatch"
        )

    for evaluation in evaluations:
        if not isinstance(evaluation, Mapping):
            raise CompositeRuntimeRequalificationError(
                "runtime evaluation is malformed"
            )
        windows = evaluation.get("dataset_windows")
        profiles = evaluation.get("profiles")
        if (
            evaluation.get("timeframe")
            != "minute15_with_completed_1h_4h"
            or not isinstance(windows, Mapping)
            or set(windows) != set(TIMEFRAMES)
            or not isinstance(profiles, Mapping)
            or set(profiles) != {"conservative", "stress"}
            or not _validate_profile(profiles["conservative"], stress=False)
            or not _validate_profile(profiles["stress"], stress=True)
            or evaluation.get("qualification_status")
            not in {"paper_candidate", "killed"}
            or not isinstance(evaluation.get("kill_reasons"), list)
            or any(
                not isinstance(reason, str)
                for reason in evaluation.get("kill_reasons", [])
            )
            or evaluation.get("deterministic_replay_verified") is not True
            or evaluation.get("closed_candle_finality_verified") is not True
            or evaluation.get("data_origin")
            != "canonical_public_bybit_runtime"
            or evaluation.get("paper_only") is not True
            or evaluation.get("live_trading_authority") is not False
            or evaluation.get("paper_execution_started") is not False
            or evaluation.get("automatic_strategy_promotion") is not False
        ):
            raise CompositeRuntimeRequalificationError(
                "runtime evaluation authority or profile binding failed"
            )

        for timeframe in TIMEFRAMES:
            window = windows.get(timeframe)
            if (
                not isinstance(window, Mapping)
                or not _HEX64.fullmatch(str(window.get("binding_sha256", "")))
                or isinstance(window.get("last_open_time_ms"), bool)
                or not isinstance(window.get("last_open_time_ms"), int)
                or window.get("last_open_time_ms") <= 0
                or window.get("row_count") != LIMITS[timeframe]
            ):
                raise CompositeRuntimeRequalificationError(
                    "runtime dataset window binding failed"
                )

        expected_total = sum(
            int(profile["closed_round_trips"])
            for profile in profiles.values()
        )
        expected_reasons: list[str] = []
        if expected_total == 0:
            expected_reasons.append("ZERO_ACTIVITY")
        if any(
            profile["halted_on_drawdown"] is True
            for profile in profiles.values()
        ):
            expected_reasons.append("DRAWDOWN_HALT")
        if any(
            float(profile["net_return_pct"]) <= 0.0
            for profile in profiles.values()
        ):
            expected_reasons.append("NON_POSITIVE_FRESH_RUNTIME_PROFILE")
        if (
            evaluation.get("total_closed_round_trips") != expected_total
            or list(evaluation["kill_reasons"]) != expected_reasons
            or (
                evaluation["qualification_status"] == "paper_candidate"
            )
            != (not expected_reasons)
        ):
            raise CompositeRuntimeRequalificationError(
                "runtime qualification result is internally inconsistent"
            )
    return row


def build_requalification(
    candidate: Mapping[str, Any],
    candidate_verification: Mapping[str, Any],
    *,
    source_sha: str,
    now_ms: int,
    evaluator: RuntimeEvaluator = _default_evaluator,
) -> dict[str, Any]:
    candidate_row = _validate_candidate(candidate, candidate_verification)
    source_sha = _source_sha(source_sha)
    if isinstance(now_ms, bool) or not isinstance(now_ms, int) or now_ms <= 0:
        raise CompositeRuntimeRequalificationError(
            "now_ms must be a positive integer"
        )

    blocked: dict[str, Any] | None = None
    runtime: dict[str, Any] | None = None
    try:
        runtime = _validate_runtime_result(
            evaluator(candidate_row, source_sha, now_ms),
            candidate_row,
            now_ms=now_ms,
        )
    except (ProductResearchError, CanonicalBacktestError) as exc:
        blocked = {
            "error_type": type(exc).__name__,
            "error_digest": digest(
                {"type": type(exc).__name__, "message": str(exc)}
            ),
        }

    if blocked is not None:
        verdict = "BLOCKED_RUNTIME_DATA"
        evaluations: list[dict[str, Any]] = []
        contract_digest = FACTORY_SPECS[candidate_row["mechanism"]][
            "contract_digest"
        ]
        peer_required = FACTORY_SPECS[candidate_row["mechanism"]][
            "peer_required"
        ]
        deterministic = False
    else:
        assert runtime is not None
        evaluations = list(runtime["evaluations"])
        verdict = (
            "QUALIFIED_FOR_REVIEW"
            if all(
                row["qualification_status"] == "paper_candidate"
                for row in evaluations
            )
            else "REJECTED"
        )
        contract_digest = runtime["mechanism_contract_digest"]
        peer_required = runtime["peer_required"]
        deterministic = runtime["deterministic_replay_verified"]

    core = {
        "schema_version": SCHEMA,
        "system_map_node": "VAL-40",
        "source_sha": source_sha,
        "candidate_source_sha": candidate_row["source_sha"],
        "candidate_digest": candidate_row["candidate_digest"],
        "candidate_verification_digest":
            candidate_verification["verification_digest"],
        "candidate": dict(candidate_row),
        "candidate_verification": dict(candidate_verification),
        "proposal_kind": "composite_mechanism",
        "mechanism": candidate_row["mechanism"],
        "strategy_config": dict(candidate_row["strategy_config"]),
        "config_fingerprint": candidate_row["config_fingerprint"],
        "mechanism_contract_digest": contract_digest,
        "peer_required": peer_required,
        "runtime_anchor_ms": now_ms,
        "deterministic_replay_verified": deterministic,
        "verdict": verdict,
        "runtime_evaluations": evaluations,
        "blocked": blocked,
        "candidate_state_created": False,
        "qualification_authority": False,
        "registry_mutation_authority": False,
        "promotion_authority": False,
        "paper_execution_started": False,
        "automatic_strategy_promotion": False,
        "research_only": True,
        "paper_only": True,
        "live_trading_authority": False,
    }
    return {**core, "requalification_digest": digest(core)}


def verify_requalification(value: Mapping[str, Any]) -> dict[str, Any]:
    checks = {
        "schema": False,
        "digest": False,
        "candidate": False,
        "runtime": False,
        "verdict": False,
        "authority": False,
    }
    try:
        core = dict(value)
        claimed = core.pop("requalification_digest", None)
        checks["schema"] = bool(
            core.get("schema_version") == SCHEMA
            and core.get("system_map_node") == "VAL-40"
            and core.get("proposal_kind") == "composite_mechanism"
            and _HEX40.fullmatch(str(core.get("source_sha", "")))
        )
        checks["digest"] = isinstance(claimed, str) and claimed == digest(core)

        candidate = core.get("candidate")
        candidate_verification = core.get("candidate_verification")
        computed_candidate = (
            verify_candidate(candidate)
            if isinstance(candidate, Mapping)
            else {}
        )
        checks["candidate"] = bool(
            isinstance(candidate, Mapping)
            and isinstance(candidate_verification, Mapping)
            and computed_candidate.get("decision") == "pass"
            and dict(candidate_verification) == computed_candidate
            and core.get("candidate_digest")
            == candidate.get("candidate_digest")
            and core.get("candidate_source_sha")
            == candidate.get("source_sha")
            and core.get("candidate_verification_digest")
            == candidate_verification.get("verification_digest")
            and core.get("mechanism") == candidate.get("mechanism")
            and core.get("strategy_config")
            == candidate.get("strategy_config")
            and core.get("config_fingerprint")
            == candidate.get("config_fingerprint")
            and core.get("mechanism_contract_digest")
            == FACTORY_SPECS[candidate["mechanism"]]["contract_digest"]
            and core.get("peer_required")
            is FACTORY_SPECS[candidate["mechanism"]]["peer_required"]
        )

        evaluations = core.get("runtime_evaluations")
        blocked = core.get("blocked")
        if (
            isinstance(candidate, Mapping)
            and isinstance(evaluations, list)
            and evaluations
        ):
            runtime_payload = {
                "runtime_anchor_ms": core.get("runtime_anchor_ms"),
                "mechanism_contract_digest":
                    FACTORY_SPECS[candidate["mechanism"]]["contract_digest"],
                "peer_required":
                    FACTORY_SPECS[candidate["mechanism"]]["peer_required"],
                "evaluations": evaluations,
                "deterministic_replay_verified":
                    core.get("deterministic_replay_verified"),
            }
            _validate_runtime_result(
                runtime_payload,
                candidate,
                now_ms=int(core["runtime_anchor_ms"]),
            )
            runtime_ok = blocked is None
        else:
            runtime_ok = bool(
                core.get("verdict") == "BLOCKED_RUNTIME_DATA"
                and evaluations == []
                and core.get("deterministic_replay_verified") is False
                and isinstance(blocked, Mapping)
                and isinstance(blocked.get("error_type"), str)
                and _HEX64.fullmatch(str(blocked.get("error_digest", "")))
            )
        checks["runtime"] = runtime_ok

        verdict = core.get("verdict")
        checks["verdict"] = bool(
            (
                verdict == "QUALIFIED_FOR_REVIEW"
                and isinstance(evaluations, list)
                and len(evaluations) == len(SYMBOLS)
                and all(
                    row.get("qualification_status") == "paper_candidate"
                    for row in evaluations
                )
                and core.get("deterministic_replay_verified") is True
                and blocked is None
            )
            or (
                verdict == "REJECTED"
                and isinstance(evaluations, list)
                and len(evaluations) == len(SYMBOLS)
                and any(
                    row.get("qualification_status") == "killed"
                    for row in evaluations
                )
                and core.get("deterministic_replay_verified") is True
                and blocked is None
            )
            or (
                verdict == "BLOCKED_RUNTIME_DATA"
                and evaluations == []
                and isinstance(blocked, Mapping)
            )
        )
        checks["authority"] = bool(
            core.get("candidate_state_created") is False
            and core.get("qualification_authority") is False
            and core.get("registry_mutation_authority") is False
            and core.get("promotion_authority") is False
            and core.get("paper_execution_started") is False
            and core.get("automatic_strategy_promotion") is False
            and core.get("research_only") is True
            and core.get("paper_only") is True
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
