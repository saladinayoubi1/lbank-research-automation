from __future__ import annotations

import json
from pathlib import Path

import pytest

from nexus_demo_state_recovery import DemoStateRecoveryError, recover_bootstrap_journals
from nexus_demo_strategy_matrix import load_manifest, load_state
from product_runtime import ProductRuntime

FUTURE = "2026-08-26T21:50:00Z"
HISTORICAL_MS = 1_700_000_000_000


def _manifest() -> dict:
    return load_manifest(Path("config/nexus-demo-strategy-matrix-v1.json"))


def _state(tmp_path: Path, manifest: dict) -> dict:
    return load_state(tmp_path / "matrix-state.json", manifest)


def _runtime_root(root: Path) -> Path:
    return (
        root / "cells" / "ethusdt" / "hour4"
        / "portfolios" / "trend_breakout"
    )


def _resolver(*_args) -> int:
    return HISTORICAL_MS


def test_future_bootstrap_only_journal_is_quarantined_and_rebased_to_replay_clock(
    tmp_path: Path,
) -> None:
    manifest = _manifest()
    root = tmp_path / "state"
    runtime_root = _runtime_root(root)
    ProductRuntime(runtime_root, clock=lambda: FUTURE)
    journal = runtime_root / "product_runtime" / "paper-events.jsonl"
    legacy = journal.read_bytes()

    summary = recover_bootstrap_journals(
        manifest=manifest,
        state=_state(root, manifest),
        state_root=root,
        logical_now_resolver=_resolver,
    )

    assert summary["recovered_count"] == 1
    assert summary["paper_only"] is True
    assert summary["live_trading_authority"] is False
    assert not journal.exists()
    recovery = summary["recoveries"][0]
    quarantine = journal.parent / "quarantine" / "bootstrap-clock"
    archived = quarantine / recovery["quarantine_file"]
    evidence = quarantine / f"{recovery['journal_sha256']}.recovery.json"
    assert archived.read_bytes() == legacy
    assert json.loads(evidence.read_text(encoding="utf-8"))["recovery_digest"] == recovery["recovery_digest"]

    ProductRuntime(runtime_root, clock=lambda: "2023-11-14T22:13:20Z")
    rows = [json.loads(line) for line in journal.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 2
    assert rows[0]["occurred_at"].startswith("2023-11-14T22:13:20")


def test_future_stateful_paper_journal_is_never_reset(tmp_path: Path) -> None:
    manifest = _manifest()
    root = tmp_path / "state"
    runtime_root = _runtime_root(root)
    runtime = ProductRuntime(runtime_root, clock=lambda: FUTURE)
    runtime.submit_paper_order({
        "operation": "open",
        "symbol": "ETHUSDT",
        "timeframe": "hour4",
        "side": "long",
        "quantity": "0.01",
        "reference_price": "2000",
        "stop_price": "1900",
        "target_price": "2200",
    })
    journal = runtime_root / "product_runtime" / "paper-events.jsonl"
    before = journal.read_bytes()

    with pytest.raises(DemoStateRecoveryError, match="stateful Paper history"):
        recover_bootstrap_journals(
            manifest=manifest,
            state=_state(root, manifest),
            state_root=root,
            logical_now_resolver=_resolver,
        )

    assert journal.read_bytes() == before
    assert not (journal.parent / "quarantine").exists()
