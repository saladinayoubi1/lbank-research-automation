"""Fresh canonical VAL-40 requalification for one verified composite candidate.

This module performs no discovery, ranking, qualification, registry mutation,
Runtime/Paper activation, or Live action.  It preserves the exact composite
strategy config selected by independently QA-attested Research and replays only
that config on fresh canonical public Bybit closed candles.

The strongest outcome is QUALIFIED_FOR_REVIEW.  A later independent QA and
QUAL-42 remain mandatory before REG-50 or any Runtime/Paper consideration.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import time
from pathlib import Path
from typing import Any, Callable, Mapping

from nexus_composite_validation_candidate import verify_candidate

SCHEMA = "nexus.composite-runtime-requalification.v1"
VERIFY_SCHEMA = "nexus.composite-runtime-requalification-verification.v1"
SYMBOLS = ("BTCUSDT", "ETHUSDT")
TIMEFRAMES = ("minute15", "hour1", "hour4")
TIMEFRAME_STEP_MS = {
    "minute15": 900_000,
    "hour1": 3_600_000,
    "hour4": 14_400_000,
}
PROFILES = ("conservative", "stress")
HISTORY_LIMIT = 1000
_SHA40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")


class CompositeRuntimeRequalificationError(RuntimeError):
    pass


Evaluator = Callable[[Mapping[str, Any], str, int, Path], list[dict[str, Any]]]


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
    normalized = str(value).strip().lower()
    if not _SHA40.fullmatch(normalized):
        raise CompositeRuntimeRequalificationError(
            "requalification source_sha must be an exact lower-case Git SHA"
        )
    return normalized


def _load_json(path: str | Path) -> dict[str, Any]:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CompositeRuntimeRequalificationError(
            "composite requalification input is unavailable"
        ) from exc
    if not isinstance(value, dict):
        raise CompositeRuntimeRequalificationError(
            "composite requalification input must be an object"
        )
    return value


def _atomic_json(path: str | Path, value: Mapping[str, Any]) -> None:
    target = Path(path).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(
            json.dumps(dict(value), indent=2, sort_keys=True, ensure_ascii=False)
        )
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, target)


def _validated_candidate(
    candidate: Mapping[str, Any],
    verification: Mapping[str, Any],
) -> dict[str, Any]:
    if not isinstance(candidate, Mapping) or not isinstance(verification, Mapping):
        raise CompositeRuntimeRequalificationError(
            "verified composite VAL-40 candidate is required"
        )
    computed = verify_candidate(candidate)
    config = candidate.get("strategy_config")
    if (
        computed.get("decision") != "pass"
        or dict(verification) != computed
        or candidate.get("schema_version") != "nexus.composite-validation-candidate.v2"
        or candidate.get("system_map_node") != "VAL-40"
        or candidate.get("decision") != "FORWARD_TO_VAL40"
        or candidate.get("eligible_for_fresh_runtime_requalification") is not True
        or candidate.get("requires_fresh_runtime_data") is not True
        or not _HEX64.fullmatch(str(candidate.get("candidate_digest", "")))
        or not isinstance(config, Mapping)
        or not config
        or config.get("mechanism") != candidate.get("mechanism")
        or candidate.get("no_minimum_trade_count_gate") is not True
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
            "composite VAL-40 candidate proof or authority is invalid"
        )
    return dict(candidate)


def _finite_number(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise CompositeRuntimeRequalificationError(
            f"runtime profile {field} is not numeric"
        )
    result = float(value)
    if not math.isfinite(result):
        raise CompositeRuntimeRequalificationError(
            f"runtime profile {field} is not finite"
        )
    return result


def _validate_dataset_binding(value: Mapping[str, Any], timeframe: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise CompositeRuntimeRequalificationError(
            f"{timeframe} runtime dataset binding is missing"
        )
    row_count = value.get("row_count")
    first_open = value.get("first_open_time_ms")
    last_open = value.get("last_open_time_ms")
    if (
        value.get("timeframe") != timeframe
        or not _HEX64.fullmatch(str(value.get("binding_sha256", "")))
        or isinstance(row_count, bool)
        or not isinstance(row_count, int)
        or row_count < 60
        or isinstance(first_open, bool)
        or not isinstance(first_open, int)
        or first_open <= 0
        or isinstance(last_open, bool)
        or not isinstance(last_open, int)
        or last_open <= first_open
    ):
        raise CompositeRuntimeRequalificationError(
            f"{timeframe} runtime dataset binding is invalid"
        )
    return dict(value)


def _validate_profile(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping) or value.get("profile") not in PROFILES:
        raise CompositeRuntimeRequalificationError("runtime profile is invalid")
    trades = value.get("closed_round_trips")
    halted = value.get("halted_on_drawdown")
    if (
        isinstance(trades, bool)
        or not isinstance(trades, int)
        or trades < 0
        or not isinstance(halted, bool)
        or value.get("trade_count_limit") is not None
    ):
        raise CompositeRuntimeRequalificationError(
            "runtime profile activity or drawdown state is invalid"
        )
    for field in (
        "net_return_pct", "net_pnl_usdt", "max_drawdown_pct",
        "turnover_usdt", "exposure_bar_ratio", "fee_bps", "slippage_bps",
    ):
        _finite_number(value.get(field), field)
    win_rate = value.get("win_rate_pct")
    profit_factor = value.get("profit_factor")
    if win_rate is not None:
        _finite_number(win_rate, "win_rate_pct")
    if profit_factor is not None:
        _finite_number(profit_factor, "profit_factor")
    if value.get("profit_factor_status") not in {
        "AVAILABLE", "NOT_AVAILABLE_NO_REALIZED_LOSSES"
    }:
        raise CompositeRuntimeRequalificationError(
            "runtime profile profit-factor status is invalid"
        )
    if (
        value.get("concurrent_risk_model")
        != "one_collateral_backed_net_long_per_symbol;10pct_position_budget"
    ):
        raise CompositeRuntimeRequalificationError(
            "runtime profile risk model differs from reviewed composite contract"
        )
    return dict(value)


def _validate_evaluation(
    value: Mapping[str, Any],
    *,
    candidate: Mapping[str, Any],
) -> dict[str, Any]:
    if not isinstance(value, Mapping) or value.get("symbol") not in SYMBOLS:
        raise CompositeRuntimeRequalificationError("runtime symbol evaluation is invalid")
    datasets = value.get("datasets")
    profiles = value.get("profiles")
    if (
        value.get("mechanism") != candidate.get("mechanism")
        or value.get("strategy_config") != candidate.get("strategy_config")
        or not isinstance(datasets, Mapping)
        or set(datasets) != set(TIMEFRAMES)
        or not isinstance(profiles, list)
        or len(profiles) != len(PROFILES)
        or {row.get("profile") for row in profiles if isinstance(row, Mapping)}
            != set(PROFILES)
        or value.get("deterministic_replay_verified") is not True
        or value.get("data_origin") != "canonical_public_bybit_runtime"
        or value.get("closed_candle_finality_verified") is not True
        or value.get("paper_only") is not True
        or value.get("candidate_state_created") is not False
        or value.get("qualification_authority") is not False
        or value.get("registry_mutation_authority") is not False
        or value.get("paper_execution_authority") is not False
        or value.get("automatic_strategy_promotion") is not False
        or value.get("live_trading_authority") is not False
    ):
        raise CompositeRuntimeRequalificationError(
            "runtime composite evaluation contract mismatch"
        )
    clean_datasets = {
        tf: _validate_dataset_binding(datasets[tf], tf)
        for tf in TIMEFRAMES
    }
    clean_profiles = [_validate_profile(row) for row in profiles]
    clean_profiles.sort(key=lambda row: PROFILES.index(row["profile"]))
    result = dict(value)
    result["datasets"] = clean_datasets
    result["profiles"] = clean_profiles
    return result


def _default_evaluator(
    candidate: Mapping[str, Any],
    source_sha: str,
    now_ms: int,
    state_root: Path,
) -> list[dict[str, Any]]:
    """Replay the exact candidate on fresh canonical public Bybit closed candles."""
    del state_root  # reserved for future bounded cache/evidence staging
    from canonical_backtest import canonical_ohlcv_frame
    import nexus_composite_strategy_research as composite
    from product_research_runtime import ProductResearchRuntime

    runtime = ProductResearchRuntime(
        None,  # type: ignore[arg-type]
        source_sha=source_sha,
        clock_ms=lambda: now_ms,
    )
    artifacts: dict[str, dict[str, Mapping[str, Any]]] = {}
    frames: dict[str, dict[str, Any]] = {}
    for symbol in SYMBOLS:
        artifacts[symbol] = {}
        frames[symbol] = {}
        for timeframe in TIMEFRAMES:
            dataset = runtime.fetch_dataset(
                symbol=symbol,
                timeframe=timeframe,
                limit=HISTORY_LIMIT,
            )
            artifact, frame = canonical_ohlcv_frame(dataset)
            artifacts[symbol][timeframe] = artifact
            frames[symbol][timeframe] = frame

    config = dict(candidate["strategy_config"])
    mechanism = str(candidate["mechanism"])
    evaluations: list[dict[str, Any]] = []
    for symbol in SYMBOLS:
        peer_symbol = next(item for item in SYMBOLS if item != symbol)
        peer = (
            frames[peer_symbol]["minute15"]
            if mechanism in composite.PEER_MECHANISMS
            else None
        )
        feature_frame = composite.build_features(
            {
                "minute15": frames[symbol]["minute15"],
                "hour1": frames[symbol]["hour1"],
                "hour4": frames[symbol]["hour4"],
            },
            peer_15m=peer,
        )
        signals = composite.signal_for(feature_frame, config)
        profile_rows: list[dict[str, Any]] = []
        for profile, fee_bps, slip_bps in (
            (
                "conservative",
                composite.ENTRY_FEE_BPS,
                composite.ENTRY_SLIP_BPS,
            ),
            (
                "stress",
                composite.STRESS_FEE_BPS,
                composite.STRESS_SLIP_BPS,
            ),
        ):
            first = composite.backtest(
                feature_frame.reset_index(drop=True),
                signals,
                fee_bps=fee_bps,
                slip_bps=slip_bps,
                risk_variant=int(config["risk_variant"]),
            )
            replay = composite.backtest(
                feature_frame.reset_index(drop=True),
                signals,
                fee_bps=fee_bps,
                slip_bps=slip_bps,
                risk_variant=int(config["risk_variant"]),
            )
            if first != replay:
                raise CompositeRuntimeRequalificationError(
                    f"fresh composite replay is not deterministic for {symbol}/{profile}"
                )
            profile_rows.append({"profile": profile, **first})

        dataset_rows = {}
        for timeframe in TIMEFRAMES:
            artifact = artifacts[symbol][timeframe]
            rows = artifact.get("rows")
            if (
                not isinstance(rows, list)
                or len(rows) < 60
                or not isinstance(rows[0], Mapping)
                or not isinstance(rows[-1], Mapping)
            ):
                raise CompositeRuntimeRequalificationError(
                    f"fresh canonical {symbol}/{timeframe} rows are unavailable"
                )
            dataset_rows[timeframe] = {
                "timeframe": timeframe,
                "binding_sha256": artifact.get("binding_sha256"),
                "row_count": artifact.get("row_count"),
                "first_open_time_ms": rows[0].get("open_time_ms"),
                "last_open_time_ms": rows[-1].get("open_time_ms"),
            }

        evaluations.append({
            "symbol": symbol,
            "mechanism": mechanism,
            "strategy_config": config,
            "datasets": dataset_rows,
            "peer_symbol": peer_symbol if peer is not None else None,
            "peer_minute15_binding_sha256": (
                artifacts[peer_symbol]["minute15"].get("binding_sha256")
                if peer is not None else None
            ),
            "profiles": profile_rows,
            "deterministic_replay_verified": True,
            "data_origin": "canonical_public_bybit_runtime",
            "closed_candle_finality_verified": True,
            "paper_only": True,
            "candidate_state_created": False,
            "qualification_authority": False,
            "registry_mutation_authority": False,
            "paper_execution_authority": False,
            "automatic_strategy_promotion": False,
            "live_trading_authority": False,
        })
    return evaluations


def build_requalification(
    candidate: Mapping[str, Any],
    candidate_verification: Mapping[str, Any],
    *,
    source_sha: str,
    now_ms: int,
    state_root: str | Path,
    evaluator: Evaluator = _default_evaluator,
) -> dict[str, Any]:
    source_sha = _source_sha(source_sha)
    if isinstance(now_ms, bool) or not isinstance(now_ms, int) or now_ms <= 0:
        raise CompositeRuntimeRequalificationError("now_ms must be a positive integer")
    verified_candidate = _validated_candidate(candidate, candidate_verification)
    rows = evaluator(
        verified_candidate,
        source_sha,
        now_ms,
        Path(state_root).resolve(),
    )
    if (
        not isinstance(rows, list)
        or len(rows) != len(SYMBOLS)
        or {row.get("symbol") for row in rows if isinstance(row, Mapping)}
            != set(SYMBOLS)
    ):
        raise CompositeRuntimeRequalificationError(
            "fresh runtime evaluator must return the complete two-symbol grid"
        )
    evaluations = [
        _validate_evaluation(row, candidate=verified_candidate)
        for row in rows
    ]
    evaluations.sort(key=lambda row: SYMBOLS.index(row["symbol"]))

    for timeframe in TIMEFRAMES:
        last_opens = {
            row["datasets"][timeframe]["last_open_time_ms"]
            for row in evaluations
        }
        if len(last_opens) != 1:
            raise CompositeRuntimeRequalificationError(
                f"fresh {timeframe} windows are not aligned across symbols"
            )
        last_open = next(iter(last_opens))
        step_ms = TIMEFRAME_STEP_MS[timeframe]
        age_ms = now_ms - (last_open + step_ms)
        if age_ms < 0 or age_ms >= step_ms:
            raise CompositeRuntimeRequalificationError(
                f"fresh {timeframe} window is not the latest closed canonical candle"
            )

    by_symbol = {row["symbol"]: row for row in evaluations}
    for row in evaluations:
        peer_symbol = row.get("peer_symbol")
        peer_binding = row.get("peer_minute15_binding_sha256")
        if peer_symbol is None:
            if peer_binding is not None:
                raise CompositeRuntimeRequalificationError(
                    "non-peer evaluation cannot carry a peer dataset binding"
                )
            continue
        if (
            peer_symbol not in SYMBOLS
            or peer_symbol == row["symbol"]
            or not _HEX64.fullmatch(str(peer_binding or ""))
            or peer_binding
                != by_symbol[peer_symbol]["datasets"]["minute15"]["binding_sha256"]
        ):
            raise CompositeRuntimeRequalificationError(
                "peer evaluation is not bound to the aligned canonical peer dataset"
            )

    profiles = [
        profile
        for row in evaluations
        for profile in row["profiles"]
    ]
    total_round_trips = sum(int(row["closed_round_trips"]) for row in profiles)
    halted = any(row["halted_on_drawdown"] is True for row in profiles)
    all_positive = all(float(row["net_return_pct"]) > 0.0 for row in profiles)

    if total_round_trips == 0:
        decision = "REJECTED"
        reasons = ["ZERO_ACTIVITY_ON_FRESH_RUNTIME_DATA"]
    elif halted:
        decision = "REJECTED"
        reasons = ["FRESH_RUNTIME_DRAWDOWN_HALT"]
    elif not all_positive:
        decision = "REJECTED"
        reasons = ["NON_POSITIVE_FRESH_RUNTIME_CELL"]
    else:
        decision = "QUALIFIED_FOR_REVIEW"
        reasons = ["FRESH_CANONICAL_RUNTIME_REPLAY_PASSED"]

    core = {
        "schema_version": SCHEMA,
        "system_map_node": "VAL-40",
        "candidate_digest": verified_candidate["candidate_digest"],
        "candidate_source_sha": verified_candidate["source_sha"],
        "requalification_source_sha": source_sha,
        "runtime_as_of_ms": now_ms,
        "mechanism": verified_candidate["mechanism"],
        "timeframe": verified_candidate["timeframe"],
        "strategy_config": dict(verified_candidate["strategy_config"]),
        "config_fingerprint": verified_candidate["config_fingerprint"],
        "decision": decision,
        "reason_codes": reasons,
        "qualified_for_review": decision == "QUALIFIED_FOR_REVIEW",
        "evaluations": evaluations,
        "evaluations_digest": digest(evaluations),
        "total_fresh_runtime_round_trips": total_round_trips,
        "fresh_history_limit_per_timeframe": HISTORY_LIMIT,
        "runtime_data_is_fresh_not_historical_archive": True,
        "historical_archive_reused": False,
        "historical_archive_sha256": verified_candidate["archive_sha256"],
        "candidate": dict(verified_candidate),
        "candidate_verification": dict(candidate_verification),
        "no_minimum_trade_count_gate": True,
        "candidate_state_created": False,
        "qualification_authority": False,
        "registry_mutation_authority": False,
        "promotion_authority": False,
        "paper_execution_authority": False,
        "automatic_strategy_promotion": False,
        "paper_only": True,
        "live_trading_authority": False,
        "private_credentials_used": False,
        "deterministic_risk_final_authority": True,
    }
    return {**core, "requalification_digest": digest(core)}


def verify_requalification(value: Mapping[str, Any]) -> dict[str, Any]:
    checks = {
        "schema": False,
        "digest": False,
        "candidate": False,
        "identity": False,
        "evaluations": False,
        "decision": False,
        "authority": False,
    }
    try:
        core = dict(value)
        claimed = core.pop("requalification_digest", None)
        checks["schema"] = bool(
            core.get("schema_version") == SCHEMA
            and core.get("system_map_node") == "VAL-40"
        )
        checks["digest"] = isinstance(claimed, str) and claimed == digest(core)

        candidate = core.get("candidate")
        candidate_verification = core.get("candidate_verification")
        verified_candidate = _validated_candidate(candidate, candidate_verification)
        checks["candidate"] = True

        checks["identity"] = bool(
            core.get("candidate_digest") == verified_candidate.get("candidate_digest")
            and core.get("candidate_source_sha") == verified_candidate.get("source_sha")
            and _SHA40.fullmatch(str(core.get("requalification_source_sha", "")))
            and type(core.get("runtime_as_of_ms")) is int
            and core.get("runtime_as_of_ms") > 0
            and core.get("mechanism") == verified_candidate.get("mechanism")
            and core.get("timeframe") == verified_candidate.get("timeframe")
            and core.get("strategy_config") == verified_candidate.get("strategy_config")
            and core.get("config_fingerprint") == verified_candidate.get("config_fingerprint")
            and core.get("historical_archive_sha256")
                == verified_candidate.get("archive_sha256")
        )

        rows = core.get("evaluations")
        clean_rows = []
        if isinstance(rows, list) and len(rows) == len(SYMBOLS):
            clean_rows = [
                _validate_evaluation(row, candidate=verified_candidate)
                for row in rows
            ]
            clean_rows.sort(key=lambda row: SYMBOLS.index(row["symbol"]))
        aligned = True
        if len(clean_rows) == len(SYMBOLS):
            by_symbol = {row["symbol"]: row for row in clean_rows}
            as_of_ms = core.get("runtime_as_of_ms")
            for timeframe in TIMEFRAMES:
                last_opens = {
                    row["datasets"][timeframe]["last_open_time_ms"]
                    for row in clean_rows
                }
                if len(last_opens) != 1 or type(as_of_ms) is not int:
                    aligned = False
                    break
                last_open = next(iter(last_opens))
                step_ms = TIMEFRAME_STEP_MS[timeframe]
                age_ms = as_of_ms - (last_open + step_ms)
                if age_ms < 0 or age_ms >= step_ms:
                    aligned = False
                    break
            if aligned:
                for row in clean_rows:
                    peer_symbol = row.get("peer_symbol")
                    peer_binding = row.get("peer_minute15_binding_sha256")
                    if peer_symbol is None:
                        if peer_binding is not None:
                            aligned = False
                            break
                    elif (
                        peer_symbol not in SYMBOLS
                        or peer_symbol == row["symbol"]
                        or not _HEX64.fullmatch(str(peer_binding or ""))
                        or peer_binding
                            != by_symbol[peer_symbol]["datasets"]["minute15"]["binding_sha256"]
                    ):
                        aligned = False
                        break

        checks["evaluations"] = bool(
            len(clean_rows) == len(SYMBOLS)
            and {row["symbol"] for row in clean_rows} == set(SYMBOLS)
            and aligned
            and core.get("evaluations_digest") == digest(clean_rows)
            and core.get("fresh_history_limit_per_timeframe") == HISTORY_LIMIT
            and core.get("runtime_data_is_fresh_not_historical_archive") is True
            and core.get("historical_archive_reused") is False
            and core.get("no_minimum_trade_count_gate") is True
        )

        profile_rows = [
            profile
            for row in clean_rows
            for profile in row["profiles"]
        ]
        total = sum(int(row["closed_round_trips"]) for row in profile_rows)
        halted = any(row["halted_on_drawdown"] is True for row in profile_rows)
        all_positive = bool(profile_rows) and all(
            float(row["net_return_pct"]) > 0.0 for row in profile_rows
        )
        decision = core.get("decision")
        reasons = core.get("reason_codes")
        qualified = core.get("qualified_for_review")
        checks["decision"] = bool(
            core.get("total_fresh_runtime_round_trips") == total
            and (
                (
                    total == 0
                    and decision == "REJECTED"
                    and reasons == ["ZERO_ACTIVITY_ON_FRESH_RUNTIME_DATA"]
                    and qualified is False
                )
                or (
                    total > 0
                    and halted
                    and decision == "REJECTED"
                    and reasons == ["FRESH_RUNTIME_DRAWDOWN_HALT"]
                    and qualified is False
                )
                or (
                    total > 0
                    and not halted
                    and not all_positive
                    and decision == "REJECTED"
                    and reasons == ["NON_POSITIVE_FRESH_RUNTIME_CELL"]
                    and qualified is False
                )
                or (
                    total > 0
                    and not halted
                    and all_positive
                    and decision == "QUALIFIED_FOR_REVIEW"
                    and reasons == ["FRESH_CANONICAL_RUNTIME_REPLAY_PASSED"]
                    and qualified is True
                )
            )
        )
        checks["authority"] = bool(
            core.get("candidate_state_created") is False
            and core.get("qualification_authority") is False
            and core.get("registry_mutation_authority") is False
            and core.get("promotion_authority") is False
            and core.get("paper_execution_authority") is False
            and core.get("automatic_strategy_promotion") is False
            and core.get("paper_only") is True
            and core.get("live_trading_authority") is False
            and core.get("private_credentials_used") is False
            and core.get("deterministic_risk_final_authority") is True
        )
    except Exception:
        pass

    result = {
        "schema_version": VERIFY_SCHEMA,
        "decision": "pass" if all(checks.values()) else "reject",
        "checks": checks,
        "requalification_digest": value.get("requalification_digest"),
    }
    return {**result, "verification_digest": digest(result)}


def run(
    candidate_path: str | Path,
    candidate_verification_path: str | Path,
    *,
    source_sha: str,
    state_root: str | Path,
    output: str | Path,
    now_ms: int | None = None,
) -> dict[str, Any]:
    result = build_requalification(
        _load_json(candidate_path),
        _load_json(candidate_verification_path),
        source_sha=source_sha,
        now_ms=int(time.time() * 1000) if now_ms is None else now_ms,
        state_root=state_root,
    )
    verification = verify_requalification(result)
    if verification.get("decision") != "pass":
        raise CompositeRuntimeRequalificationError(
            "fresh composite requalification verifier rejected evidence"
        )
    target = Path(output).resolve()
    _atomic_json(target, result)
    _atomic_json(target.with_name("verification.json"), verification)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--candidate-verification", type=Path, required=True)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--state-root", type=Path, default=Path("build/composite-val40"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--now-ms", type=int)
    args = parser.parse_args()
    result = run(
        args.candidate,
        args.candidate_verification,
        source_sha=args.source_sha,
        state_root=args.state_root,
        output=args.output,
        now_ms=args.now_ms,
    )
    print(json.dumps({
        "schema_version": result["schema_version"],
        "decision": result["decision"],
        "candidate_digest": result["candidate_digest"],
        "requalification_digest": result["requalification_digest"],
        "paper_only": True,
        "live_trading_authority": False,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
