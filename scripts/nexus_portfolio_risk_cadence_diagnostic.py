"""One fixed daily target-ratchet falsification; original account engine reused.

No scheduler, exchange client, promotion, parameter search or future sources.
The ratchet changes targets, not inventory. Daily buys are explicitly audited.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

import bybit_portfolio_search_v3 as engine

SOURCE_COMMIT = "7383788754e1f7bef8e70e7df0c765b40e49e6ff"
ENGINE_SHA256_LF = "1f086b5958a59c19657dea5b642a888d9039d6db2fd088893f7870dd7f549688"
VERIFIER_SHA256_LF = "8848a9afaf034338923ce51de1fedb51912a02f32eefccdaef8e5b88891e09cb"
CONTRACT_SHA256 = "f909e7dc8beb34bac0efe13cbb9c8dc128996d42b305089ecae25d7cd39604bf"
BASELINE_CONFIG_SHA256 = "0d59b4c956ceec492c4c9b2f92062871f7603a9bb60f69a2e435a971597bc1e4"
DEFAULT_CONTRACT = Path("research/portfolio_risk_cadence_diagnostic_v1.json")
BASELINE_CONFIG = Path("research/portfolio_existing_engine_shared500_calibration_v1.json")
COST_PROFILE_NAMES = ("conservative", "stress", "severe")
BOOK_NAMES = ("baseline", "daily_target_ratchet", "baseline_times_075", "passive_BTC")
SYMBOLS = ["btc_usdt", "eth_usdt"]
PERIODS = {
    "continuous": {"start": "2023-09-01", "end": "2026-08-01"},
    "2023_09_to_2024_03": {"start": "2023-09-01", "end": "2024-03-01"},
    "2024_03_to_2024_09": {"start": "2024-03-01", "end": "2024-09-01"},
    "2024_09_to_2025_03": {"start": "2024-09-01", "end": "2025-03-01"},
    "2025_03_to_2025_10": {"start": "2025-03-01", "end": "2025-10-01"},
    "2025_10_to_2026_04": {"start": "2025-10-01", "end": "2026-04-01"},
    "2026_04_to_2026_08": {"start": "2026-04-01", "end": "2026-08-01"},
}
NEGATIVE_REGIMES = ("2024_03_to_2024_09", "2025_10_to_2026_04", "2026_04_to_2026_08")


class CadenceError(ValueError):
    pass


def digest(obj: Any) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, separators=(",", ":"),
                                   allow_nan=False).encode()).hexdigest()


def source_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def checked_baseline_config(path: Path) -> dict[str, Any]:
    """Bind the full reviewed candidate, costs, shared balance and authorities."""
    try:
        config = json.loads(path.read_text(encoding="utf-8-sig"))
        fingerprint = digest(config)
    except (OSError, UnicodeError, TypeError, ValueError) as exc:
        raise CadenceError("Invalid fixed baseline configuration") from exc
    if fingerprint != BASELINE_CONFIG_SHA256:
        raise CadenceError("Fixed baseline candidate, execution or authority changed")
    return config


def validate_market(market: dict[str, Any]) -> None:
    ts = market["timestamps"]
    if (market["symbols"] != SYMBOLS or not isinstance(ts, pd.Series)
            or str(ts.dtype) != "datetime64[ns, UTC]" or ts.isna().any()
            or ts.duplicated().any() or not ts.is_monotonic_increasing
            or ts.iloc[0] != pd.Timestamp("2022-12-01", tz="UTC")
            or not (ts.diff().dropna() == pd.Timedelta(hours=4)).all()
            or ts.iloc[-1] + pd.Timedelta(hours=4) != pd.Timestamp("2026-08-01", tz="UTC")):
        raise CadenceError("Exact original aligned historical UTC 4h source required")
    for key in ("open", "high", "low", "close"):
        v = market[key]
        if v.shape != (len(ts), 2) or not np.isfinite(v).all() or (v <= 0).any():
            raise CadenceError("Invalid physical source prices")
    if ((market["low"] > np.minimum(market["open"], market["close"])).any()
            or (market["high"] < np.maximum(market["open"], market["close"])).any()
            or (market["low"] > market["high"]).any()):
        raise CadenceError("Impossible source OHLC")


def target_ratchet(timestamps: pd.Series, baseline: np.ndarray, vol: np.ndarray,
                   weekly: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Causal state: only weekly reset may raise target or change winner.

    A daily observation is the *close* of the 20:00-open candle. The engine
    consumes that row's target at next 00:00 open. No daily scheduled drift
    rebalance is added: only an actual lower target causes an extra event.
    """
    if (baseline.shape != vol.shape or baseline.shape != (len(timestamps), 2)
            or weekly.shape != (len(timestamps),) or weekly.dtype != np.bool_
            or not np.isfinite(baseline).all() or (baseline < 0).any()
            or (baseline.sum(axis=1) > 1 + 1e-12).any()
            or (np.count_nonzero(baseline, axis=1) > 1).any()
            or not weekly[0] or timestamps.isna().any()
            or not (timestamps.diff().dropna() == pd.Timedelta(hours=4)).all()):
        raise CadenceError("Invalid synchronized winner-target inputs")
    output = np.zeros_like(baseline)
    reduced = np.zeros(len(timestamps), dtype=bool)
    held = np.zeros(2)
    for i, stamp in enumerate(timestamps):
        if weekly[i]:
            held = baseline[i].copy()
        elif stamp.hour == 20:
            active = np.flatnonzero(held > 0)
            if active.size:
                j = int(active[0])
                risk = vol[i, j]
                cap = (float(np.clip(np.round((0.30 / risk) / 0.25) * 0.25, 0, 1))
                       if np.isfinite(risk) and risk > 0 else 0.0)
                new = min(float(held[j]), cap)
                reduced[i] = new < held[j]
                held[j] = new
        output[i] = held
    return output, reduced


def verify_trace(market: dict[str, Any], trace: dict[str, Any], metrics: dict[str, Any],
                 profile: dict[str, float], period: dict[str, str],
                 daily_reductions: np.ndarray) -> dict[str, Any]:
    """Replay every fill and bind receipts/metrics to the exact period grid."""
    ts = market["timestamps"]
    idx = engine.period_indices(ts, period)
    if (not len(idx) or daily_reductions.shape != (len(ts),)
            or daily_reductions.dtype != np.bool_
            or trace["schema"] != "nexus.portfolio-v3-original-fill-trace.v1"
            or trace["symbols"] != SYMBOLS or trace["period"] != period
            or trace["initial_cash_usdt"] != profile["initial_cash"]
            or len(trace["equity_marks"]) != len(idx)):
        raise CadenceError("Trace header, period or mark coverage mismatch")
    row_by_open = {t: i for i, t in enumerate(ts)}
    allowed_rows = set(idx.tolist())
    fill_groups: dict[int, list[dict[str, Any]]] = {}
    previous_order = (-1, False)
    for sequence, fill in enumerate(trace["fills"]):
        k = row_by_open.get(pd.Timestamp(fill["source_bar_open_utc"]))
        terminal = fill["fill_kind"] == "terminal_bar_close"
        if (k not in allowed_rows or type(fill["sequence"]) is not int
                or fill["sequence"] != sequence or fill["symbol"] not in SYMBOLS
                or fill["side"] not in ("buy", "sell")
                or fill["fill_kind"] not in ("next_bar_open", "terminal_bar_close")
                or (terminal and (k != idx[-1] or fill["side"] != "sell"))
                or (not terminal and k == idx[0])
                or (k, terminal) < previous_order):
            raise CadenceError("Unaccounted, reordered or invalid fill")
        previous_order = (k, terminal)
        fill_groups.setdefault(k, []).append(fill)
    cash, quantity = float(profile["initial_cash"]), np.zeros(2)
    daily_buys = 0
    max_error = 0.0
    actual_exposure = []
    equity_rows = []
    total_fees = total_notional = 0.0
    asset_fills = np.zeros(2, dtype=int)
    for k, mark in zip(idx, trace["equity_marks"], strict=True):
        marked_quantity = np.asarray(mark["asset_quantities"], dtype=float)
        if (pd.Timestamp(mark["bar_closed_at_utc"]) != ts.iloc[k] + pd.Timedelta(hours=4)
                or marked_quantity.shape != (2,) or not np.isfinite(marked_quantity).all()
                or not np.isfinite([mark["equity_usdt"], mark["cash_usdt"]]).all()
                or mark["equity_usdt"] <= 0):
            raise CadenceError("Invalid or misdated equity mark")
        for fill in fill_groups.get(int(k), []):
            j = SYMBOLS.index(fill["symbol"])
            q, price, fee = (float(fill[x]) for x in ("quantity", "price_usdt", "fee_usdt"))
            if (not np.isfinite([q, price, fee, fill["cash_after_usdt"],
                                   fill["asset_quantity_after"]]).all()
                    or q <= 0 or price <= 0 or fee < 0):
                raise CadenceError("Invalid fill quantity, price, fee or account receipt")
            side = 1 if fill["side"] == "buy" else -1
            terminal = fill["fill_kind"] == "terminal_bar_close"
            expected_time = ts.iloc[k] + pd.Timedelta(hours=4) if terminal else ts.iloc[k]
            raw = market["close" if terminal else "open"][k, j]
            expected_price = raw * (1 + side * profile["slippage_bps"] / 10000)
            if (pd.Timestamp(fill["executed_at_utc"]) != expected_time
                    or not np.isclose(price, expected_price, rtol=1e-12, atol=1e-12)
                    or not np.isclose(fee, q * price * profile["fee_bps"] / 10000,
                                      rtol=1e-12, atol=1e-9)):
                raise CadenceError("Fill time, slippage or fee mismatch")
            cash -= side * q * price + fee
            quantity[j] += side * q
            if cash < -1e-7 or (quantity < -1e-10).any():
                raise CadenceError("Independent replay borrowed cash or inventory")
            if (abs(cash - fill["cash_after_usdt"]) > 1e-7
                    or abs(quantity[j] - fill["asset_quantity_after"]) > 1e-10):
                raise CadenceError("Per-fill account receipt mismatch")
            total_fees += fee
            total_notional += q * price
            asset_fills[j] += 1
            if side == 1 and not terminal and k > 0 and daily_reductions[k - 1]:
                daily_buys += 1
        reconstructed = cash + float(quantity @ market["close"][k])
        error = max(abs(reconstructed - mark["equity_usdt"]),
                    abs(cash - mark["cash_usdt"]),
                    float(np.max(np.abs(quantity - marked_quantity))))
        max_error = max(max_error, error)
        if error > 1e-7:
            raise CadenceError("Ledger and marked equity mismatch")
        actual_exposure.append(float(1 - cash / reconstructed))
        equity_rows.append(reconstructed)
    terminal_quantity = np.asarray(trace["terminal_quantities"], dtype=float)
    if (not np.allclose(quantity, 0, atol=1e-10)
            or terminal_quantity.shape != (2,) or not np.isfinite(terminal_quantity).all()
            or not np.allclose(terminal_quantity, quantity, rtol=0, atol=1e-10)
            or not np.isfinite(trace["terminal_cash_usdt"])
            or abs(trace["terminal_cash_usdt"] - cash) > 1e-7
            or abs(cash / profile["initial_cash"] - 1 - metrics["total_return"]) > 1e-9):
        raise CadenceError("Terminal account mismatch")
    equity = np.asarray(equity_rows)
    maximum_dd = float(-(equity / np.maximum.accumulate(equity) - 1).min())
    summary = [metrics[x] for x in ("total_return", "max_drawdown", "total_fees", "turnover")]
    if (not np.isfinite(summary).all()
            or type(metrics["fill_count"]) is not int
            or metrics["fill_count"] != len(trace["fills"])
            or not np.array_equal(metrics["asset_fill_counts"], asset_fills)
            or abs(metrics["max_drawdown"] - maximum_dd) > 1e-10
            or abs(metrics["total_fees"] - total_fees) > 1e-7
            or abs(metrics["turnover"] - total_notional / profile["initial_cash"]) > 1e-9):
        raise CadenceError("Aggregate fills, costs or drawdown mismatch")
    return {"ledger_replay_passed": True, "maximum_reconciliation_error_usdt": max_error,
            "actual_mean_marked_gross_exposure": float(np.mean(actual_exposure)),
            "target_mean_exposure_engine_field": metrics["average_exposure"],
            "buys_after_daily_target_reductions": daily_buys,
            "fills_sha256": digest(trace["fills"]),
            "equity_marks_sha256": digest(trace["equity_marks"])}


def falsification(results: dict[str, Any]) -> dict[str, Any]:
    if type(results) is not dict or set(results) != set(PERIODS):
        raise CadenceError("Fixed reporting periods are incomplete or changed")
    for books in results.values():
        if type(books) is not dict or set(books) != set(BOOK_NAMES):
            raise CadenceError("Fixed comparison books are incomplete or changed")
        for profiles in books.values():
            if type(profiles) is not dict or set(profiles) != set(COST_PROFILE_NAMES):
                raise CadenceError("All three fixed execution profiles are required")
    decisions = {}
    for profile in COST_PROFILE_NAMES:
        base = results["continuous"]["baseline"][profile]
        cand = results["continuous"]["daily_target_ratchet"][profile]
        fixed = results["continuous"]["baseline_times_075"][profile]
        reductions = {name: 100 * (results[name]["baseline"][profile]["max_drawdown"]
                                  - results[name]["daily_target_ratchet"][profile]["max_drawdown"])
                      for name in NEGATIVE_REGIMES}
        score = lambda r: r["total_return"] / r["max_drawdown"] if r["max_drawdown"] else 0.0
        checks = {
            "continuous_pnl_retained_at_least_90pct": cand["net_pnl_usdt"] >= .9 * base["net_pnl_usdt"],
            "each_negative_regime_dd_improved_at_least_3pp": all(x >= 3 for x in reductions.values()),
            "return_over_dd_exceeds_fixed075": score(cand) > score(fixed),
            "no_buys_at_any_daily_reduction": all(results[p]["daily_target_ratchet"][profile]
                ["qa"]["buys_after_daily_target_reductions"] == 0 for p in results),
        }
        decisions[profile] = {"checks": checks, "passes_all": all(checks.values()),
                              "negative_regime_dd_reduction_percentage_points": reductions}
    return {"by_cost_profile": decisions,
            "verdict": ("SURVIVES_DIAGNOSTIC_ONLY" if all(x["passes_all"] for x in decisions.values())
                        else "REJECT_FIXED_HYPOTHESIS_NO_RETUNE"),
            "independent_edge_established": False, "paper_eligible": False, "live_enabled": False}


def run(archive_root: Path, contract_path: Path, output_dir: Path) -> dict[str, Any]:
    # Reject changed execution inputs before importing any market-source path.
    config = checked_baseline_config(BASELINE_CONFIG)
    # Import the established source authenticator; no new trust-in-manifest path.
    from scripts import nexus_strategy_finder_shared_cash_eval as source_guard
    if source_hash(Path(engine.__file__)) != ENGINE_SHA256_LF:
        raise CadenceError("Original immutable engine source mismatch")
    if source_hash(Path(source_guard.__file__)) != VERIFIER_SHA256_LF:
        raise CadenceError("Original six-file authenticator mismatch")
    if output_dir.exists():
        raise CadenceError("A new write-once result directory is required")
    contract = json.loads(contract_path.read_text(encoding="utf-8-sig"))
    # All fixed contract content must match its separately recorded receipt.
    lock = json.loads(contract_path.with_suffix(".lock.json").read_text(encoding="utf-8-sig"))
    if (digest(contract) != CONTRACT_SHA256
            or lock != {"contract_sha256": CONTRACT_SHA256, "source_commit": SOURCE_COMMIT}):
        raise CadenceError("Fixed one-candidate contract lock mismatch")
    candidate = config["candidate"]
    if engine.candidate_id(candidate["family"], candidate["params"]) != "b4e4a2c33304aec1":
        raise CadenceError("Frozen original baseline changed")
    source_hashes = source_guard.verify_pinned_market_files(archive_root)
    market = engine.load_market(archive_root, SYMBOLS)
    validate_market(market)
    vol = engine.realized_vol(market["close"], 30)
    state = engine.build_structural_state(market, candidate)
    baseline = engine.construct_weights(state, vol, candidate)
    weekly = engine._candidate_rebalance_mask(len(baseline), candidate)
    ratchet, reductions = target_ratchet(market["timestamps"], baseline, vol, weekly)
    btc = np.zeros_like(baseline)
    btc[:, 0] = 1.0
    books = {"baseline": (baseline, weekly), "daily_target_ratchet": (ratchet, weekly),
             "baseline_times_075": (.75 * baseline, weekly), "passive_BTC": (btc, None)}
    output_dir.mkdir(parents=True)
    results = {}
    for period_name, period in PERIODS.items():
        results[period_name] = {}
        for name, (weights, schedule) in books.items():
            results[period_name][name] = {}
            for profile_name, profile in config["execution"].items():
                trace: dict[str, Any] = {}
                metrics = engine.exact_backtest(market, weights, period, profile,
                                               rebalance_mask=schedule, fill_trace=trace)
                qa = verify_trace(market, trace, metrics, profile, period,
                                  reductions if name == "daily_target_ratchet" else np.zeros_like(reductions))
                metrics["net_pnl_usdt"] = profile["initial_cash"] * metrics["total_return"]
                metrics["qa"] = qa
                results[period_name][name][profile_name] = metrics
                if period_name == "continuous" and profile_name == "conservative":
                    source_guard.write_once(output_dir / (name + "-trace.json"), trace)
    expected = results["continuous"]["baseline"]["conservative"]["net_pnl_usdt"]
    if not np.isclose(expected, 343.66115005, atol=1e-6):
        raise CadenceError("Pinned prior baseline economic evidence did not reproduce")
    evidence = {
        "schema": "nexus.portfolio-risk-cadence-diagnostic-result.v1",
        "source_commit": SOURCE_COMMIT, "source_hashes": source_hashes,
        "engine_sha256_lf": source_hash(Path(engine.__file__)),
        "script_sha256_lf": source_hash(Path(__file__)),
        "contract_sha256": digest(contract), "contract": contract,
        "baseline_config_sha256": digest(config),
        "execution_profiles": config["execution"],
        "source_history_preinspected": True, "source_4h_rows_per_asset": len(baseline),
        "candidate_count": 1, "parameter_search": False,
        "daily_target_reduction_events_full_source": int(reductions.sum()),
        "continuous_period_reduction_events": int(reductions[engine.period_indices(market["timestamps"], PERIODS["continuous"])].sum()),
        "periods": PERIODS, "results": results,
        "falsification": falsification(results),
        "exposure_note": "engine average_exposure is target mean; QA field is actual marked inventory/equity mean, final flat mark included",
        "reset_periods_are_not_additive_or_independent": True,
        "paper_eligible": False, "live_enabled": False, "orders": 0,
    }
    evidence["result_digest"] = digest(evidence)
    source_guard.write_once(output_dir / "result.json", evidence)
    return evidence


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--archive-root", type=Path, required=True)
    ap.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    ap.add_argument("--output-dir", type=Path, required=True)
    args = ap.parse_args()
    evidence = run(args.archive_root, args.contract, args.output_dir)
    print(json.dumps({"verdict": evidence["falsification"]["verdict"],
                      "result_digest": evidence["result_digest"],
                      "continuous": {name: {p: {k: v[k] for k in
                          ("net_pnl_usdt", "max_drawdown", "fill_count")}
                          for p, v in rows.items()} for name, rows in evidence["results"]["continuous"].items()}},
                     allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
