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


class SearchError(RuntimeError):
    pass


def cid(family: str, params: dict[str, Any]) -> str:
    raw = json.dumps({"family": family, "params": params}, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def bars(days: int) -> int:
    return max(1, int(days) * BARS_PER_DAY)


def load_frame(root: Path, symbol: str) -> pd.DataFrame:
    path = root / "bybit_market" / symbol / "hour4.parquet"
    frame = pd.read_parquet(path)
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True)
    frame = frame.sort_values("timestamp").reset_index(drop=True)
    required = ["timestamp", "open", "high", "low", "close", "volume", "symbol", "timeframe"]
    if frame.columns.tolist() != required:
        raise SearchError(f"Unexpected schema for {symbol}: {frame.columns.tolist()}")
    if frame["timestamp"].duplicated().any():
        raise SearchError(f"Duplicate timestamps for {symbol}")
    if set(frame["symbol"].astype(str)) != {symbol} or set(frame["timeframe"].astype(str)) != {"hour4"}:
        raise SearchError(f"Identity mismatch for {symbol}")
    return frame


def enumerate_candidates(cfg: dict[str, Any]) -> list[dict[str, Any]]:
    risk = cfg["search"]["risk"]
    overlays = list(itertools.product(risk["vol_days"], risk["target_vol"], risk["rebalance_days"], risk["quantum"]))
    out: list[dict[str, Any]] = []

    e = cfg["search"]["ema"]
    for fast, slow, mom, ov in itertools.product(e["fast_days"], e["slow_days"], e["momentum_days"], overlays):
        if fast >= slow:
            continue
        vd, tv, rd, q = ov
        p = {"fast_days": fast, "slow_days": slow, "momentum_days": mom, "vol_days": vd, "target_vol": tv, "rebalance_days": rd, "quantum": q}
        out.append({"id": cid("ema", p), "family": "ema", "params": p})

    t = cfg["search"]["tsmom"]
    for lbs, threshold, ov in itertools.product(t["lookback_sets"], t["vote_threshold"], overlays):
        vd, tv, rd, q = ov
        p = {"lookbacks": lbs, "threshold": threshold, "vol_days": vd, "target_vol": tv, "rebalance_days": rd, "quantum": q}
        out.append({"id": cid("tsmom", p), "family": "tsmom", "params": p})

    b = cfg["search"]["breakout"]
    for entry, exit_, ma, ov in itertools.product(b["entry_days"], b["exit_days"], b["ma_filter_days"], overlays):
        if exit_ >= entry:
            continue
        vd, tv, rd, q = ov
        p = {"entry_days": entry, "exit_days": exit_, "ma_filter_days": ma, "vol_days": vd, "target_vol": tv, "rebalance_days": rd, "quantum": q}
        out.append({"id": cid("breakout", p), "family": "breakout", "params": p})

    h = cfg["search"]["hysteresis"]
    for ma, enter, exit_, ov in itertools.product(h["ma_days"], h["enter_buffer"], h["exit_buffer"], overlays):
        vd, tv, rd, q = ov
        p = {"ma_days": ma, "enter_buffer": enter, "exit_buffer": exit_, "vol_days": vd, "target_vol": tv, "rebalance_days": rd, "quantum": q}
        out.append({"id": cid("hysteresis", p), "family": "hysteresis", "params": p})
    return out


def structural_key(candidate: dict[str, Any]) -> str:
    risk_keys = {"vol_days", "target_vol", "rebalance_days", "quantum"}
    p = {k: v for k, v in candidate["params"].items() if k not in risk_keys}
    return json.dumps({"family": candidate["family"], "params": p}, sort_keys=True)


def signal(frame: pd.DataFrame, candidate: dict[str, Any]) -> np.ndarray:
    close = frame["close"].astype(float)
    p = candidate["params"]
    family = candidate["family"]
    if family == "ema":
        fast = close.ewm(span=bars(p["fast_days"]), adjust=False, min_periods=bars(p["fast_days"])).mean()
        slow = close.ewm(span=bars(p["slow_days"]), adjust=False, min_periods=bars(p["slow_days"])).mean()
        s = fast > slow
        if p["momentum_days"]:
            s &= close.pct_change(bars(p["momentum_days"])) > 0
        return s.fillna(False).to_numpy(float)
    if family == "tsmom":
        votes = np.column_stack([(close.pct_change(bars(x)) > 0).fillna(False).to_numpy(float) for x in p["lookbacks"]])
        return (votes.mean(axis=1) >= float(p["threshold"])).astype(float)
    if family == "breakout":
        hi = close.shift(1).rolling(bars(p["entry_days"]), min_periods=bars(p["entry_days"])).max().to_numpy(float)
        lo = close.shift(1).rolling(bars(p["exit_days"]), min_periods=bars(p["exit_days"])).min().to_numpy(float)
        ma = None
        if p["ma_filter_days"]:
            ma = close.ewm(span=bars(p["ma_filter_days"]), adjust=False, min_periods=bars(p["ma_filter_days"])).mean().to_numpy(float)
        prices = close.to_numpy(float)
        out = np.zeros(len(frame)); state = 0.0
        for i, price in enumerate(prices):
            filter_ok = ma is None or (np.isfinite(ma[i]) and price > ma[i])
            if state == 0 and np.isfinite(hi[i]) and price > hi[i] and filter_ok:
                state = 1.0
            elif state == 1 and np.isfinite(lo[i]) and price < lo[i]:
                state = 0.0
            out[i] = state
        return out
    if family == "hysteresis":
        ma = close.ewm(span=bars(p["ma_days"]), adjust=False, min_periods=bars(p["ma_days"])).mean().to_numpy(float)
        prices = close.to_numpy(float)
        out = np.zeros(len(frame)); state = 0.0
        for i, price in enumerate(prices):
            if not np.isfinite(ma[i]):
                continue
            if state == 0 and price > ma[i] * (1 + p["enter_buffer"]):
                state = 1.0
            elif state == 1 and price < ma[i] * (1 - p["exit_buffer"]):
                state = 0.0
            out[i] = state
        return out
    raise SearchError(f"Unknown family {family}")


def realized_vol(frame: pd.DataFrame, days: int) -> np.ndarray:
    r = frame["close"].astype(float).pct_change()
    return (r.rolling(bars(days), min_periods=bars(days)).std(ddof=0) * math.sqrt(BARS_PER_YEAR)).to_numpy(float)


def target(frame: pd.DataFrame, candidate: dict[str, Any], sig: np.ndarray, vol: np.ndarray) -> pd.Series:
    p = candidate["params"]
    raw = np.divide(float(p["target_vol"]), vol, out=np.zeros(len(frame)), where=vol > 0)
    raw = np.clip(raw, 0, 1) * sig
    rb = bars(p["rebalance_days"])
    source = (np.arange(len(frame)) // rb) * rb
    raw = raw[source]
    q = float(p["quantum"])
    raw = np.clip(np.round(raw / q) * q, 0, 1)
    raw[~np.isfinite(raw)] = 0
    return pd.Series(raw, index=frame.index)


def period_mask(frame: pd.DataFrame, period: dict[str, str]) -> pd.Series:
    start = pd.Timestamp(period["start"], tz="UTC")
    end = pd.Timestamp(period["end"], tz="UTC")
    return (frame["timestamp"] >= start) & (frame["timestamp"] < end)


def approx(frame: pd.DataFrame, targets: pd.Series, period: dict[str, str], cost_bps: float) -> dict[str, Any]:
    m = period_mask(frame, period)
    f = frame.loc[m].reset_index(drop=True)
    t = targets.loc[m].reset_index(drop=True).to_numpy(float)
    close = f["close"].to_numpy(float)
    ret = close[1:] / close[:-1] - 1
    pos = t[:-1]
    prev = np.r_[0.0, pos[:-1]]
    turnover = np.abs(pos - prev)
    net = pos * ret - turnover * cost_bps / 10000
    if len(net):
        net[-1] -= abs(pos[-1]) * cost_bps / 10000
    net = np.maximum(net, -0.999999)
    equity = np.r_[1.0, np.cumprod(1 + net)]
    dd = equity / np.maximum.accumulate(equity) - 1
    sd = float(np.std(net, ddof=0))
    sh = float(np.mean(net) / sd * math.sqrt(BARS_PER_YEAR)) if sd > 0 else 0.0
    fills = int((np.abs(np.diff(np.r_[0.0, pos])) > 1e-12).sum() + (abs(pos[-1]) > 1e-12))
    return {"total_return": float(equity[-1] - 1), "max_drawdown": float(-dd.min()), "sharpe": sh, "turnover": float(turnover.sum() + abs(pos[-1])), "fill_count": fills}


def exact(frame: pd.DataFrame, targets: pd.Series, period: dict[str, str], profile: dict[str, float]) -> dict[str, Any]:
    m = period_mask(frame, period)
    f = frame.loc[m].reset_index(drop=True)
    t = targets.loc[m].reset_index(drop=True).to_numpy(float)
    cash = float(profile["initial_cash"]); qty = 0.0
    fee_rate = float(profile["fee_bps"]) / 10000
    slip = float(profile["slippage_bps"]) / 10000
    equity = []; total_notional = 0.0; total_fees = 0.0; fills = 0
    for i, row in f.iterrows():
        if i > 0:
            ref = float(row.open); eopen = cash + qty * ref
            desired = eopen * t[i - 1] / ref
            dq = desired - qty
            if abs(dq) > 1e-12:
                fill = ref * (1 + slip if dq > 0 else 1 - slip)
                notional = abs(dq * fill); fee = notional * fee_rate
                cash -= dq * fill + fee; qty += dq
                total_notional += notional; total_fees += fee; fills += 1
        equity.append(cash + qty * float(row.close))
    if abs(qty) > 1e-12:
        ref = float(f.iloc[-1].close); dq = -qty
        fill = ref * (1 + slip if dq > 0 else 1 - slip)
        notional = abs(dq * fill); fee = notional * fee_rate
        cash -= dq * fill + fee; qty = 0.0
        total_notional += notional; total_fees += fee; fills += 1
        equity[-1] = cash
    e = np.asarray(equity, float)
    rets = pd.Series(e).pct_change().replace([np.inf, -np.inf], np.nan).dropna().to_numpy(float)
    dd = e / np.maximum.accumulate(e) - 1
    sd = float(np.std(rets, ddof=0)) if len(rets) else 0.0
    sh = float(np.mean(rets) / sd * math.sqrt(BARS_PER_YEAR)) if sd > 0 else 0.0
    return {"total_return": float(e[-1] / profile["initial_cash"] - 1), "max_drawdown": float(-dd.min()), "sharpe": sh, "fill_count": fills, "total_fees": total_fees, "turnover": total_notional / profile["initial_cash"]}


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    r = [x["total_return"] for x in rows]; d = [x["max_drawdown"] for x in rows]
    s = [x["sharpe"] for x in rows]; f = [x["fill_count"] for x in rows]; to = [x["turnover"] for x in rows]
    out = {"count": len(rows), "positive_ratio": sum(x > 0 for x in r) / len(r), "median_return": float(median(r)), "worst_return": float(min(r)), "worst_drawdown": float(max(d)), "median_sharpe": float(median(s)), "minimum_sharpe": float(min(s)), "minimum_fill_count": int(min(f)), "median_turnover": float(median(to))}
    out["score"] = out["median_sharpe"] + 1.25 * out["median_return"] + 0.2 * out["positive_ratio"] - 1.1 * out["worst_drawdown"] - 0.002 * out["median_turnover"]
    return out


def checks(summary: dict[str, Any], gate: dict[str, Any]) -> dict[str, bool]:
    return {"positive_ratio": summary["positive_ratio"] >= gate["minimum_positive_ratio"], "median_return": summary["median_return"] >= gate["minimum_median_return"], "worst_return": summary["worst_return"] >= gate["minimum_worst_return"], "drawdown": summary["worst_drawdown"] <= gate["maximum_drawdown"], "median_sharpe": summary["median_sharpe"] >= gate["minimum_median_sharpe"], "minimum_sharpe": summary["minimum_sharpe"] >= gate["minimum_sharpe"], "fills": summary["minimum_fill_count"] >= gate["minimum_fill_count"]}


def evaluate(frames: dict[str, pd.DataFrame], targets: dict[str, pd.Series], periods: list[dict[str, str]], mode: str, profile: dict[str, float] | None = None, cost_bps: float = 0) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    rows = []
    for pi, period in enumerate(periods, 1):
        for symbol, frame in frames.items():
            metric = exact(frame, targets[symbol], period, profile) if mode == "exact" else approx(frame, targets[symbol], period, cost_bps)
            rows.append({"fold": pi, "symbol": symbol, **metric})
    return summarize(rows), rows


def run(manifest_path: Path, output: Path) -> dict[str, Any]:
    cfg = json.loads(manifest_path.read_text())
    root = Path(cfg["dataset"]["dataset_root"])
    frames = {s: load_frame(root, s) for s in cfg["symbols"]}
    candidates = enumerate_candidates(cfg)
    sig_cache = {s: {} for s in frames}; vol_cache = {s: {} for s in frames}
    conservative = cfg["execution"]["conservative"]
    cost = conservative["fee_bps"] + conservative["slippage_bps"]
    approx_rows = []
    for candidate in candidates:
        ts = {}
        sk = structural_key(candidate)
        for symbol, frame in frames.items():
            if sk not in sig_cache[symbol]:
                sig_cache[symbol][sk] = signal(frame, candidate)
            vd = candidate["params"]["vol_days"]
            if vd not in vol_cache[symbol]:
                vol_cache[symbol][vd] = realized_vol(frame, vd)
            ts[symbol] = target(frame, candidate, sig_cache[symbol][sk], vol_cache[symbol][vd])
        summary, _ = evaluate(frames, ts, cfg["development_folds"], "approx", cost_bps=cost)
        gate = checks(summary, cfg["development_gate"])
        approx_rows.append({**candidate, **summary, "passes": all(gate.values()), "failed": [k for k, v in gate.items() if not v]})
    approx_rows.sort(key=lambda x: x["score"], reverse=True)
    passers = [x for x in approx_rows if x["passes"]]
    finalists = (passers or approx_rows)[: cfg["search"]["top_exact"]]
    byid = {x["id"]: x for x in candidates}; target_cache = {}; exact_rows = []; exact_runs = []
    for row in finalists:
        candidate = byid[row["id"]]; ts = {}
        sk = structural_key(candidate)
        for symbol, frame in frames.items():
            ts[symbol] = target(frame, candidate, sig_cache[symbol][sk], vol_cache[symbol][candidate["params"]["vol_days"]])
        target_cache[candidate["id"]] = ts
        summary, runs = evaluate(frames, ts, cfg["development_folds"], "exact", profile=conservative)
        gate = checks(summary, cfg["development_gate"])
        exact_rows.append({**candidate, **summary, "passes": all(gate.values()), "failed": [k for k, v in gate.items() if not v]})
        exact_runs += [{"candidate_id": candidate["id"], "family": candidate["family"], **x} for x in runs]
    exact_rows.sort(key=lambda x: x["score"], reverse=True)
    ranked = [x for x in exact_rows if x["passes"]] or exact_rows
    selected_components = []; family_counts = {}
    for row in ranked:
        if family_counts.get(row["family"], 0) >= 2:
            continue
        selected_components.append(row); family_counts[row["family"]] = family_counts.get(row["family"], 0) + 1
        if len(selected_components) == cfg["search"]["ensemble_size"]:
            break
    ensemble = {}
    for symbol in frames:
        ensemble[symbol] = pd.concat([target_cache[x["id"]][symbol] for x in selected_components], axis=1).median(axis=1)
    ens_summary, ens_runs = evaluate(frames, ensemble, cfg["development_folds"], "exact", profile=conservative)
    ens_gate = checks(ens_summary, cfg["development_gate"])
    best = ranked[0]
    if ens_summary["score"] >= best["score"]:
        selected = {"type": "median_ensemble", "components": [{"id": x["id"], "family": x["family"], "params": x["params"]} for x in selected_components], "development": ens_summary, "passes_development": all(ens_gate.values())}
        chosen = ensemble
    else:
        selected = {"type": "single", "id": best["id"], "family": best["family"], "params": best["params"], "development": {k: best[k] for k in ["positive_ratio", "median_return", "worst_return", "worst_drawdown", "median_sharpe", "minimum_sharpe", "minimum_fill_count", "median_turnover", "score"]}, "passes_development": best["passes"]}
        chosen = target_cache[best["id"]]
    locked = [cfg["locked_test"]]; locked_rows = []; summaries = {}; final_checks = {}
    for name in ["conservative", "stress"]:
        summary, rows = evaluate(frames, chosen, locked, "exact", profile=cfg["execution"][name])
        summaries[name] = summary; final_checks[name] = checks(summary, cfg["final_gate"][name])
        locked_rows += [{"profile": name, **x} for x in rows]
    qualifies = bool(selected["passes_development"] and all(final_checks["conservative"].values()) and all(final_checks["stress"].values()))
    report = {"experiment_id": cfg["experiment_id"], "dataset_archive_sha256": cfg["dataset"]["archive_sha256"], "summary": {"candidate_count": len(candidates), "approximate_gate_passers": len(passers), "exact_evaluated": len(exact_rows), "exact_gate_passers": sum(x["passes"] for x in exact_rows), "qualifies_for_paper_forward_review": qualifies, "automatic_paper_forward_started": False, "live_trading_enabled": False}, "selected_strategy": selected, "locked_test_summaries": summaries, "locked_test_runs": locked_rows, "final_checks": final_checks, "decision": "eligible_for_separate_paper_forward_review" if qualifies else "continue_research_no_promotion"}
    output.mkdir(parents=True, exist_ok=True)
    (output / "strategy_search_v2.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    pd.DataFrame([{**x, "params": json.dumps(x["params"], sort_keys=True), "failed": json.dumps(x["failed"])} for x in approx_rows[:500]]).to_csv(output / "top_approximate_candidates.csv", index=False)
    pd.DataFrame([{**x, "params": json.dumps(x["params"], sort_keys=True), "failed": json.dumps(x["failed"])} for x in exact_rows]).to_csv(output / "exact_candidates.csv", index=False)
    pd.DataFrame(exact_runs).to_csv(output / "exact_development_runs.csv", index=False)
    pd.DataFrame(locked_rows).to_csv(output / "locked_test_runs.csv", index=False)
    (output / "selected_strategy.json").write_text(json.dumps(selected, indent=2, sort_keys=True) + "\n")
    shutil.copy2(manifest_path, output / manifest_path.name)
    return report


def main() -> int:
    p = argparse.ArgumentParser(); p.add_argument("--manifest", type=Path, default=Path("experiments/bybit_strategy_search_v2.json")); p.add_argument("--output", type=Path, default=Path("build/bybit_strategy_search_v2")); p.add_argument("--require-qualified", action="store_true")
    args = p.parse_args(); report = run(args.manifest, args.output); print(json.dumps(report["summary"], sort_keys=True))
    return 1 if args.require_qualified and not report["summary"]["qualifies_for_paper_forward_review"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
