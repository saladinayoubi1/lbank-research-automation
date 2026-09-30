"""Owner-authorized single-strategy 500-USDT Paper runtime with terminal projection.

Runs only the frozen bybit_btc_eth_regime_consensus_v1 strategy. It never sends
exchange orders, never uses private credentials, never promotes to Live, and
writes a read-only terminal snapshot for the NEXUS desktop UI.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from copy import deepcopy
import json
import os
from pathlib import Path
import time

import pandas as pd

import bybit_prospective_paper_forward_v1 as forward
from bybit_public_klines import _active_mainnet_base_urls
from bybit_derivatives_core_v1 import Client
from product_shared_paper import build_snapshot, seal, with_public_marks

ROOT = Path(__file__).resolve().parent
OLD_MANIFEST = ROOT / "experiments/bybit_prospective_paper_forward_v1.json"
SCHEMA = "nexus.owner-consensus-paper.v3"


def engine_digest():
    files = [
        Path(__file__),
        ROOT / "bybit_prospective_paper_forward_v1.py",
        ROOT / "bybit_derivatives_core_v1.py",
        ROOT / "bybit_derivatives_validation_v1.py",
        ROOT / "bybit_regime_search_v6.py",
        ROOT / "bybit_consensus_search_v5.py",
        ROOT / "product_shared_paper.py",
    ]
    return forward._digest({p.name: forward._file_sha(p) for p in files})


def make_config(now):
    original, frozen = forward.load_contract(OLD_MANIFEST)
    config = deepcopy(original)
    start = pd.Timestamp(now).tz_convert("UTC").floor("4h") + pd.Timedelta(hours=4)
    config["start_not_before_utc"] = forward._utc_text(start)
    config["forward_id"] = "owner-consensus-paper-v3-" + start.strftime("%Y%m%dT%H%MZ")
    config["api_base_urls"] = list(_active_mainnet_base_urls()[1])
    config["maximum_attempts"] = 4
    config["timeout_seconds"] = 15
    for name, profile in config["execution_profiles"].items():
        profile["initial_cash"] = 500.0
        config["completion_gates"][name]["minimum_fill_count"] = 0
        config["completion_gates"][name]["minimum_asset_fill_count"] = 0
    return config, frozen


@contextmanager
def writer_lock(root):
    handle = (root / "writer.lock").open("a+b")
    try:
        handle.seek(0)
        handle.write(b"0")
        handle.flush()
        handle.seek(0)
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield
    finally:
        handle.close()


def initialize(root, source_sha, now):
    root.mkdir(parents=True, exist_ok=True)
    if len(source_sha) != 40 or any(c not in "0123456789abcdef" for c in source_sha):
        raise ValueError("exact source SHA required")
    activation_path = root / "activation.json"
    if activation_path.exists():
        activation = json.loads(activation_path.read_text("utf-8"))
        if activation["engine_sha256"] != engine_digest() or activation["source_sha"] != source_sha:
            raise ValueError("activated source changed")
        core = dict(activation)
        claimed = core.pop("activation_sha256")
        if claimed != forward._digest(core):
            raise ValueError("activation contract changed")
        if not (root / "state.json").exists():
            raise ValueError("existing activation lost state; refusing capital reset")
        return activation
    if (root / "state.json").exists():
        raise ValueError("orphan state must not be overwritten")
    config, frozen = make_config(now)
    activation = {
        "schema": SCHEMA,
        "config": config,
        "frozen": frozen,
        "source_sha": source_sha,
        "engine_sha256": engine_digest(),
        "activated_at": str(now),
        "mode": "internal_paper",
        "paper_only": True,
        "live_trading_authority": False,
        "private_credentials_allowed": False,
        "automatic_promotion": False,
    }
    state = forward.new_state(
        config,
        engine_sha256=activation["engine_sha256"],
        source_sha=source_sha,
        run_id=0,
    )
    forward.save_state(root / "state.json", state)
    activation["activation_sha256"] = forward._digest(activation)
    forward.save_state(activation_path, activation)
    return activation


def risk_reasons(state, config):
    reasons = []
    for name, profile in state["profiles"].items():
        gate = config["completion_gates"][name]
        for metric in (
            "maximum_drawdown",
            "maximum_margin_utilization",
            "maximum_risk_tier_utilization",
        ):
            if profile[metric] > gate[metric]:
                reasons.append(name + ":" + metric)
        if profile["liquidations"] or profile["equity"] <= 0:
            reasons.append(name + ":liquidation_or_insolvency")
    return reasons


def _terminal_wrapper(state, activation, summary):
    terminal_activation = seal({
        "configs": {"consensus": activation["config"]},
        "source_sha": activation["source_sha"],
        "paper_only": True,
        "live_trading_authority": False,
    })
    terminal_state = seal({
        "lanes": {"consensus": state},
        "last_execution_utc": state["last_execution_utc"],
        "halted_lanes": ["consensus"] if summary["risk_reasons"] else [],
        "aggregate_max_drawdown": {
            name: float(profile["maximum_drawdown"])
            for name, profile in state["profiles"].items()
        },
        "activation_digest": terminal_activation["digest"],
    })
    return build_snapshot(terminal_state, terminal_activation, summary)


def tick(root, activation, now, client=None, snapshot_out=None):
    config = activation["config"]
    state = json.loads((root / "state.json").read_text("utf-8"))
    forward.verify_state(state, config, activation["engine_sha256"])
    reasons = risk_reasons(state, config)
    status = "risk_halted" if reasons else "waiting_for_closed_bar"
    cutoff = pd.Timestamp(state["last_execution_utc"] or config["start_not_before_utc"])
    due = cutoff + pd.Timedelta(hours=4 if state["last_execution_utc"] is None else 8)
    market_client = client or Client(config["api_base_urls"], 15, 4, 0.03)
    if not reasons and pd.Timestamp(now) >= due:
        observations = forward.collect_observations(
            config,
            activation["frozen"],
            state,
            now_utc=str(now),
            client=market_client,
        )
        for observation in observations:
            observation = deepcopy(observation)
            observation["capture_execution_details"] = True
            state = forward.apply_observations(
                state,
                [observation],
                config,
                source_sha=activation["source_sha"],
                run_id=state["last_run_id"] + 1,
            )
            forward.verify_state(state, config, activation["engine_sha256"])
            forward.save_state(root / "state.json", state)
            reasons = risk_reasons(state, config)
            if reasons:
                break
        status = "risk_halted" if reasons else "paper_running"
    summary = {
        "status": status,
        "checked_at": str(now),
        "risk_reasons": reasons,
        "start_not_before_utc": config["start_not_before_utc"],
        "completed_bars": state["completed_bar_count"],
        "profiles": state["profiles"],
        "state_sha256": state["state_digest"],
        "live_trading_authority": False,
        "automatic_promotion": False,
        "paper_only": True,
        "mode": "internal_paper",
        "strategy_id": config["strategy_id"],
    }
    forward.save_state(root / "status.json", summary)

    terminal = _terminal_wrapper(state, activation, summary)
    if terminal["positions"]:
        terminal = with_public_marks(
            terminal,
            market_client,
            pd.Timestamp(now).to_pydatetime(),
        )
    forward.save_state(root / "terminal.json", terminal)
    if snapshot_out is not None:
        destination = Path(snapshot_out)
        destination.parent.mkdir(parents=True, exist_ok=True)
        forward.save_state(destination, terminal)
    return summary, terminal


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--snapshot-out", type=Path)
    parser.add_argument("--loop", action="store_true")
    args = parser.parse_args()
    root = args.root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    with writer_lock(root):
        activation = initialize(root, args.source_sha, pd.Timestamp.now(tz="UTC"))
        while not (root / "STOP").exists():
            try:
                tick(
                    root,
                    activation,
                    pd.Timestamp.now(tz="UTC"),
                    snapshot_out=args.snapshot_out,
                )
            except Exception as exc:
                forward.save_state(root / "last-error.json", {
                    "at": str(pd.Timestamp.now(tz="UTC")),
                    "error_type": type(exc).__name__,
                    "message": str(exc)[:400],
                    "live_trading_authority": False,
                    "paper_only": True,
                })
                if not args.loop:
                    raise
            if not args.loop:
                break
            time.sleep(60)


if __name__ == "__main__":
    main()
