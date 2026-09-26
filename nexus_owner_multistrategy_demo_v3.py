"""Owner-authorized four-strategy internal Paper portfolio, 500 USDT total.

Four ring-fenced sleeves share one aggregate budget/risk view. Conservative is
the primary account; stress is a parallel cost scenario, not extra capital.
All execution remains simulated. New strategies use spot signals with the
existing public derivatives execution model (including funding and lot sizes).
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import json
from pathlib import Path
import time

import numpy as np
import pandas as pd

import bybit_prospective_paper_forward_v1 as forward
import nexus_owner_consensus_demo_v2 as prior
import nexus_monthly_strategy_matrix_v1 as matrix
from bybit_derivatives_core_v1 import Client, Position, unrealized, funding_cashflow
from bybit_public_klines import fetch_closed_klines
from canonical_backtest import canonical_market_frame
from phase6_research_pipeline import bind_bybit_closed_dataset
from product_research_runtime import _public_mapping, _registry_path
from market_data_source_validator import load_and_validate

SELECTED = {"bollinger20_2": "ETHUSDT", "momentum20_ema100": "BTCUSDT",
            "macd12_26_9": "BTCUSDT"}
LANES = ("consensus", *SELECTED)
REPORT_DIGEST = "bd942023c70c2f87ff009f0baf31da7a8d97ce38a3112577090046be60793c5f"
GROSS_CAP = 0.95
ASSET_CAP = 0.60


def seal(value):
    core = dict(value)
    core.pop("digest", None)
    return {**core, "digest": forward._digest(core)}


def verified(value):
    if seal(value) != value:
        raise ValueError("portfolio state/activation digest mismatch")
    return value


def engine_digest():
    return forward._digest({"prior": prior.engine_digest(),
        "targets": forward._file_sha(Path(matrix.__file__)),
        "portfolio": forward._file_sha(Path(__file__))})


def assert_empty_prior(state, activation):
    forward.verify_state(state, activation["config"], activation["engine_sha256"])
    if activation["engine_sha256"] != prior.engine_digest():
        raise ValueError("prior runtime source mismatch")
    if state["completed_bar_count"] or state["events"] or state["last_execution_utc"]:
        raise ValueError("prior lane has observations; explicit position migration required")
    for p in state["profiles"].values():
        if (p["wallet"] != 500 or p["equity"] != 500 or p["fill_count"] or p["fees"]
                or p["funding_cashflow"] or any(x["quantity"] != 0 for x in p["positions"])):
            raise ValueError("prior account is not empty; refusing balance reset")


def make_initial(old_state, old_activation, report, source_sha):
    if len(source_sha) != 40 or any(c not in "0123456789abcdef" for c in source_sha):
        raise ValueError("exact source SHA required")
    assert_empty_prior(old_state, old_activation)
    if matrix.digest(report) != REPORT_DIGEST:
        raise ValueError("approved backtest report mismatch")
    for name, symbol in SELECTED.items():
        rows = [x for x in report["results"] if x["strategy"] == name and
                x["symbol"] == symbol and x["timeframe"] == "hour4" and x["profile"] == "stress"]
        if len(rows) != 1 or rows[0]["net_pnl"] <= 0:
            raise ValueError("selected strategy does not match owner-reviewed evidence")
    configs, lanes = {}, {}
    for name in LANES:
        cfg = deepcopy(old_activation["config"])
        cfg["forward_id"] = "owner-multi-v3-"+name+"-"+cfg["start_not_before_utc"]
        if name != "consensus":
            cfg["strategy_id"] = name
            cfg["strategy_manifest_sha256"] = forward._file_sha(Path(matrix.__file__))
        for profile in cfg["execution_profiles"].values():
            profile["initial_cash"] = 125.0
        configs[name] = cfg
        lanes[name] = forward.new_state(cfg, engine_sha256=engine_digest(), source_sha=source_sha, run_id=0)
    activation = seal({"schema": "nexus.owner-multistrategy-paper.v3", "configs": configs,
        "frozen": old_activation["frozen"], "source_sha": source_sha,
        "engine_digest": engine_digest(), "approved_report_digest": REPORT_DIGEST,
        "prior_state_digest": old_state["state_digest"], "initial_total_cash": 500,
        "gross_cap": GROSS_CAP, "asset_cap": ASSET_CAP, "selected": SELECTED,
        "owner_instruction_utc": "2026-09-26T17:30:33Z", "live_trading_authority": False,
        "mode": "internal_paper", "execution_market": "linear_derivatives_simulation"})
    state = seal({"lanes": lanes, "last_execution_utc": None, "halted": False, "halted_lanes": [],
        "aggregate_peak": {"conservative": 500.0, "stress": 500.0},
        "aggregate_max_drawdown": {"conservative": 0.0, "stress": 0.0},
        "activation_digest": activation["digest"], "live_trading_authority": False,
        "events": []})
    return activation, state


def initialize(root, prior_root, report_path, source_sha):
    ap, sp = root/"activation.json", root/"state.json"
    if ap.exists():
        activation = verified(json.loads(ap.read_text("utf-8")))
        if activation["engine_digest"] != engine_digest() or activation["source_sha"] != source_sha:
            raise ValueError("activated code changed")
        verify_state(json.loads(sp.read_text("utf-8")), activation)
        return activation
    if sp.exists():
        raise ValueError("orphan state; refusing reinitialization")
    if not (prior_root/"STOP").exists():
        raise ValueError("prior writer must be stopped before migration")
    with prior.writer_lock(prior_root):
        old_a = json.loads((prior_root/"activation.json").read_text("utf-8"))
        unsigned = dict(old_a)
        claimed = unsigned.pop("activation_sha256")
        if claimed != forward._digest(unsigned):
            raise ValueError("prior activation digest mismatch")
        old_s = json.loads((prior_root/"state.json").read_text("utf-8"))
        report = json.loads(report_path.read_text("utf-8"))
        activation, state = make_initial(old_s, old_a, report, source_sha)
        forward.save_state(root/"prior-state-preserved.json", old_s)
        forward.save_state(sp, state)
        forward.save_state(ap, activation)
    return activation


def verify_state(state, activation):
    verified(state)
    if state["activation_digest"] != activation["digest"] or set(state["lanes"]) != set(LANES):
        raise ValueError("portfolio identity changed")
    for name, lane in state["lanes"].items():
        forward.verify_state(lane, activation["configs"][name], activation["engine_digest"])
        if lane["last_execution_utc"] != state["last_execution_utc"]:
            raise ValueError("portfolio cursors diverged")


def opening_equity(p, marks, rates=None):
    rates = rates or [[], []]
    return p["wallet"] + sum(unrealized(Position(**x), marks[i])
        + sum(funding_cashflow(x["quantity"], marks[i], r) for r in rates[i])
        for i, x in enumerate(p["positions"]))


def capped_targets(state, raw, observation):
    """Pre-trade caps use opening marks only; never the bar's later high/close."""
    marks = [x["open"] for x in observation["mark"]]
    weights = {n: np.asarray(raw[n], dtype=float).copy() for n in LANES}
    if any(w.shape != (2,) or not np.isfinite(w).all() or np.abs(w).sum() > 1+1e-9
           for w in weights.values()):
        raise ValueError("invalid strategy weights")
    # Scaling only down preserves earlier constraints in BOTH cost scenarios.
    for p in ("conservative", "stress"):
        budgets = {n: opening_equity(state["lanes"][n]["profiles"][p], marks,
                                    observation["funding_rates"]) for n in LANES}
        if any(not np.isfinite(v) or v <= 0 for v in budgets.values()):
            raise ValueError("non-positive allocation equity")
        total = sum(budgets.values())
        for asset in range(2):
            gross = sum(abs(weights[n][asset])*budgets[n] for n in LANES)
            factor = min(1.0, ASSET_CAP*total/gross) if gross else 1.0
            for n in LANES:
                weights[n][asset] *= factor
        gross = sum(float(np.abs(weights[n]).sum())*budgets[n] for n in LANES)
        factor = min(1.0, GROSS_CAP*total/gross) if gross else 1.0
        for n in LANES:
            weights[n] *= factor
    return {n: w.tolist() for n, w in weights.items()}


def new_signals(activation, observations, root):
    if not observations:
        return {}, {}
    start = pd.Timestamp(activation["configs"]["consensus"]["start_not_before_utc"])
    first = int((start-pd.Timedelta(hours=4*matrix.WARMUP)).timestamp()*1000)
    last = int(pd.Timestamp(observations[-1]["execution_utc"]).timestamp()*1000)-forward.BAR_MS
    registry = load_and_validate(_registry_path())
    by_time = {o["execution_utc"]: {} for o in observations}
    bindings = {}
    for symbol in forward.SYMBOLS:
        mapping, source = _public_mapping(registry, symbol, "hour4")
        candles = []
        for lo in range(first, last+1, 1000*forward.BAR_MS):
            hi = min(last, lo+999*forward.BAR_MS)
            candles.extend(fetch_closed_klines(symbol, "240", now_ms=last+forward.BAR_MS,
                start_time_ms=lo, end_time_ms=hi, limit=(hi-lo)//forward.BAR_MS+1, timeout_seconds=20))
        dataset = bind_bybit_closed_dataset(candles, canonical_symbol=mapping["canonical_symbol"],
            source_symbol=source["symbol"], interval="240")
        artifact, frame = canonical_market_frame(dataset, registry_path=_registry_path())
        bindings[symbol] = artifact["binding_sha256"]
        data_root = root/"signal-data"
        data_root.mkdir(exist_ok=True)
        import gzip
        with gzip.open(data_root/(artifact["binding_sha256"]+".json.gz"), "wt", encoding="utf-8") as out:
            json.dump(artifact, out, sort_keys=True, allow_nan=False)
        opens = [x["open_time_ms"] for x in artifact["rows"]]
        if opens != list(range(first, last+forward.BAR_MS, forward.BAR_MS)):
            raise ValueError("strategy input has a missing bar")
        frame["volume"] = [float(x["volume"]) for x in artifact["rows"]]
        lookup = {x: i for i, x in enumerate(opens)}
        for name, selected_symbol in SELECTED.items():
            if selected_symbol != symbol:
                continue
            targets = matrix.targets(frame, name)
            for o in observations:
                idx = lookup[int(pd.Timestamp(o["execution_utc"]).timestamp()*1000)-forward.BAR_MS]
                weight = float(targets.iloc[idx])*.95
                by_time[o["execution_utc"]][name] = [weight if s == symbol else 0.0 for s in forward.SYMBOLS]
    return by_time, bindings


def step(state, activation, observation, signals, client, signal_bindings=None):
    when = observation["execution_utc"]
    if state["last_execution_utc"] and pd.Timestamp(when) <= pd.Timestamp(state["last_execution_utc"]):
        raise ValueError("duplicate or reversed portfolio bar")
    raw = {"consensus": observation["target_weights"], **signals}
    for n in state["halted_lanes"]:
        raw[n] = [0.0, 0.0]
    weights = ({n: [0.0, 0.0] for n in LANES} if state["halted"]
               else capped_targets(state, raw, observation))
    updated = deepcopy(state)
    windows = deepcopy(observation["minute_windows"])
    for name in LANES:
        obs = deepcopy(observation)
        obs["capture_execution_details"] = True
        lane = state["lanes"][name]
        obs["target_weights"] = weights[name]
        obs["target_changed"] = not np.allclose(weights[name],
            lane["profiles"]["conservative"]["target_weights"], atol=1e-12, rtol=0)
        if obs["target_changed"]:
            for asset, symbol in enumerate(forward.SYMBOLS):
                # Fetch a closing window too when an old target becomes flat.
                needed = weights[name][asset] or any(lane["profiles"][p]["positions"][asset]["quantity"]
                                                    for p in ("conservative", "stress"))
                if needed:
                    windows.setdefault(symbol, {})
                    for p, cfg in activation["configs"][name]["execution_profiles"].items():
                        if p not in windows[symbol]:
                            windows[symbol][p] = forward._minute_window(client, symbol,
                                pd.Timestamp(when), cfg["execution_window_minutes"])
        obs["minute_windows"] = deepcopy(windows)
        updated["lanes"][name] = forward.apply_observations(lane, [obs], activation["configs"][name],
            source_sha=activation["source_sha"], run_id=lane["last_run_id"]+1)
    updated["last_execution_utc"] = when
    for p in ("conservative", "stress"):
        equity = sum(updated["lanes"][n]["profiles"][p]["equity"] for n in LANES)
        updated["aggregate_peak"][p] = max(updated["aggregate_peak"][p], equity)
        dd = 1-equity/updated["aggregate_peak"][p]
        updated["aggregate_max_drawdown"][p] = max(updated["aggregate_max_drawdown"][p], dd)
        if dd > (0.15 if p == "conservative" else 0.20):
            updated["halted"] = True
    for n in LANES:
        if prior.risk_reasons(updated["lanes"][n], activation["configs"][n]):
            if n not in updated["halted_lanes"]:
                updated["halted_lanes"].append(n)
    updated["events"].append({"execution_utc": when, "raw_weights": raw, "risk_weights": weights,
        "market_evidence_digest": forward._digest(observation), "signal_dataset_bindings": signal_bindings or {},
        "halted": updated["halted"], "halted_lanes": list(updated["halted_lanes"])})
    return seal(updated)


def tick(root, activation, now):
    state = json.loads((root/"state.json").read_text("utf-8"))
    verify_state(state, activation)
    cfg = activation["configs"]["consensus"]
    cutoff = pd.Timestamp(state["last_execution_utc"] or cfg["start_not_before_utc"])
    due = cutoff+pd.Timedelta(hours=8 if state["last_execution_utc"] else 4)
    if pd.Timestamp(now) >= due:
        client = Client(cfg["api_base_urls"], 15, 4, .03)
        obs = forward.collect_observations(cfg, activation["frozen"], state["lanes"]["consensus"],
                                           now_utc=str(now), client=client)
        signals, bindings = new_signals(activation, obs, root)
        for o in obs:
            state = step(state, activation, o, signals[o["execution_utc"]], client, bindings)
            verify_state(state, activation)
            forward.save_state(root/"state.json", state)
    totals = {p: {"equity": sum(state["lanes"][n]["profiles"][p]["equity"] for n in LANES),
        "fills": sum(state["lanes"][n]["profiles"][p]["fill_count"] for n in LANES)}
        for p in ("conservative", "stress")}
    summary = {"status": "risk_halted" if state["halted"] else "running_waiting_for_closed_bar",
        "checked_at": str(now), "initial_total_cash": 500, "initial_allocation_each": 125,
        "strategies": list(LANES), "timeframe": "4h", "totals": totals, "halted_lanes": state["halted_lanes"],
        "last_execution_utc": state["last_execution_utc"], "start_not_before_utc": cfg["start_not_before_utc"],
        "live_trading_authority": False, "automatic_promotion": False,
        "mode": "internal_paper", "source_sha": activation["source_sha"], "state_digest": state["digest"]}
    forward.save_state(root/"status.json", summary)
    from product_shared_paper import build_snapshot, with_public_marks
    terminal = build_snapshot(state, activation, summary)
    if terminal["positions"]:
        terminal = with_public_marks(terminal, Client(cfg["api_base_urls"], 5, 2, 0), pd.Timestamp(now).to_pydatetime())
    forward.save_state(root/"terminal.json", terminal)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--prior-root", type=Path, required=True)
    parser.add_argument("--backtest-report", type=Path, required=True)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--loop", action="store_true")
    parser.add_argument("--snapshot-out", type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    with prior.writer_lock(root):
        activation = initialize(root, args.prior_root, args.backtest_report, args.source_sha)
        while not (root/"STOP").exists():
            try:
                tick(root, activation, pd.Timestamp.now(tz="UTC"))
                if args.snapshot_out:
                    if args.snapshot_out.name != "terminal.json" or args.snapshot_out.resolve() == (root/"state.json").resolve():
                        raise ValueError("invalid terminal export path")
                    forward.save_state(args.snapshot_out, json.loads((root/"terminal.json").read_text("utf-8")))
            except Exception as exc:
                forward.save_state(root/"last-error.json", {"error_type": type(exc).__name__,
                    "message": str(exc)[:400], "at": str(pd.Timestamp.now(tz="UTC"))})
                if not args.loop:
                    raise
            if not args.loop:
                break
            time.sleep(60)


if __name__ == "__main__":
    main()
