from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import math
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd

from bybit_derivatives_core_v1 import (
    Client,
    InstrumentSpec,
    Position,
    RiskTier,
    adverse_fill_price,
    apply_trade,
    fetch_funding,
    fetch_instrument,
    fetch_risk_tiers,
    funding_cashflow,
    margin_requirements,
    minute_vwap,
    normalized_target_quantity,
    unrealized,
)
from bybit_derivatives_validation_v1 import frozen_weights


SCHEMA = "nexus.bybit-prospective-paper-forward.v1"
EVENT_SCHEMA = "nexus.bybit-prospective-paper-forward-event.v1"
BAR_MS = 4 * 60 * 60 * 1000
SYMBOLS = ("BTCUSDT", "ETHUSDT")


class ProspectivePaperError(RuntimeError):
    pass


def _canonical(value: Any) -> bytes:
    try:
        return json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ProspectivePaperError("paper-forward evidence is not canonical JSON") from exc


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _utc(value: str) -> pd.Timestamp:
    stamp = pd.Timestamp(value)
    if stamp.tzinfo is None:
        raise ProspectivePaperError("paper-forward timestamps must include UTC")
    return stamp.tz_convert("UTC")


def _utc_text(value: pd.Timestamp) -> str:
    return value.tz_convert("UTC").isoformat().replace("+00:00", "Z")


def _require_complete_grid(
    frame: pd.DataFrame, *, start_ms: int, end_ms: int, label: str
) -> None:
    actual = [int(value.timestamp() * 1000) for value in frame["timestamp"]]
    expected = list(range(start_ms, end_ms, BAR_MS))
    if actual != expected:
        raise ProspectivePaperError(
            f"public {label} history is incomplete or off the 4h UTC grid"
        )


def load_contract(path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    try:
        config = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ProspectivePaperError(f"paper-forward manifest unavailable: {exc}") from exc
    required = {
        "schema_version", "forward_id", "strategy_manifest", "strategy_id",
        "strategy_manifest_sha256", "start_not_before_utc", "minimum_observation_days",
        "minimum_completed_bars", "linear_symbols", "spot_symbols", "timeframe",
        "warmup_days", "api_base_urls", "timeout_seconds", "maximum_attempts",
        "request_pause_seconds", "evidence_prerequisites", "execution_profiles",
        "completion_gates", "authority",
    }
    if not isinstance(config, dict) or set(config) != required or config["schema_version"] != 1:
        raise ProspectivePaperError("paper-forward manifest schema mismatch")
    if tuple(config["linear_symbols"]) != SYMBOLS or tuple(config["spot_symbols"]) != SYMBOLS:
        raise ProspectivePaperError("paper-forward symbol tuple changed")
    if config["timeframe"] != "240" or int(config["warmup_days"]) < 240:
        raise ProspectivePaperError("paper-forward timeframe or warmup is invalid")
    if set(config["execution_profiles"]) != {"conservative", "stress"}:
        raise ProspectivePaperError("both locked execution profiles are required")
    if set(config["completion_gates"]) != {"conservative", "stress"}:
        raise ProspectivePaperError("both locked completion gates are required")
    if config["authority"] != {
        "paper_only": True,
        "live_trading_enabled": False,
        "private_credentials_allowed": False,
        "automatic_live_promotion": False,
    }:
        raise ProspectivePaperError("paper-forward authority widened beyond Paper")
    _utc(config["start_not_before_utc"])
    frozen_path = (path.parent.parent / config["strategy_manifest"]).resolve()
    if _file_sha(frozen_path) != config["strategy_manifest_sha256"]:
        raise ProspectivePaperError("frozen strategy manifest digest mismatch")
    frozen = json.loads(frozen_path.read_text(encoding="utf-8"))
    if frozen.get("strategy_id") != config["strategy_id"]:
        raise ProspectivePaperError("frozen strategy identity mismatch")
    if frozen.get("promotion_policy", {}).get("automatic_paper_forward") is not False:
        raise ProspectivePaperError("frozen strategy promotion boundary changed")
    if frozen.get("promotion_policy", {}).get("live_trading") is not False:
        raise ProspectivePaperError("frozen strategy live boundary changed")
    return config, frozen


def _position_rows() -> list[dict[str, float]]:
    return [
        {"quantity": 0.0, "average_entry": 0.0},
        {"quantity": 0.0, "average_entry": 0.0},
    ]


def new_state(
    config: Mapping[str, Any], *, engine_sha256: str, source_sha: str, run_id: int
) -> dict[str, Any]:
    profiles = {}
    for name, profile in config["execution_profiles"].items():
        initial = float(profile["initial_cash"])
        profiles[name] = {
            "wallet": initial,
            "equity": initial,
            "equity_high": initial,
            "maximum_drawdown": 0.0,
            "positions": _position_rows(),
            "target_weights": [0.0, 0.0],
            "fill_count": 0,
            "asset_fill_counts": [0, 0],
            "orders": 0,
            "execution_hits": 0,
            "expected_funding_events": 0,
            "actual_funding_events": 0,
            "margin_rejections": 0,
            "liquidations": 0,
            "maximum_margin_utilization": 0.0,
            "maximum_risk_tier_utilization": 0.0,
            "fees": 0.0,
            "funding_cashflow": 0.0,
        }
    core = {
        "schema_version": SCHEMA,
        "forward_id": config["forward_id"],
        "strategy_id": config["strategy_id"],
        "strategy_manifest_sha256": config["strategy_manifest_sha256"],
        "engine_sha256": engine_sha256,
        "start_not_before_utc": config["start_not_before_utc"],
        "last_execution_utc": None,
        "last_run_id": int(run_id),
        "latest_source_sha": source_sha,
        "completed_bar_count": 0,
        "events": [],
        "profiles": profiles,
        "status": "WAITING_FOR_FIRST_PROSPECTIVE_BAR",
        "decision": "collect_prospective_paper_evidence",
        "paper_only": True,
        "live_trading_enabled": False,
        "private_credentials_used": False,
        "automatic_live_promotion": False,
    }
    return {**core, "state_digest": _digest(core)}


def verify_state(state: Mapping[str, Any], config: Mapping[str, Any], engine_sha256: str) -> None:
    if not isinstance(state, Mapping):
        raise ProspectivePaperError("paper-forward state must be an object")
    core = dict(state)
    claimed = core.pop("state_digest", None)
    if claimed != _digest(core):
        raise ProspectivePaperError("paper-forward state digest mismatch")
    checks = {
        "schema": state.get("schema_version") == SCHEMA,
        "forward": state.get("forward_id") == config["forward_id"],
        "strategy": state.get("strategy_id") == config["strategy_id"],
        "manifest": state.get("strategy_manifest_sha256") == config["strategy_manifest_sha256"],
        "engine": state.get("engine_sha256") == engine_sha256,
        "paper": state.get("paper_only") is True,
        "live": state.get("live_trading_enabled") is False,
        "credentials": state.get("private_credentials_used") is False,
        "promotion": state.get("automatic_live_promotion") is False,
        "profiles": set(state.get("profiles", {})) == {"conservative", "stress"},
    }
    if not all(checks.values()):
        raise ProspectivePaperError(f"paper-forward state contract rejected: {checks}")
    events = state.get("events", [])
    if not isinstance(events, list) or len(events) != int(state.get("completed_bar_count", -1)):
        raise ProspectivePaperError("paper-forward event count is inconsistent")
    previous = "0" * 64
    for sequence, event in enumerate(events, start=1):
        unsigned = dict(event)
        event_digest = unsigned.pop("event_digest", None)
        if (
            unsigned.get("schema_version") != EVENT_SCHEMA
            or unsigned.get("sequence") != sequence
            or unsigned.get("previous_event_digest") != previous
            or event_digest != _digest(unsigned)
            or unsigned.get("paper_only") is not True
            or unsigned.get("live_trading_enabled") is not False
        ):
            raise ProspectivePaperError("paper-forward event chain rejected")
        previous = event_digest
    if events:
        if state.get("last_execution_utc") != events[-1].get("execution_utc"):
            raise ProspectivePaperError("paper-forward last execution is inconsistent")
    elif state.get("last_execution_utc") is not None:
        raise ProspectivePaperError("paper-forward empty chain has a last execution")


def _fetch_klines(
    client: Client,
    *,
    category: str,
    endpoint: str,
    symbol: str,
    start_ms: int,
    end_ms: int,
    include_volume: bool = False,
) -> pd.DataFrame:
    rows: dict[int, list[Any]] = {}
    cursor = end_ms - 1
    while cursor >= start_ms:
        batch = client.get(endpoint, {
            "category": category,
            "symbol": symbol,
            "interval": "240",
            "start": start_ms,
            "end": cursor,
            "limit": 1000,
        })["result"].get("list", [])
        if not batch:
            break
        for item in batch:
            stamp = int(item[0])
            if start_ms <= stamp < end_ms:
                rows[stamp] = item
        oldest = min(int(item[0]) for item in batch)
        if oldest <= start_ms:
            break
        if oldest >= cursor:
            raise ProspectivePaperError(f"kline pagination stalled for {category}:{symbol}")
        cursor = oldest - 1
    if not rows:
        raise ProspectivePaperError(f"no public {category} rows for {symbol}")
    items = [rows[key] for key in sorted(rows)]
    data: dict[str, Any] = {
        "timestamp": pd.to_datetime([int(x[0]) for x in items], unit="ms", utc=True),
        "open": [float(x[1]) for x in items],
        "high": [float(x[2]) for x in items],
        "low": [float(x[3]) for x in items],
        "close": [float(x[4]) for x in items],
    }
    if include_volume:
        data["volume"] = [float(x[5]) for x in items]
        data["turnover"] = [float(x[6]) for x in items]
    return pd.DataFrame(data)


def _minute_window(client: Client, symbol: str, timestamp: pd.Timestamp, minutes: int) -> list[dict[str, float]]:
    start = int(timestamp.timestamp() * 1000)
    batch = client.get("/v5/market/kline", {
        "category": "linear", "symbol": symbol, "interval": "1",
        "start": start, "end": start + minutes * 60_000 - 1, "limit": minutes,
    })["result"].get("list", [])
    ordered = sorted(batch, key=lambda item: int(item[0]))
    expected = [start + offset * 60_000 for offset in range(minutes)]
    if [int(item[0]) for item in ordered] != expected:
        return []
    return [
        {"volume": float(x[5]), "turnover": float(x[6])}
        for x in ordered
    ]


def collect_observations(
    config: Mapping[str, Any],
    frozen: Mapping[str, Any],
    state: Mapping[str, Any],
    *,
    now_utc: str,
    client: Client | None = None,
) -> list[dict[str, Any]]:
    now = _utc(now_utc)
    latest_closed_open_ms = ((int(now.timestamp() * 1000) - BAR_MS) // BAR_MS) * BAR_MS
    if latest_closed_open_ms <= 0:
        raise ProspectivePaperError("no completed 4h bar is available")
    start = _utc(config["start_not_before_utc"])
    warmup_start = start - pd.Timedelta(days=int(config["warmup_days"]))
    end_ms = latest_closed_open_ms + BAR_MS
    api = client or Client(
        list(config["api_base_urls"]), float(config["timeout_seconds"]),
        int(config["maximum_attempts"]), float(config["request_pause_seconds"]),
    )
    spot_frames = {
        symbol: _fetch_klines(
            api, category="spot", endpoint="/v5/market/kline", symbol=symbol,
            start_ms=int(warmup_start.timestamp() * 1000), end_ms=end_ms,
            include_volume=True,
        )
        for symbol in SYMBOLS
    }
    for symbol, frame in spot_frames.items():
        _require_complete_grid(
            frame,
            start_ms=int(warmup_start.timestamp() * 1000),
            end_ms=end_ms,
            label=f"Spot {symbol}",
        )
    timestamps = spot_frames[SYMBOLS[0]]["timestamp"]
    if not timestamps.equals(spot_frames[SYMBOLS[1]]["timestamp"]):
        raise ProspectivePaperError("public Spot BTC/ETH history is not aligned")
    spot = {
        "timestamps": timestamps,
        "close": np.column_stack([spot_frames[symbol]["close"].to_numpy(float) for symbol in SYMBOLS]),
    }
    weights = frozen_weights(spot, dict(frozen))
    linear_start_ms = int((start - pd.Timedelta(hours=4)).timestamp() * 1000)
    trade = {
        symbol: _fetch_klines(
            api, category="linear", endpoint="/v5/market/kline", symbol=symbol,
            start_ms=linear_start_ms, end_ms=end_ms, include_volume=True,
        )
        for symbol in SYMBOLS
    }
    mark = {
        symbol: _fetch_klines(
            api, category="linear", endpoint="/v5/market/mark-price-kline", symbol=symbol,
            start_ms=linear_start_ms, end_ms=end_ms,
        )
        for symbol in SYMBOLS
    }
    for kind, frames in (("trade", trade), ("mark", mark)):
        for symbol, frame in frames.items():
            _require_complete_grid(
                frame,
                start_ms=linear_start_ms,
                end_ms=end_ms,
                label=f"linear {kind} {symbol}",
            )
    specs = [fetch_instrument(api, symbol) for symbol in SYMBOLS]
    tiers = [fetch_risk_tiers(api, symbol) for symbol in SYMBOLS]
    funding = [fetch_funding(api, symbol, linear_start_ms, end_ms) for symbol in SYMBOLS]
    spot_index = {int(stamp.timestamp() * 1000): index for index, stamp in enumerate(timestamps)}
    last = _utc(state["last_execution_utc"]) if state["last_execution_utc"] else None
    prior_targets = list(state["profiles"]["conservative"]["target_weights"])
    observations: list[dict[str, Any]] = []
    trade_indexes = [frame.set_index("timestamp") for frame in trade.values()]
    mark_indexes = [frame.set_index("timestamp") for frame in mark.values()]
    common_times = trade_indexes[0].index.intersection(trade_indexes[1].index)
    common_times = common_times.intersection(mark_indexes[0].index).intersection(mark_indexes[1].index)
    for execution_time in common_times.sort_values():
        execution_time = pd.Timestamp(execution_time)
        if execution_time < start or (last is not None and execution_time <= last):
            continue
        signal_open_ms = int(execution_time.timestamp() * 1000) - BAR_MS
        signal_index = spot_index.get(signal_open_ms)
        if signal_index is None:
            raise ProspectivePaperError("prospective signal has no aligned Spot predecessor")
        target = [float(x) for x in weights[signal_index].tolist()]
        if any(not math.isfinite(x) or abs(x) > 1.0 + 1e-9 for x in target):
            raise ProspectivePaperError("frozen strategy emitted invalid target weights")
        if sum(abs(x) for x in target) > 1.0 + 1e-9:
            raise ProspectivePaperError("frozen strategy exceeded gross exposure ceiling")
        changed = not np.allclose(target, prior_targets, atol=1e-12, rtol=0.0)
        minute_windows: dict[str, dict[str, list[dict[str, float]]]] = {}
        if changed:
            for symbol in SYMBOLS:
                minute_windows[symbol] = {
                    name: _minute_window(api, symbol, execution_time, int(profile["execution_window_minutes"]))
                    for name, profile in config["execution_profiles"].items()
                }
        previous_time = last or execution_time - pd.Timedelta(hours=4)
        funding_rows = []
        expected_funding_events = []
        for asset, frame in enumerate(funding):
            selected = frame[(frame["timestamp"] > previous_time) & (frame["timestamp"] <= execution_time)]
            funding_rows.append([float(x) for x in selected["funding_rate"].tolist()])
            interval_ms = int(specs[asset].funding_interval_minutes) * 60_000
            previous_ms = int(previous_time.timestamp() * 1000)
            execution_ms = int(execution_time.timestamp() * 1000)
            expected_funding_events.append(execution_ms // interval_ms - previous_ms // interval_ms)
        observations.append({
            "execution_utc": _utc_text(execution_time),
            "signal_close_utc": _utc_text(execution_time),
            "target_weights": target,
            "target_changed": changed,
            "trade": [
                {key: float(trade_indexes[i].loc[execution_time][key]) for key in ("open", "close")}
                for i in range(2)
            ],
            "mark": [
                {key: float(mark_indexes[i].loc[execution_time][key]) for key in ("open", "high", "low", "close")}
                for i in range(2)
            ],
            "funding_rates": funding_rows,
            "expected_funding_events": expected_funding_events,
            "minute_windows": minute_windows,
            "instrument_specs": [dataclasses.asdict(x) for x in specs],
            "risk_tiers": [[dataclasses.asdict(x) for x in group] for group in tiers],
            "public_data_only": True,
        })
        prior_targets = target
        last = execution_time
    return observations


def _objects(profile_state: Mapping[str, Any]) -> list[Position]:
    return [Position(float(row["quantity"]), float(row["average_entry"])) for row in profile_state["positions"]]


def _profile_step(
    current: Mapping[str, Any],
    observation: Mapping[str, Any],
    profile: Mapping[str, Any],
    profile_name: str,
) -> dict[str, Any]:
    row = deepcopy(dict(current))
    positions = _objects(row)
    specs = [InstrumentSpec(**item) for item in observation["instrument_specs"]]
    tiers = [[RiskTier(**tier) for tier in group] for group in observation["risk_tiers"]]
    fee_rate = float(profile["fee_bps"]) / 10000.0
    wallet = float(row["wallet"])
    marks_open = np.array([float(x["open"]) for x in observation["mark"]])
    for asset, rates in enumerate(observation["funding_rates"]):
        row["expected_funding_events"] += int(observation["expected_funding_events"][asset])
        for rate in rates:
            cashflow = funding_cashflow(positions[asset].quantity, marks_open[asset], float(rate))
            wallet += cashflow
            row["funding_cashflow"] += cashflow
            row["actual_funding_events"] += 1
    target = [float(x) for x in observation["target_weights"]]
    if observation["target_changed"]:
        equity_open = wallet + sum(unrealized(position, marks_open[i]) for i, position in enumerate(positions))
        desired = [
            normalized_target_quantity(equity_open * target[i], marks_open[i], specs[i])
            for i in range(2)
        ]
        for asset, spec in enumerate(specs):
            delta = desired[asset] - positions[asset].quantity
            if abs(delta) <= 1e-15:
                continue
            row["orders"] += 1
            window = observation["minute_windows"].get(spec.symbol, {}).get(
                profile_name, []
            )
            frame = pd.DataFrame(window)
            vwap = minute_vwap(frame) if not frame.empty else None
            if vwap is None:
                fallback = float(profile["fallback_slippage_bps"]) / 10000.0
                fill = float(observation["trade"][asset]["open"]) * (
                    1.0 + math.copysign(fallback, delta)
                )
            else:
                turnover = float(frame["turnover"].sum())
                fill, _ = adverse_fill_price(
                    delta, vwap, abs(delta) * vwap, turnover, dict(profile)
                )
                row["execution_hits"] += 1
            candidate = [Position(x.quantity, x.average_entry) for x in positions]
            candidate_wallet = wallet + apply_trade(candidate[asset], delta, fill)
            fee = abs(delta * fill) * fee_rate
            candidate_wallet -= fee
            initial, _, details = margin_requirements(
                candidate, marks_open, tiers, float(profile["account_leverage"]), fee_rate
            )
            candidate_equity = candidate_wallet + sum(
                unrealized(position, marks_open[i]) for i, position in enumerate(candidate)
            )
            tier_exceeded = any(
                float(item["tier_limit"]) > 0.0
                and float(item["notional"]) > float(item["tier_limit"]) + 1e-8
                for item in details
            )
            if tier_exceeded or initial > candidate_equity + 1e-8:
                row["margin_rejections"] += 1
                continue
            positions = candidate
            wallet = candidate_wallet
            row["fees"] += fee
            row["fill_count"] += 1
            row["asset_fill_counts"][asset] += 1
            utilization = initial / max(candidate_equity, 1e-12)
            tier_utilization = max(
                (float(x["notional"]) / float(x["tier_limit"]) for x in details if x["tier_limit"] > 0),
                default=0.0,
            )
            row["maximum_margin_utilization"] = max(row["maximum_margin_utilization"], utilization)
            row["maximum_risk_tier_utilization"] = max(row["maximum_risk_tier_utilization"], tier_utilization)
        row["target_weights"] = target
    close_marks = np.array([float(x["close"]) for x in observation["mark"]])
    adverse = np.array([
        float(observation["mark"][i]["low"] if position.quantity >= 0 else observation["mark"][i]["high"])
        for i, position in enumerate(positions)
    ])
    close_equity = wallet + sum(unrealized(position, close_marks[i]) for i, position in enumerate(positions))
    adverse_equity = wallet + sum(unrealized(position, adverse[i]) for i, position in enumerate(positions))
    initial, _, details = margin_requirements(
        positions, close_marks, tiers, float(profile["account_leverage"]), fee_rate
    )
    _, maintenance, _ = margin_requirements(
        positions, adverse, tiers, float(profile["account_leverage"]), fee_rate
    )
    row["maximum_margin_utilization"] = max(
        row["maximum_margin_utilization"], initial / max(close_equity, 1e-12)
    )
    row["maximum_risk_tier_utilization"] = max(
        row["maximum_risk_tier_utilization"],
        max(
            (float(x["notional"]) / float(x["tier_limit"]) for x in details if x["tier_limit"] > 0),
            default=0.0,
        ),
    )
    if maintenance > 0.0 and adverse_equity <= maintenance:
        row["liquidations"] += 1
        liquidation_rate = float(profile["liquidation_fee_bps"]) / 10000.0
        for asset, position in enumerate(positions):
            if abs(position.quantity) <= 1e-15:
                continue
            delta = -position.quantity
            fill = adverse[asset] * (1.0 + math.copysign(liquidation_rate, delta))
            wallet += apply_trade(position, delta, fill)
            charge = abs(delta * fill) * liquidation_rate
            wallet -= charge
            row["fees"] += charge
            row["fill_count"] += 1
            row["asset_fill_counts"][asset] += 1
        close_equity = wallet
    if not math.isfinite(close_equity) or close_equity <= 0.0:
        raise ProspectivePaperError("paper-forward account equity is non-positive")
    row["wallet"] = float(wallet)
    row["equity"] = float(close_equity)
    row["equity_high"] = max(float(row["equity_high"]), float(close_equity))
    drawdown = 1.0 - float(close_equity) / max(float(row["equity_high"]), 1e-12)
    row["maximum_drawdown"] = max(float(row["maximum_drawdown"]), drawdown)
    row["positions"] = [dataclasses.asdict(position) for position in positions]
    return row


def _completion(config: Mapping[str, Any], state: Mapping[str, Any]) -> tuple[str, str]:
    start = _utc(config["start_not_before_utc"])
    last = _utc(state["last_execution_utc"]) if state["last_execution_utc"] else start
    elapsed_days = (last - start).total_seconds() / 86400.0
    ready = (
        elapsed_days >= int(config["minimum_observation_days"])
        and int(state["completed_bar_count"]) >= int(config["minimum_completed_bars"])
    )
    if not ready:
        return "COLLECTING", "collect_prospective_paper_evidence"
    all_pass = True
    for name, profile in state["profiles"].items():
        gate = config["completion_gates"][name]
        initial = float(config["execution_profiles"][name]["initial_cash"])
        funding_coverage = profile["actual_funding_events"] / max(profile["expected_funding_events"], 1)
        execution_coverage = profile["execution_hits"] / max(profile["orders"], 1)
        checks = [
            profile["equity"] / initial - 1.0 >= gate["minimum_total_return"],
            profile["maximum_drawdown"] <= gate["maximum_drawdown"],
            profile["fill_count"] >= gate["minimum_fill_count"],
            min(profile["asset_fill_counts"]) >= gate["minimum_asset_fill_count"],
            funding_coverage >= gate["minimum_funding_coverage"],
            execution_coverage >= gate["minimum_execution_coverage"],
            profile["maximum_margin_utilization"] <= gate["maximum_margin_utilization"],
            profile["maximum_risk_tier_utilization"] <= gate["maximum_risk_tier_utilization"],
            profile["margin_rejections"] == 0,
            profile["liquidations"] == 0,
        ]
        all_pass &= all(checks)
    return (
        ("COMPLETE_REVIEW_REQUIRED", "paper_forward_passed_requires_separate_owner_review")
        if all_pass
        else ("QUARANTINED", "paper_forward_failed_no_promotion")
    )


def apply_observations(
    state: Mapping[str, Any],
    observations: list[Mapping[str, Any]],
    config: Mapping[str, Any],
    *,
    source_sha: str,
    run_id: int,
) -> dict[str, Any]:
    result = deepcopy(dict(state))
    if int(run_id) <= int(result["last_run_id"]):
        raise ProspectivePaperError("workflow run ID did not advance")
    for observation in observations:
        if observation.get("public_data_only") is not True:
            raise ProspectivePaperError("paper-forward observation is not public-data-only")
        execution = _utc(str(observation["execution_utc"]))
        if execution < _utc(config["start_not_before_utc"]):
            raise ProspectivePaperError("pre-cutoff data cannot enter prospective evidence")
        if result["last_execution_utc"] and execution <= _utc(result["last_execution_utc"]):
            raise ProspectivePaperError("paper-forward observations are not strictly increasing")
        for name in ("conservative", "stress"):
            result["profiles"][name] = _profile_step(
                result["profiles"][name], observation, config["execution_profiles"][name], name
            )
        previous = result["events"][-1]["event_digest"] if result["events"] else "0" * 64
        event_core = {
            "schema_version": EVENT_SCHEMA,
            "sequence": len(result["events"]) + 1,
            "execution_utc": observation["execution_utc"],
            "signal_close_utc": observation["signal_close_utc"],
            "target_weights": observation["target_weights"],
            "target_changed": observation["target_changed"],
            "market_evidence_digest": _digest(dict(observation)),
            "source_sha": source_sha,
            "previous_event_digest": previous,
            "paper_only": True,
            "live_trading_enabled": False,
        }
        result["events"].append({**event_core, "event_digest": _digest(event_core)})
        result["last_execution_utc"] = observation["execution_utc"]
        result["completed_bar_count"] += 1
    result["last_run_id"] = int(run_id)
    result["latest_source_sha"] = source_sha
    result["status"], result["decision"] = _completion(config, result)
    result["paper_only"] = True
    result["live_trading_enabled"] = False
    result["private_credentials_used"] = False
    result["automatic_live_promotion"] = False
    unsigned = dict(result)
    unsigned.pop("state_digest", None)
    result["state_digest"] = _digest(unsigned)
    return result


def save_state(path: Path, state: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(dict(state), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def run_once(
    *,
    manifest_path: Path,
    state_path: Path,
    output_path: Path,
    source_sha: str,
    run_id: int,
    now_utc: str,
    client: Client | None = None,
) -> dict[str, Any]:
    config, frozen = load_contract(manifest_path.resolve())
    engine_sha = _file_sha(Path(__file__).resolve())
    if state_path.is_file():
        state = json.loads(state_path.read_text(encoding="utf-8"))
        verify_state(state, config, engine_sha)
    else:
        state = new_state(config, engine_sha256=engine_sha, source_sha=source_sha, run_id=run_id - 1)
    observations = collect_observations(
        config, frozen, state, now_utc=now_utc, client=client
    )
    updated = apply_observations(
        state, observations, config, source_sha=source_sha, run_id=run_id
    )
    verify_state(updated, config, engine_sha)
    save_state(output_path, updated)
    return updated


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=Path("experiments/bybit_prospective_paper_forward_v1.json"))
    parser.add_argument("--state", type=Path, default=Path("build/prior/bybit_prospective_paper_forward_v1.json"))
    parser.add_argument("--output", type=Path, default=Path("build/bybit_prospective_paper_forward_v1/bybit_prospective_paper_forward_v1.json"))
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--run-id", type=int, required=True)
    parser.add_argument("--now-utc", default=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"))
    args = parser.parse_args()
    state = run_once(
        manifest_path=args.manifest, state_path=args.state, output_path=args.output,
        source_sha=args.source_sha, run_id=args.run_id, now_utc=args.now_utc,
    )
    print(json.dumps({
        "status": state["status"], "decision": state["decision"],
        "completed_bar_count": state["completed_bar_count"],
        "last_execution_utc": state["last_execution_utc"],
        "state_digest": state["state_digest"], "paper_only": state["paper_only"],
        "live_trading_enabled": state["live_trading_enabled"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
