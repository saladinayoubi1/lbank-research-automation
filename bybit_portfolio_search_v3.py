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

BARS_PER_DAY = 6
BARS_PER_YEAR = 365.25 * BARS_PER_DAY


class PortfolioSearchError(RuntimeError):
    pass


def bars(days: int) -> int:
    return max(1, int(days) * BARS_PER_DAY)


def candidate_id(family: str, params: dict[str, Any]) -> str:
    text = json.dumps({"family": family, "params": params}, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def load_market(root: Path, symbols: list[str]) -> dict[str, Any]:
    frames: list[pd.DataFrame] = []
    required = ["timestamp", "open", "high", "low", "close", "volume", "symbol", "timeframe"]
    for symbol in symbols:
        path = root / "bybit_market" / symbol / "hour4.parquet"
        frame = pd.read_parquet(path)
        if frame.columns.tolist() != required:
            raise PortfolioSearchError(f"Unexpected schema for {symbol}")
        frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True)
        frame = frame.sort_values("timestamp").reset_index(drop=True)
        if frame["timestamp"].duplicated().any():
            raise PortfolioSearchError(f"Duplicate timestamps for {symbol}")
        if set(frame["symbol"].astype(str)) != {symbol} or set(frame["timeframe"].astype(str)) != {"hour4"}:
            raise PortfolioSearchError(f"Identity mismatch for {symbol}")
        frames.append(frame)
    timestamps = frames[0]["timestamp"]
    for frame in frames[1:]:
        if not timestamps.equals(frame["timestamp"]):
            raise PortfolioSearchError("BTC and ETH timestamps are not exactly aligned")
    return {
        "timestamps": timestamps,
        "open": np.column_stack([f["open"].to_numpy(float) for f in frames]),
        "high": np.column_stack([f["high"].to_numpy(float) for f in frames]),
        "low": np.column_stack([f["low"].to_numpy(float) for f in frames]),
        "close": np.column_stack([f["close"].to_numpy(float) for f in frames]),
        "symbols": symbols,
    }


def enumerate_candidates(cfg: dict[str, Any]) -> list[dict[str, Any]]:
    risk = cfg["search"]["risk"]
    overlays = list(itertools.product(risk["vol_days"], risk["target_vol"], risk["rebalance_days"]))
    quantum = float(risk["quantum"])
    output: list[dict[str, Any]] = []

    section = cfg["search"]["dual_rotation"]
    for lookbacks, absolute_days, ma_days, minimum_return, allocation, overlay in itertools.product(
        section["lookback_sets"], section["absolute_days"], section["ma_filter_days"],
        section["minimum_absolute_return"], section["allocation"], overlays
    ):
        vol_days, target_vol, rebalance_days = overlay
        params = {
            "lookbacks": lookbacks, "absolute_days": absolute_days,
            "ma_filter_days": ma_days, "minimum_absolute_return": minimum_return,
            "allocation": allocation, "vol_days": vol_days,
            "target_vol": target_vol, "rebalance_days": rebalance_days,
            "quantum": quantum,
        }
        output.append({"id": candidate_id("dual_rotation", params), "family": "dual_rotation", "params": params})

    section = cfg["search"]["trend_risk_parity"]
    for lookbacks, threshold, ma_days, overlay in itertools.product(
        section["lookback_sets"], section["vote_threshold"], section["ma_filter_days"], overlays
    ):
        vol_days, target_vol, rebalance_days = overlay
        params = {
            "lookbacks": lookbacks, "vote_threshold": threshold,
            "ma_filter_days": ma_days, "allocation": "inverse_vol",
            "vol_days": vol_days, "target_vol": target_vol,
            "rebalance_days": rebalance_days, "quantum": quantum,
        }
        output.append({"id": candidate_id("trend_risk_parity", params), "family": "trend_risk_parity", "params": params})

    section = cfg["search"]["relative_breakout"]
    for entry_days, exit_days, ma_days, allocation, overlay in itertools.product(
        section["entry_days"], section["exit_days"], section["ma_filter_days"],
        section["allocation"], overlays
    ):
        if exit_days >= entry_days:
            continue
        vol_days, target_vol, rebalance_days = overlay
        params = {
            "entry_days": entry_days, "exit_days": exit_days,
            "ma_filter_days": ma_days, "allocation": allocation,
            "vol_days": vol_days, "target_vol": target_vol,
            "rebalance_days": rebalance_days, "quantum": quantum,
        }
        output.append({"id": candidate_id("relative_breakout", params), "family": "relative_breakout", "params": params})
    return output


def structural_key(candidate: dict[str, Any]) -> str:
    excluded = {"vol_days", "target_vol", "rebalance_days", "quantum"}
    params = {k: v for k, v in candidate["params"].items() if k not in excluded}
    return json.dumps({"family": candidate["family"], "params": params}, sort_keys=True)


def rolling_ema(values: np.ndarray, days: int) -> np.ndarray:
    if days == 0:
        return np.full_like(values, np.nan)
    return np.column_stack([
        pd.Series(values[:, i]).ewm(span=bars(days), adjust=False, min_periods=bars(days)).mean().to_numpy(float)
        for i in range(values.shape[1])
    ])


def lag_return(values: np.ndarray, days: int) -> np.ndarray:
    periods = bars(days)
    output = np.full_like(values, np.nan)
    output[periods:] = values[periods:] / values[:-periods] - 1.0
    return output


def build_structural_state(market: dict[str, Any], candidate: dict[str, Any]) -> tuple[np.ndarray, np.ndarray]:
    close = market["close"]
    p = candidate["params"]
    family = candidate["family"]
    n, assets = close.shape

    if family == "dual_rotation":
        normalized = []
        for lookback in p["lookbacks"]:
            ret = lag_return(close, int(lookback))
            normalized.append(np.log1p(np.maximum(ret, -0.999999)) / math.sqrt(float(lookback)))
        score = np.nanmedian(np.stack(normalized, axis=2), axis=2)
        absolute = lag_return(close, int(p["absolute_days"]))
        eligible = absolute > float(p["minimum_absolute_return"])
        if int(p["ma_filter_days"]):
            ma = rolling_ema(close, int(p["ma_filter_days"]))
            eligible &= close > ma
        eligible &= np.isfinite(score)
        return score, eligible

    if family == "trend_risk_parity":
        votes = np.stack([(lag_return(close, int(x)) > 0).astype(float) for x in p["lookbacks"]], axis=2)
        score = votes.mean(axis=2)
        eligible = score >= float(p["vote_threshold"])
        if int(p["ma_filter_days"]):
            ma = rolling_ema(close, int(p["ma_filter_days"]))
            eligible &= close > ma
        return score, eligible

    if family == "relative_breakout":
        entry = bars(int(p["entry_days"]))
        exit_ = bars(int(p["exit_days"]))
        states = np.zeros((n, assets), dtype=float)
        score = np.full((n, assets), np.nan, dtype=float)
        ma = rolling_ema(close, int(p["ma_filter_days"])) if int(p["ma_filter_days"]) else None
        for asset in range(assets):
            series = pd.Series(close[:, asset])
            prior_high = series.shift(1).rolling(entry, min_periods=entry).max().to_numpy(float)
            prior_low = series.shift(1).rolling(exit_, min_periods=exit_).min().to_numpy(float)
            state = 0.0
            for index, price in enumerate(close[:, asset]):
                filter_ok = ma is None or (np.isfinite(ma[index, asset]) and price > ma[index, asset])
                if state == 0.0 and np.isfinite(prior_high[index]) and price > prior_high[index] and filter_ok:
                    state = 1.0
                elif state == 1.0 and np.isfinite(prior_low[index]) and price < prior_low[index]:
                    state = 0.0
                states[index, asset] = state
                if np.isfinite(prior_high[index]) and prior_high[index] > 0:
                    score[index, asset] = price / prior_high[index] - 1.0
        return score, states > 0

    raise PortfolioSearchError(f"Unsupported family: {family}")


def realized_vol(close: np.ndarray, days: int) -> np.ndarray:
    result = []
    for asset in range(close.shape[1]):
        returns = pd.Series(close[:, asset]).pct_change()
        vol = returns.rolling(bars(days), min_periods=bars(days)).std(ddof=0) * math.sqrt(BARS_PER_YEAR)
        result.append(vol.to_numpy(float))
    return np.column_stack(result)


def construct_weights(
    state: tuple[np.ndarray, np.ndarray],
    vol: np.ndarray,
    candidate: dict[str, Any],
) -> np.ndarray:
    score, eligible = state
    p = candidate["params"]
    n, assets = score.shape
    base = np.zeros((n, assets), dtype=float)
    allocation = p["allocation"]

    if allocation == "winner":
        masked = np.where(eligible & np.isfinite(score), score, -np.inf)
        winners = np.argmax(masked, axis=1)
        valid = np.isfinite(masked[np.arange(n), winners]) & (masked[np.arange(n), winners] > -np.inf)
        base[np.arange(n)[valid], winners[valid]] = 1.0
    elif allocation == "inverse_vol":
        inverse = np.divide(1.0, vol, out=np.zeros_like(vol), where=(vol > 0) & np.isfinite(vol))
        inverse *= eligible.astype(float)
        totals = inverse.sum(axis=1, keepdims=True)
        base = np.divide(inverse, totals, out=np.zeros_like(inverse), where=totals > 0)
    else:
        raise PortfolioSearchError(f"Unsupported allocation: {allocation}")

    risk_proxy = np.sum(base * np.where(np.isfinite(vol), vol, 0.0), axis=1)
    scale = np.divide(float(p["target_vol"]), risk_proxy, out=np.zeros(n), where=risk_proxy > 0)
    scale = np.clip(scale, 0.0, 1.0)
    raw = base * scale[:, None]

    rebalance = bars(int(p["rebalance_days"]))
    source = (np.arange(n) // rebalance) * rebalance
    held = raw[source]
    quantum = float(p["quantum"])
    held = np.clip(np.round(held / quantum) * quantum, 0.0, 1.0)
    sums = held.sum(axis=1)
    excessive = sums > 1.0
    held[excessive] /= sums[excessive, None]
    held[~np.isfinite(held)] = 0.0
    return held


def period_indices(timestamps: pd.Series, period: dict[str, str]) -> np.ndarray:
    start = pd.Timestamp(period["start"], tz="UTC")
    end = pd.Timestamp(period["end"], tz="UTC")
    return np.flatnonzero(((timestamps >= start) & (timestamps < end)).to_numpy())


def approximate_backtest(
    market: dict[str, Any], weights: np.ndarray, period: dict[str, str], cost_bps: float
) -> dict[str, Any]:
    idx = period_indices(market["timestamps"], period)
    if len(idx) < 3:
        raise PortfolioSearchError("Period has fewer than three bars")
    close = market["close"][idx]
    selected = weights[idx]
    asset_returns = close[1:] / close[:-1] - 1.0
    positions = selected[:-1]
    previous = np.vstack([np.zeros((1, positions.shape[1])), positions[:-1]])
    turnover_by_asset = np.abs(positions - previous)
    net = np.sum(positions * asset_returns, axis=1) - turnover_by_asset.sum(axis=1) * cost_bps / 10000.0
    if len(net):
        net[-1] -= np.abs(positions[-1]).sum() * cost_bps / 10000.0
    net = np.maximum(net, -0.999999)
    equity = np.r_[1.0, np.cumprod(1.0 + net)]
    drawdown = equity / np.maximum.accumulate(equity) - 1.0
    sd = float(np.std(net, ddof=0))
    sharpe = float(np.mean(net) / sd * math.sqrt(BARS_PER_YEAR)) if sd > 0 else 0.0
    changes = np.abs(np.diff(np.vstack([np.zeros((1, positions.shape[1])), positions]), axis=0)) > 1e-12
    asset_fills = changes.sum(axis=0).astype(int)
    if np.abs(positions[-1]).sum() > 1e-12:
        asset_fills += (np.abs(positions[-1]) > 1e-12).astype(int)
    return {
        "total_return": float(equity[-1] - 1.0),
        "max_drawdown": float(-drawdown.min()),
        "sharpe": sharpe,
        "fill_count": int(asset_fills.sum()),
        "asset_fill_counts": asset_fills.tolist(),
        "turnover": float(turnover_by_asset.sum() + np.abs(positions[-1]).sum()),
        "average_exposure": float(np.mean(positions.sum(axis=1))),
    }


def exact_backtest(
    market: dict[str, Any], weights: np.ndarray, period: dict[str, str], profile: dict[str, float]
) -> dict[str, Any]:
    idx = period_indices(market["timestamps"], period)
    if len(idx) < 3:
        raise PortfolioSearchError("Period has fewer than three bars")
    opens = market["open"][idx]
    closes = market["close"][idx]
    selected = weights[idx]
    cash = float(profile["initial_cash"])
    quantity = np.zeros(opens.shape[1], dtype=float)
    fee_rate = float(profile["fee_bps"]) / 10000.0
    slippage = float(profile["slippage_bps"]) / 10000.0
    equity_rows: list[float] = []
    total_fees = 0.0
    total_notional = 0.0
    asset_fills = np.zeros(opens.shape[1], dtype=int)

    for row in range(len(idx)):
        if row > 0:
            equity_at_open = cash + float(np.dot(quantity, opens[row]))
            desired_quantity = equity_at_open * selected[row - 1] / opens[row]
            changes = desired_quantity - quantity
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
        equity_rows.append(cash + float(np.dot(quantity, closes[row])))

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
        "average_exposure": float(np.mean(selected[:-1].sum(axis=1))),
    }


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    returns = [float(x["total_return"]) for x in rows]
    drawdowns = [float(x["max_drawdown"]) for x in rows]
    sharpes = [float(x["sharpe"]) for x in rows]
    fills = [int(x["fill_count"]) for x in rows]
    turnovers = [float(x["turnover"]) for x in rows]
    result = {
        "count": len(rows),
        "positive_ratio": sum(value > 0 for value in returns) / len(returns),
        "median_return": float(median(returns)),
        "worst_return": float(min(returns)),
        "worst_drawdown": float(max(drawdowns)),
        "median_sharpe": float(median(sharpes)),
        "minimum_sharpe": float(min(sharpes)),
        "minimum_fill_count": int(min(fills)),
        "median_turnover": float(median(turnovers)),
    }
    result["score"] = (
        result["median_sharpe"] + 1.3 * result["median_return"]
        + 0.25 * result["positive_ratio"] - 1.2 * result["worst_drawdown"]
        - 0.002 * result["median_turnover"]
    )
    return result


def development_checks(summary: dict[str, Any], gate: dict[str, Any]) -> dict[str, bool]:
    return {
        "positive_ratio": summary["positive_ratio"] >= gate["minimum_positive_ratio"],
        "median_return": summary["median_return"] >= gate["minimum_median_return"],
        "worst_return": summary["worst_return"] >= gate["minimum_worst_return"],
        "drawdown": summary["worst_drawdown"] <= gate["maximum_drawdown"],
        "median_sharpe": summary["median_sharpe"] >= gate["minimum_median_sharpe"],
        "minimum_sharpe": summary["minimum_sharpe"] >= gate["minimum_sharpe"],
        "fills": summary["minimum_fill_count"] >= gate["minimum_fill_count"],
    }


def stress_checks(result: dict[str, Any], gate: dict[str, Any]) -> dict[str, bool]:
    return {
        "return": result["total_return"] >= gate["minimum_total_return"],
        "drawdown": result["max_drawdown"] <= gate["maximum_drawdown"],
        "sharpe": result["sharpe"] >= gate["minimum_sharpe"],
        "fills": result["fill_count"] >= gate["minimum_fill_count"],
        "both_assets_used": min(result["asset_fill_counts"]) >= gate["minimum_asset_fill_count"],
    }


def evaluate_development(
    market: dict[str, Any], weights: np.ndarray, periods: list[dict[str, str]],
    mode: str, profile: dict[str, float] | None = None, cost_bps: float = 0.0
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    rows = []
    for fold, period in enumerate(periods, 1):
        metric = exact_backtest(market, weights, period, profile) if mode == "exact" else approximate_backtest(market, weights, period, cost_bps)
        rows.append({"fold": fold, "start": period["start"], "end": period["end"], **metric})
    return summarize(rows), rows


def flatten_candidate(row: dict[str, Any]) -> dict[str, Any]:
    output = dict(row)
    output["params"] = json.dumps(output["params"], sort_keys=True)
    output["failed_checks"] = json.dumps(output.get("failed_checks", []))
    return output


def run_search(manifest_path: Path, output_root: Path) -> dict[str, Any]:
    cfg = json.loads(manifest_path.read_text(encoding="utf-8"))
    market = load_market(Path(cfg["dataset"]["dataset_root"]), cfg["symbols"])
    candidates = enumerate_candidates(cfg)
    conservative = cfg["execution"]["conservative"]
    approximate_cost = float(conservative["fee_bps"]) + float(conservative["slippage_bps"])
    state_cache: dict[str, tuple[np.ndarray, np.ndarray]] = {}
    vol_cache: dict[int, np.ndarray] = {}
    approximate_rows: list[dict[str, Any]] = []

    for candidate in candidates:
        key = structural_key(candidate)
        if key not in state_cache:
            state_cache[key] = build_structural_state(market, candidate)
        vol_days = int(candidate["params"]["vol_days"])
        if vol_days not in vol_cache:
            vol_cache[vol_days] = realized_vol(market["close"], vol_days)
        weights = construct_weights(state_cache[key], vol_cache[vol_days], candidate)
        summary, _ = evaluate_development(
            market, weights, cfg["development_folds"], "approx", cost_bps=approximate_cost
        )
        checks = development_checks(summary, cfg["development_gate"])
        approximate_rows.append({
            **candidate, **summary, "passes": all(checks.values()),
            "failed_checks": [name for name, passed in checks.items() if not passed],
        })

    approximate_rows.sort(key=lambda item: item["score"], reverse=True)
    approximate_passers = [item for item in approximate_rows if item["passes"]]
    finalists = (approximate_passers or approximate_rows)[: int(cfg["search"]["top_exact"])]
    candidate_by_id = {item["id"]: item for item in candidates}
    weight_cache: dict[str, np.ndarray] = {}
    exact_rows: list[dict[str, Any]] = []
    exact_runs: list[dict[str, Any]] = []

    for approximate in finalists:
        candidate = candidate_by_id[approximate["id"]]
        key = structural_key(candidate)
        weights = construct_weights(state_cache[key], vol_cache[int(candidate["params"]["vol_days"])], candidate)
        weight_cache[candidate["id"]] = weights
        summary, runs = evaluate_development(
            market, weights, cfg["development_folds"], "exact", profile=conservative
        )
        checks = development_checks(summary, cfg["development_gate"])
        exact_rows.append({
            **candidate, **summary, "passes": all(checks.values()),
            "failed_checks": [name for name, passed in checks.items() if not passed],
        })
        exact_runs.extend({"candidate_id": candidate["id"], "family": candidate["family"], **run} for run in runs)

    exact_rows.sort(key=lambda item: item["score"], reverse=True)
    ranked = [item for item in exact_rows if item["passes"]] or exact_rows
    exact_passers = [item for item in exact_rows if item["passes"]]
    passer_families = sorted({item["family"] for item in exact_passers})
    development_plateau = len(exact_passers) >= 10 and len(passer_families) >= 2

    components: list[dict[str, Any]] = []
    family_count: dict[str, int] = {}
    for item in ranked:
        if family_count.get(item["family"], 0) >= 3:
            continue
        components.append(item)
        family_count[item["family"]] = family_count.get(item["family"], 0) + 1
        if len(components) >= int(cfg["search"]["ensemble_size"]):
            break

    ensemble_weights = np.median(
        np.stack([weight_cache[item["id"]] for item in components], axis=2), axis=2
    )
    ensemble_sums = ensemble_weights.sum(axis=1)
    excessive = ensemble_sums > 1.0
    ensemble_weights[excessive] /= ensemble_sums[excessive, None]
    ensemble_summary, ensemble_runs = evaluate_development(
        market, ensemble_weights, cfg["development_folds"], "exact", profile=conservative
    )
    ensemble_checks = development_checks(ensemble_summary, cfg["development_gate"])
    best = ranked[0]

    if ensemble_summary["score"] >= best["score"] and all(ensemble_checks.values()):
        selected_weights = ensemble_weights
        selected = {
            "type": "median_ensemble",
            "components": [
                {"id": item["id"], "family": item["family"], "params": item["params"]}
                for item in components
            ],
            "development": ensemble_summary,
            "development_checks": ensemble_checks,
        }
        selected_development_runs = ensemble_runs
    else:
        selected_weights = weight_cache[best["id"]]
        selected = {
            "type": "single",
            "id": best["id"], "family": best["family"], "params": best["params"],
            "development": {key: best[key] for key in [
                "positive_ratio", "median_return", "worst_return", "worst_drawdown",
                "median_sharpe", "minimum_sharpe", "minimum_fill_count",
                "median_turnover", "score"
            ]},
            "development_checks": development_checks(best, cfg["development_gate"]),
        }
        selected_development_runs = [run for run in exact_runs if run["candidate_id"] == best["id"]]

    stress_results: dict[str, Any] = {}
    stress_gate_results: dict[str, Any] = {}
    for profile_name in ["conservative", "stress"]:
        result = exact_backtest(
            market, selected_weights, cfg["recent_stress_period"], cfg["execution"][profile_name]
        )
        stress_results[profile_name] = result
        stress_gate_results[profile_name] = stress_checks(
            result, cfg["recent_stress_gate"][profile_name]
        )

    qualifies = bool(
        development_plateau
        and all(selected["development_checks"].values())
        and all(stress_gate_results["conservative"].values())
        and all(stress_gate_results["stress"].values())
    )
    report = {
        "experiment_id": cfg["experiment_id"],
        "dataset_archive_sha256": cfg["dataset"]["archive_sha256"],
        "methodology_note": (
            "The recent stress period overlaps a previously viewed benchmark period and is not "
            "treated as pristine out-of-sample evidence. Qualification permits prospective "
            "paper-forward review only."
        ),
        "summary": {
            "candidate_count": len(candidates),
            "approximate_gate_passers": len(approximate_passers),
            "exact_evaluated": len(exact_rows),
            "exact_gate_passers": len(exact_passers),
            "passing_families": passer_families,
            "development_plateau": development_plateau,
            "qualifies_for_prospective_paper_forward_review": qualifies,
            "automatic_paper_forward_started": False,
            "live_trading_enabled": False,
        },
        "selected_strategy": selected,
        "selected_development_runs": selected_development_runs,
        "recent_stress_results": stress_results,
        "recent_stress_checks": stress_gate_results,
        "decision": (
            "eligible_for_separate_prospective_paper_forward_review"
            if qualifies else "continue_research_no_promotion"
        ),
    }

    output_root.mkdir(parents=True, exist_ok=True)
    (output_root / "portfolio_search_v3.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (output_root / "selected_portfolio_strategy.json").write_text(
        json.dumps(selected, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    pd.DataFrame([flatten_candidate(item) for item in approximate_rows[:1000]]).to_csv(
        output_root / "top_approximate_candidates.csv", index=False
    )
    pd.DataFrame([flatten_candidate(item) for item in exact_rows]).to_csv(
        output_root / "exact_candidates.csv", index=False
    )
    pd.DataFrame(exact_runs).to_csv(output_root / "exact_development_runs.csv", index=False)
    pd.DataFrame(selected_development_runs).to_csv(
        output_root / "selected_development_runs.csv", index=False
    )
    pd.DataFrame([
        {"profile": profile, **result}
        for profile, result in stress_results.items()
    ]).to_csv(output_root / "recent_stress_results.csv", index=False)
    shutil.copy2(manifest_path, output_root / manifest_path.name)
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, default=Path("experiments/bybit_portfolio_search_v3.json"))
    parser.add_argument("--output", type=Path, default=Path("build/bybit_portfolio_search_v3"))
    parser.add_argument("--require-qualified", action="store_true")
    args = parser.parse_args()
    report = run_search(args.manifest, args.output)
    print(json.dumps(report["summary"], sort_keys=True))
    if args.require_qualified and not report["summary"]["qualifies_for_prospective_paper_forward_review"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
