from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import math
import shutil
from pathlib import Path
from statistics import median
from typing import Any

import numpy as np
import pandas as pd

import bybit_portfolio_search_v3 as common

BARS_PER_DAY = common.BARS_PER_DAY
BARS_PER_YEAR = common.BARS_PER_YEAR


class LongShortSearchError(RuntimeError):
    pass


def cid(family: str, params: dict[str, Any]) -> str:
    raw = json.dumps({"family": family, "params": params}, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def lag_return(values: np.ndarray, days: int) -> np.ndarray:
    periods = common.bars(days)
    output = np.full_like(values, np.nan)
    output[periods:] = values[periods:] / values[:-periods] - 1.0
    return output


def enumerate_candidates(cfg: dict[str, Any]) -> list[dict[str, Any]]:
    risk = cfg["search"]["risk"]
    overlays = list(itertools.product(risk["vol_days"], risk["target_vol"], risk["rebalance_days"]))
    quantum = float(risk["quantum"])
    output: list[dict[str, Any]] = []

    section = cfg["search"]["tsmom_long_short"]
    for lookbacks, threshold, deadband, allocation, overlay in itertools.product(
        section["lookback_sets"], section["vote_threshold"], section["deadband"],
        section["allocation"], overlays
    ):
        vol_days, target_vol, rebalance_days = overlay
        params = {
            "lookbacks": lookbacks, "vote_threshold": threshold, "deadband": deadband,
            "allocation": allocation, "vol_days": vol_days, "target_vol": target_vol,
            "rebalance_days": rebalance_days, "quantum": quantum,
        }
        output.append({"id": cid("tsmom_long_short", params), "family": "tsmom_long_short", "params": params})

    section = cfg["search"]["ema_long_short"]
    for fast, slow, deadband, allocation, overlay in itertools.product(
        section["fast_days"], section["slow_days"], section["deadband"],
        section["allocation"], overlays
    ):
        if fast >= slow:
            continue
        vol_days, target_vol, rebalance_days = overlay
        params = {
            "fast_days": fast, "slow_days": slow, "deadband": deadband,
            "allocation": allocation, "vol_days": vol_days, "target_vol": target_vol,
            "rebalance_days": rebalance_days, "quantum": quantum,
        }
        output.append({"id": cid("ema_long_short", params), "family": "ema_long_short", "params": params})

    section = cfg["search"]["breakout_long_short"]
    for entry, exit_, allocation, overlay in itertools.product(
        section["entry_days"], section["exit_days"], section["allocation"], overlays
    ):
        if exit_ >= entry:
            continue
        vol_days, target_vol, rebalance_days = overlay
        params = {
            "entry_days": entry, "exit_days": exit_, "allocation": allocation,
            "vol_days": vol_days, "target_vol": target_vol,
            "rebalance_days": rebalance_days, "quantum": quantum,
        }
        output.append({"id": cid("breakout_long_short", params), "family": "breakout_long_short", "params": params})

    section = cfg["search"]["relative_value"]
    for lookbacks, spread, overlay in itertools.product(
        section["lookback_sets"], section["minimum_score_spread"], overlays
    ):
        vol_days, target_vol, rebalance_days = overlay
        params = {
            "lookbacks": lookbacks, "minimum_score_spread": spread,
            "allocation": "relative_value", "vol_days": vol_days,
            "target_vol": target_vol, "rebalance_days": rebalance_days,
            "quantum": quantum,
        }
        output.append({"id": cid("relative_value", params), "family": "relative_value", "params": params})
    return output


def structural_key(candidate: dict[str, Any]) -> str:
    excluded = {"vol_days", "target_vol", "rebalance_days", "quantum"}
    params = {key: value for key, value in candidate["params"].items() if key not in excluded}
    return json.dumps({"family": candidate["family"], "params": params}, sort_keys=True)


def structural_signal(market: dict[str, Any], candidate: dict[str, Any]) -> tuple[np.ndarray, np.ndarray]:
    close = market["close"]
    p = candidate["params"]
    family = candidate["family"]
    n, assets = close.shape

    if family in {"tsmom_long_short", "relative_value"}:
        returns = np.stack([lag_return(close, int(days)) for days in p["lookbacks"]], axis=2)
        normalized = np.stack([
            np.log1p(np.maximum(returns[:, :, index], -0.999999)) / math.sqrt(float(days))
            for index, days in enumerate(p["lookbacks"])
        ], axis=2)
        score = np.nanmedian(normalized, axis=2)
        if family == "relative_value":
            signal = np.zeros((n, assets), dtype=float)
            valid = np.isfinite(score).all(axis=1)
            spread = np.abs(score[:, 0] - score[:, 1])
            active = valid & (spread >= float(p["minimum_score_spread"]) / math.sqrt(180.0))
            stronger = np.argmax(score, axis=1)
            signal[np.arange(n)[active], stronger[active]] = 1.0
            signal[np.arange(n)[active], 1 - stronger[active]] = -1.0
            return signal, score

        positive_votes = np.mean(returns > 0, axis=2)
        negative_votes = np.mean(returns < 0, axis=2)
        aggregate = np.nanmedian(returns, axis=2)
        signal = np.zeros((n, assets), dtype=float)
        signal[(positive_votes >= float(p["vote_threshold"])) & (aggregate > float(p["deadband"]))] = 1.0
        signal[(negative_votes >= float(p["vote_threshold"])) & (aggregate < -float(p["deadband"]))] = -1.0
        return signal, score

    if family == "ema_long_short":
        fast = np.column_stack([
            pd.Series(close[:, asset]).ewm(
                span=common.bars(int(p["fast_days"])), adjust=False,
                min_periods=common.bars(int(p["fast_days"]))
            ).mean().to_numpy(float)
            for asset in range(assets)
        ])
        slow = np.column_stack([
            pd.Series(close[:, asset]).ewm(
                span=common.bars(int(p["slow_days"])), adjust=False,
                min_periods=common.bars(int(p["slow_days"]))
            ).mean().to_numpy(float)
            for asset in range(assets)
        ])
        score = fast / slow - 1.0
        signal = np.zeros((n, assets), dtype=float)
        signal[score > float(p["deadband"])] = 1.0
        signal[score < -float(p["deadband"])] = -1.0
        signal[~np.isfinite(score)] = 0.0
        return signal, score

    if family == "breakout_long_short":
        entry = common.bars(int(p["entry_days"]))
        exit_ = common.bars(int(p["exit_days"]))
        signal = np.zeros((n, assets), dtype=float)
        score = np.zeros((n, assets), dtype=float)
        for asset in range(assets):
            series = pd.Series(close[:, asset])
            entry_high = series.shift(1).rolling(entry, min_periods=entry).max().to_numpy(float)
            entry_low = series.shift(1).rolling(entry, min_periods=entry).min().to_numpy(float)
            exit_high = series.shift(1).rolling(exit_, min_periods=exit_).max().to_numpy(float)
            exit_low = series.shift(1).rolling(exit_, min_periods=exit_).min().to_numpy(float)
            state = 0.0
            for index, price in enumerate(close[:, asset]):
                if np.isfinite(entry_high[index]) and price > entry_high[index]:
                    state = 1.0
                elif np.isfinite(entry_low[index]) and price < entry_low[index]:
                    state = -1.0
                elif state > 0 and np.isfinite(exit_low[index]) and price < exit_low[index]:
                    state = 0.0
                elif state < 0 and np.isfinite(exit_high[index]) and price > exit_high[index]:
                    state = 0.0
                signal[index, asset] = state
                if state > 0 and np.isfinite(entry_high[index]):
                    score[index, asset] = price / entry_high[index] - 1.0
                elif state < 0 and np.isfinite(entry_low[index]):
                    score[index, asset] = entry_low[index] / price - 1.0
        return signal, score

    raise LongShortSearchError(f"Unsupported family: {family}")


def construct_weights(
    signal_and_score: tuple[np.ndarray, np.ndarray],
    vol: np.ndarray,
    candidate: dict[str, Any],
) -> np.ndarray:
    signal, score = signal_and_score
    p = candidate["params"]
    n, assets = signal.shape
    if candidate["family"] == "relative_value":
        base = signal * 0.5
    else:
        active = np.abs(signal) > 0
        if p["allocation"] == "equal":
            counts = active.sum(axis=1, keepdims=True)
            magnitudes = np.divide(
                active.astype(float), counts,
                out=np.zeros_like(signal), where=counts > 0
            )
        elif p["allocation"] == "inverse_vol":
            inverse = np.divide(
                1.0, vol, out=np.zeros_like(vol),
                where=(vol > 0) & np.isfinite(vol)
            ) * active
            totals = inverse.sum(axis=1, keepdims=True)
            magnitudes = np.divide(inverse, totals, out=np.zeros_like(inverse), where=totals > 0)
        else:
            raise LongShortSearchError(f"Unsupported allocation: {p['allocation']}")
        base = np.sign(signal) * magnitudes

    risk_proxy = np.sum(np.abs(base) * np.where(np.isfinite(vol), vol, 0.0), axis=1)
    scale = np.divide(
        float(p["target_vol"]), risk_proxy,
        out=np.zeros(n), where=risk_proxy > 0
    )
    scale = np.clip(scale, 0.0, 1.0)
    raw = base * scale[:, None]
    rebalance = common.bars(int(p["rebalance_days"]))
    source = (np.arange(n) // rebalance) * rebalance
    held = raw[source]
    quantum = float(p["quantum"])
    held = np.round(held / quantum) * quantum
    held = np.clip(held, -1.0, 1.0)
    gross = np.abs(held).sum(axis=1)
    excessive = gross > 1.0
    held[excessive] /= gross[excessive, None]
    held[~np.isfinite(held)] = 0.0
    return held


def approximate_backtest(
    market: dict[str, Any], weights: np.ndarray, period: dict[str, str], profile: dict[str, float]
) -> dict[str, Any]:
    idx = common.period_indices(market["timestamps"], period)
    close = market["close"][idx]
    selected = weights[idx]
    asset_returns = close[1:] / close[:-1] - 1.0
    positions = selected[:-1]
    previous = np.vstack([np.zeros((1, positions.shape[1])), positions[:-1]])
    turnover = np.abs(positions - previous)
    transaction_bps = float(profile["fee_bps"]) + float(profile["slippage_bps"])
    short_carry = np.abs(np.minimum(positions, 0.0)).sum(axis=1) * float(profile["annual_short_carry"]) / BARS_PER_YEAR
    net = np.sum(positions * asset_returns, axis=1) - turnover.sum(axis=1) * transaction_bps / 10000.0 - short_carry
    if len(net):
        net[-1] -= np.abs(positions[-1]).sum() * transaction_bps / 10000.0
    net = np.maximum(net, -0.999999)
    equity = np.r_[1.0, np.cumprod(1.0 + net)]
    drawdown = equity / np.maximum.accumulate(equity) - 1.0
    sd = float(np.std(net, ddof=0))
    sharpe = float(np.mean(net) / sd * math.sqrt(BARS_PER_YEAR)) if sd > 0 else 0.0
    changes = np.abs(np.diff(np.vstack([np.zeros((1, positions.shape[1])), positions]), axis=0)) > 1e-12
    asset_fills = changes.sum(axis=0).astype(int)
    asset_fills += (np.abs(positions[-1]) > 1e-12).astype(int)
    return {
        "total_return": float(equity[-1] - 1.0),
        "max_drawdown": float(-drawdown.min()),
        "sharpe": sharpe,
        "fill_count": int(asset_fills.sum()),
        "asset_fill_counts": asset_fills.tolist(),
        "turnover": float(turnover.sum() + np.abs(positions[-1]).sum()),
        "average_gross_exposure": float(np.mean(np.abs(positions).sum(axis=1))),
        "average_net_exposure": float(np.mean(positions.sum(axis=1))),
    }


def exact_backtest(
    market: dict[str, Any], weights: np.ndarray, period: dict[str, str], profile: dict[str, float]
) -> dict[str, Any]:
    idx = common.period_indices(market["timestamps"], period)
    opens = market["open"][idx]
    closes = market["close"][idx]
    selected = weights[idx]
    cash = float(profile["initial_cash"])
    quantity = np.zeros(opens.shape[1], dtype=float)
    fee_rate = float(profile["fee_bps"]) / 10000.0
    slippage = float(profile["slippage_bps"]) / 10000.0
    annual_carry = float(profile["annual_short_carry"])
    total_fees = 0.0
    total_carry = 0.0
    total_notional = 0.0
    asset_fills = np.zeros(opens.shape[1], dtype=int)
    equity_rows: list[float] = []

    for row in range(len(idx)):
        target_changed = row == 1 or (
            row > 1 and not np.allclose(selected[row - 1], selected[row - 2], rtol=0.0, atol=1e-12)
        )
        if row > 0 and target_changed:
            equity_at_open = cash + float(np.dot(quantity, opens[row]))
            desired = equity_at_open * selected[row - 1] / opens[row]
            changes = desired - quantity
            order = list(np.where(changes < -1e-12)[0]) + list(np.where(changes > 1e-12)[0])
            for asset in order:
                change = float(changes[asset])
                fill = opens[row, asset] * (1.0 + slippage if change > 0 else 1.0 - slippage)
                notional = abs(change * fill)
                fee = notional * fee_rate
                cash -= change * fill + fee
                quantity[asset] += change
                total_notional += notional
                total_fees += fee
                asset_fills[asset] += 1
        short_notional = float(np.sum(np.abs(np.minimum(quantity, 0.0)) * closes[row]))
        carry = short_notional * annual_carry / BARS_PER_YEAR
        cash -= carry
        total_carry += carry
        equity = cash + float(np.dot(quantity, closes[row]))
        if not np.isfinite(equity) or equity <= 0:
            raise LongShortSearchError("Portfolio equity became non-positive")
        equity_rows.append(equity)

    for asset in range(len(quantity)):
        if abs(quantity[asset]) > 1e-12:
            change = -quantity[asset]
            fill = closes[-1, asset] * (1.0 + slippage if change > 0 else 1.0 - slippage)
            notional = abs(change * fill)
            fee = notional * fee_rate
            cash -= change * fill + fee
            quantity[asset] = 0.0
            total_notional += notional
            total_fees += fee
            asset_fills[asset] += 1
    equity_rows[-1] = cash
    equity = np.asarray(equity_rows, dtype=float)
    returns = pd.Series(equity).pct_change().replace([np.inf, -np.inf], np.nan).dropna().to_numpy(float)
    drawdown = equity / np.maximum.accumulate(equity) - 1.0
    sd = float(np.std(returns, ddof=0)) if len(returns) else 0.0
    sharpe = float(np.mean(returns) / sd * math.sqrt(BARS_PER_YEAR)) if sd > 0 else 0.0
    return {
        "total_return": float(equity[-1] / profile["initial_cash"] - 1.0),
        "max_drawdown": float(-drawdown.min()),
        "sharpe": sharpe,
        "fill_count": int(asset_fills.sum()),
        "asset_fill_counts": asset_fills.tolist(),
        "turnover": float(total_notional / profile["initial_cash"]),
        "total_fees": float(total_fees),
        "total_short_carry": float(total_carry),
        "average_gross_exposure": float(np.mean(np.abs(selected[:-1]).sum(axis=1))),
        "average_net_exposure": float(np.mean(selected[:-1].sum(axis=1))),
    }


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    returns = [float(row["total_return"]) for row in rows]
    drawdowns = [float(row["max_drawdown"]) for row in rows]
    sharpes = [float(row["sharpe"]) for row in rows]
    fills = [int(row["fill_count"]) for row in rows]
    turnovers = [float(row["turnover"]) for row in rows]
    minimum_asset_fills = min(min(row["asset_fill_counts"]) for row in rows)
    result = {
        "count": len(rows),
        "positive_ratio": sum(value > 0 for value in returns) / len(returns),
        "median_return": float(median(returns)),
        "worst_return": float(min(returns)),
        "worst_drawdown": float(max(drawdowns)),
        "median_sharpe": float(median(sharpes)),
        "minimum_sharpe": float(min(sharpes)),
        "minimum_fill_count": int(min(fills)),
        "minimum_asset_fill_count": int(minimum_asset_fills),
        "median_turnover": float(median(turnovers)),
    }
    result["score"] = (
        result["median_sharpe"] + 1.4 * result["median_return"]
        + 0.3 * result["positive_ratio"] - 1.25 * result["worst_drawdown"]
        - 0.002 * result["median_turnover"]
    )
    return result


def gate_checks(summary: dict[str, Any], gate: dict[str, Any]) -> dict[str, bool]:
    return {
        "positive_ratio": summary["positive_ratio"] >= gate["minimum_positive_ratio"],
        "median_return": summary["median_return"] >= gate["minimum_median_return"],
        "worst_return": summary["worst_return"] >= gate["minimum_worst_return"],
        "drawdown": summary["worst_drawdown"] <= gate["maximum_drawdown"],
        "median_sharpe": summary["median_sharpe"] >= gate["minimum_median_sharpe"],
        "minimum_sharpe": summary["minimum_sharpe"] >= gate["minimum_sharpe"],
        "fills": summary["minimum_fill_count"] >= gate["minimum_fill_count"],
        "both_assets_used": summary["minimum_asset_fill_count"] >= gate["minimum_asset_fill_count"],
    }


def evaluate(
    market: dict[str, Any], weights: np.ndarray, folds: list[dict[str, str]],
    mode: str, profile: dict[str, float]
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    rows = []
    for fold, period in enumerate(folds, 1):
        metric = exact_backtest(market, weights, period, profile) if mode == "exact" else approximate_backtest(market, weights, period, profile)
        rows.append({"fold": fold, "start": period["start"], "end": period["end"], **metric})
    return summarize(rows), rows


def flatten(row: dict[str, Any]) -> dict[str, Any]:
    result = dict(row)
    result["params"] = json.dumps(result["params"], sort_keys=True)
    result["failed_conservative"] = json.dumps(result.get("failed_conservative", []))
    result["failed_stress"] = json.dumps(result.get("failed_stress", []))
    return result


def buy_hold_baselines(market: dict[str, Any], folds: list[dict[str, str]]) -> list[dict[str, Any]]:
    output = []
    for fold, period in enumerate(folds, 1):
        idx = common.period_indices(market["timestamps"], period)
        for asset, symbol in enumerate(market["symbols"]):
            result = market["close"][idx[-1], asset] / market["close"][idx[0], asset] - 1.0
            output.append({"fold": fold, "symbol": symbol, "start": period["start"], "end": period["end"], "total_return": float(result)})
    return output


def run_search(manifest_path: Path, output_root: Path) -> dict[str, Any]:
    cfg = json.loads(manifest_path.read_text(encoding="utf-8"))
    market = common.load_market(Path(cfg["dataset"]["dataset_root"]), cfg["symbols"])
    candidates = enumerate_candidates(cfg)
    profiles = cfg["execution"]
    state_cache: dict[str, tuple[np.ndarray, np.ndarray]] = {}
    vol_cache: dict[int, np.ndarray] = {}
    approximate_rows: list[dict[str, Any]] = []

    for candidate in candidates:
        key = structural_key(candidate)
        if key not in state_cache:
            state_cache[key] = structural_signal(market, candidate)
        vol_days = int(candidate["params"]["vol_days"])
        if vol_days not in vol_cache:
            vol_cache[vol_days] = common.realized_vol(market["close"], vol_days)
        weights = construct_weights(state_cache[key], vol_cache[vol_days], candidate)
        conservative_summary, _ = evaluate(market, weights, cfg["folds"], "approx", profiles["conservative"])
        conservative_checks = gate_checks(conservative_summary, cfg["gates"]["conservative"])
        approximate_rows.append({
            **candidate, **conservative_summary,
            "passes_conservative": all(conservative_checks.values()),
            "failed_conservative": [name for name, passed in conservative_checks.items() if not passed],
        })

    approximate_rows.sort(key=lambda row: row["score"], reverse=True)
    approximate_passers = [row for row in approximate_rows if row["passes_conservative"]]
    finalists = (approximate_passers or approximate_rows)[: int(cfg["search"]["top_exact"])]
    candidate_map = {candidate["id"]: candidate for candidate in candidates}
    exact_rows: list[dict[str, Any]] = []
    exact_runs: list[dict[str, Any]] = []
    weight_cache: dict[str, np.ndarray] = {}

    for approximate in finalists:
        candidate = candidate_map[approximate["id"]]
        key = structural_key(candidate)
        weights = construct_weights(state_cache[key], vol_cache[int(candidate["params"]["vol_days"])], candidate)
        weight_cache[candidate["id"]] = weights
        conservative_summary, conservative_runs = evaluate(market, weights, cfg["folds"], "exact", profiles["conservative"])
        stress_summary, stress_runs = evaluate(market, weights, cfg["folds"], "exact", profiles["stress"])
        conservative_checks = gate_checks(conservative_summary, cfg["gates"]["conservative"])
        stress_checks = gate_checks(stress_summary, cfg["gates"]["stress"])
        exact_rows.append({
            **candidate,
            "conservative": conservative_summary,
            "stress": stress_summary,
            "combined_score": conservative_summary["score"] + 0.5 * stress_summary["score"],
            "passes": all(conservative_checks.values()) and all(stress_checks.values()),
            "failed_conservative": [name for name, passed in conservative_checks.items() if not passed],
            "failed_stress": [name for name, passed in stress_checks.items() if not passed],
        })
        exact_runs.extend({"candidate_id": candidate["id"], "family": candidate["family"], "profile": "conservative", **row} for row in conservative_runs)
        exact_runs.extend({"candidate_id": candidate["id"], "family": candidate["family"], "profile": "stress", **row} for row in stress_runs)

    exact_rows.sort(key=lambda row: row["combined_score"], reverse=True)
    passers = [row for row in exact_rows if row["passes"]]
    ranked = passers or exact_rows
    passing_families = sorted({row["family"] for row in passers})
    plateau = len(passers) >= 10 and len(passing_families) >= 2

    components: list[dict[str, Any]] = []
    family_counts: dict[str, int] = {}
    for row in ranked:
        if family_counts.get(row["family"], 0) >= 3:
            continue
        components.append(row)
        family_counts[row["family"]] = family_counts.get(row["family"], 0) + 1
        if len(components) >= int(cfg["search"]["ensemble_size"]):
            break

    ensemble_weights = np.median(np.stack([weight_cache[row["id"]] for row in components], axis=2), axis=2)
    gross = np.abs(ensemble_weights).sum(axis=1)
    excessive = gross > 1.0
    ensemble_weights[excessive] /= gross[excessive, None]
    ensemble_conservative, ensemble_conservative_runs = evaluate(market, ensemble_weights, cfg["folds"], "exact", profiles["conservative"])
    ensemble_stress, ensemble_stress_runs = evaluate(market, ensemble_weights, cfg["folds"], "exact", profiles["stress"])
    ensemble_conservative_checks = gate_checks(ensemble_conservative, cfg["gates"]["conservative"])
    ensemble_stress_checks = gate_checks(ensemble_stress, cfg["gates"]["stress"])
    ensemble_passes = all(ensemble_conservative_checks.values()) and all(ensemble_stress_checks.values())
    ensemble_score = ensemble_conservative["score"] + 0.5 * ensemble_stress["score"]
    best = ranked[0]

    if ensemble_passes and ensemble_score >= best["combined_score"]:
        selected = {
            "type": "median_ensemble",
            "components": [{"id": row["id"], "family": row["family"], "params": row["params"]} for row in components],
            "conservative": ensemble_conservative,
            "stress": ensemble_stress,
            "conservative_checks": ensemble_conservative_checks,
            "stress_checks": ensemble_stress_checks,
            "combined_score": ensemble_score,
        }
        selected_runs = [
            *({"profile": "conservative", **row} for row in ensemble_conservative_runs),
            *({"profile": "stress", **row} for row in ensemble_stress_runs),
        ]
        selected_passes = True
    else:
        selected = {
            "type": "single", "id": best["id"], "family": best["family"],
            "params": best["params"], "conservative": best["conservative"],
            "stress": best["stress"], "combined_score": best["combined_score"],
            "conservative_checks": gate_checks(best["conservative"], cfg["gates"]["conservative"]),
            "stress_checks": gate_checks(best["stress"], cfg["gates"]["stress"]),
        }
        selected_runs = [row for row in exact_runs if row["candidate_id"] == best["id"]]
        selected_passes = best["passes"]

    qualifies = bool(plateau and selected_passes)
    report = {
        "experiment_id": cfg["experiment_id"],
        "dataset_archive_sha256": cfg["dataset"]["archive_sha256"],
        "limitations": [
            "The complete historical range has now informed model development; no historical period remains pristine.",
            "Short positions are modeled from Spot OHLCV with explicit carry assumptions, but actual perpetual funding, borrow availability, margin and liquidation are not in this dataset.",
            "Qualification requires a separate derivatives-data validation and prospective paper-forward run before any implementation decision."
        ],
        "summary": {
            "candidate_count": len(candidates),
            "approximate_conservative_passers": len(approximate_passers),
            "exact_evaluated": len(exact_rows),
            "exact_dual_profile_passers": len(passers),
            "passing_families": passing_families,
            "parameter_plateau": plateau,
            "qualifies_for_derivatives_data_and_prospective_paper_forward_review": qualifies,
            "automatic_paper_forward_started": False,
            "live_trading_enabled": False,
        },
        "selected_strategy": selected,
        "selected_runs": selected_runs,
        "buy_hold_baselines": buy_hold_baselines(market, cfg["folds"]),
        "decision": "eligible_for_derivatives_validation_and_prospective_paper_forward" if qualifies else "continue_research_no_promotion",
    }

    output_root.mkdir(parents=True, exist_ok=True)
    (output_root / "long_short_search_v4.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (output_root / "selected_long_short_strategy.json").write_text(json.dumps(selected, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    pd.DataFrame([flatten(row) for row in approximate_rows[:1000]]).to_csv(output_root / "top_approximate_candidates.csv", index=False)
    exact_flat = []
    for row in exact_rows:
        exact_flat.append({
            "id": row["id"], "family": row["family"], "params": json.dumps(row["params"], sort_keys=True),
            "passes": row["passes"], "combined_score": row["combined_score"],
            **{f"conservative_{key}": value for key, value in row["conservative"].items()},
            **{f"stress_{key}": value for key, value in row["stress"].items()},
            "failed_conservative": json.dumps(row["failed_conservative"]),
            "failed_stress": json.dumps(row["failed_stress"]),
        })
    pd.DataFrame(exact_flat).to_csv(output_root / "exact_candidates.csv", index=False)
    pd.DataFrame(exact_runs).to_csv(output_root / "exact_fold_runs.csv", index=False)
    pd.DataFrame(selected_runs).to_csv(output_root / "selected_fold_runs.csv", index=False)
    pd.DataFrame(report["buy_hold_baselines"]).to_csv(output_root / "buy_hold_baselines.csv", index=False)
    shutil.copy2(manifest_path, output_root / manifest_path.name)
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, default=Path("experiments/bybit_long_short_search_v4.json"))
    parser.add_argument("--output", type=Path, default=Path("build/bybit_long_short_search_v4"))
    parser.add_argument("--require-qualified", action="store_true")
    args = parser.parse_args()
    report = run_search(args.manifest, args.output)
    print(json.dumps(report["summary"], sort_keys=True))
    if args.require_qualified and not report["summary"]["qualifies_for_derivatives_data_and_prospective_paper_forward_review"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
