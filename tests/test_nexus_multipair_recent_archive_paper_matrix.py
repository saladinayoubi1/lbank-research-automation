from __future__ import annotations

import json
from pathlib import Path

import pytest

import nexus_multipair_recent_archive_paper_matrix as paper


SOURCE_SHA = "a" * 40
SNAPSHOT_DIGEST = "b" * 64
DATA_AS_OF_MS = 1_788_480_000_000


def _snapshot() -> dict:
    return {
        "snapshot_digest": SNAPSHOT_DIGEST,
        "history_limit": 240,
        "cell_count": 12,
        "runtime_requalification_recency_verified": True,
        "live_freshness_claimed": False,
        "research_only": True,
        "paper_execution_started": False,
        "live_trading_authority": False,
        "private_credentials_used": False,
        "real_exchange_orders": False,
        "automatic_strategy_promotion": False,
        "issue_984_state_touched": False,
        "data_as_of_ms": DATA_AS_OF_MS,
    }


def test_load_verified_snapshot_requires_digest_and_authority(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "snapshot"
    root.mkdir()
    (root / "snapshot-manifest.json").write_text(json.dumps(_snapshot()), encoding="utf-8")
    monkeypatch.setattr(
        paper.recent,
        "verify_recent_archive_runtime_snapshot",
        lambda *args, **kwargs: {"decision": "pass"},
    )
    value = paper.load_verified_snapshot(
        root,
        expected_snapshot_digest=SNAPSHOT_DIGEST,
        source_sha=SOURCE_SHA,
        now_ms=DATA_AS_OF_MS + 1,
    )
    assert value["snapshot_digest"] == SNAPSHOT_DIGEST

    with pytest.raises(paper.MultiPairRecentArchivePaperError, match="digest mismatch"):
        paper.load_verified_snapshot(
            root,
            expected_snapshot_digest="c" * 64,
            source_sha=SOURCE_SHA,
            now_ms=DATA_AS_OF_MS + 1,
        )

    broken = _snapshot()
    broken["live_trading_authority"] = True
    (root / "snapshot-manifest.json").write_text(json.dumps(broken), encoding="utf-8")
    with pytest.raises(paper.MultiPairRecentArchivePaperError, match="authority boundary"):
        paper.load_verified_snapshot(
            root,
            expected_snapshot_digest=SNAPSHOT_DIGEST,
            source_sha=SOURCE_SHA,
            now_ms=DATA_AS_OF_MS + 1,
        )


def test_snapshot_dataset_fetcher_rebinds_exact_requested_window(tmp_path: Path, monkeypatch) -> None:
    step_ms = 14_400_000
    end_ms = DATA_AS_OF_MS - step_ms
    start_ms = end_ms - 239 * step_ms
    rows = [
        {"open_time_ms": start_ms + index * step_ms}
        for index in range(240)
    ]

    def bind(root, snapshot, *, symbol, timeframe):
        assert Path(root) == tmp_path.resolve()
        assert snapshot["snapshot_digest"] == SNAPSHOT_DIGEST
        assert symbol == "BTCUSDT"
        assert timeframe == "hour4"
        return {
            "instrument": "BTC/USDT",
            "source": "Bybit",
            "source_symbol": "BTCUSDT",
            "interval": "240",
            "paper_only": True,
            "row_count": 240,
            "rows": rows,
            "binding_sha256": "d" * 64,
        }

    monkeypatch.setattr(paper.runtime_snapshot, "bind_transported_runtime_dataset", bind)
    fetcher = paper.build_snapshot_dataset_fetcher(tmp_path, _snapshot())
    result = fetcher(
        canonical_symbol="BTC/USDT",
        source_symbol="BTCUSDT",
        interval="240",
        now_ms=DATA_AS_OF_MS,
        start_time_ms=start_ms,
        end_time_ms=end_ms,
        limit=240,
    )
    assert result["binding_sha256"] == "d" * 64

    with pytest.raises(paper.MultiPairRecentArchivePaperError, match="closed 240-row window"):
        fetcher(
            canonical_symbol="BTC/USDT",
            source_symbol="BTCUSDT",
            interval="240",
            now_ms=DATA_AS_OF_MS,
            start_time_ms=start_ms,
            end_time_ms=end_ms,
            limit=239,
        )


def test_run_cycle_injects_archive_fetcher_and_pins_matrix_clock(tmp_path: Path, monkeypatch) -> None:
    manifest = {"matrix_id": "test"}
    state = {"state_digest": "seed"}
    snapshot = _snapshot()
    monkeypatch.setattr(paper, "load_manifest", lambda path: manifest)
    monkeypatch.setattr(paper, "load_or_migrate_state", lambda *args, **kwargs: (state, None))
    monkeypatch.setattr(paper, "load_verified_snapshot", lambda *args, **kwargs: snapshot)
    monkeypatch.setattr(paper, "build_snapshot_dataset_fetcher", lambda *args, **kwargs: object())

    def supervisor(**kwargs):
        assert "dataset_fetcher" in kwargs
        assert kwargs["now_ms"] == DATA_AS_OF_MS
        return {"ok": True}

    monkeypatch.setattr(paper, "run_supervisor_once", supervisor)

    next_state = {
        "data_mode": paper.recent.TRANSPORT_ORIGIN,
        "dataset_sha256": SNAPSHOT_DIGEST,
    }
    matrix_snapshot = {
        "data_mode": paper.recent.TRANSPORT_ORIGIN,
        "dataset_sha256": SNAPSHOT_DIGEST,
        "paper_only": True,
        "live_trading_authority": False,
        "private_credentials_used": False,
        "automatic_strategy_promotion": False,
        "deterministic_risk_final_authority": True,
    }

    def matrix_cycle(**kwargs):
        assert kwargs["data_mode"] == paper.recent.TRANSPORT_ORIGIN
        assert kwargs["dataset_sha256"] == SNAPSHOT_DIGEST
        assert kwargs["now_resolver"]("BTCUSDT", "hour4", -1, 240) == DATA_AS_OF_MS
        assert kwargs["runner"](
            source_sha=SOURCE_SHA,
            state_root=tmp_path,
            symbol="BTCUSDT",
            timeframe="hour4",
            families=("momentum",),
            limit=240,
            now_ms=DATA_AS_OF_MS,
        ) == {"ok": True}
        return next_state, matrix_snapshot

    monkeypatch.setattr(paper, "run_matrix_cycle", matrix_cycle)
    monkeypatch.setattr(paper, "verify_v2_snapshot", lambda *args, **kwargs: {"decision": "pass"})

    actual_state, actual_snapshot, migration = paper.run_recent_archive_paper_cycle(
        manifest_path=tmp_path / "manifest.json",
        legacy_manifest_path=tmp_path / "legacy.json",
        state_path=tmp_path / "state.json",
        state_root=tmp_path,
        snapshot_root=tmp_path / "recent",
        expected_snapshot_digest=SNAPSHOT_DIGEST,
        source_sha=SOURCE_SHA,
        run_id="123",
        now_ms=DATA_AS_OF_MS + 1,
    )
    assert actual_state is next_state
    assert actual_snapshot is matrix_snapshot
    assert migration is None


def test_run_cycle_rejects_cursor_ahead_of_archive(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(paper, "load_manifest", lambda path: {"matrix_id": "test"})
    monkeypatch.setattr(paper, "load_or_migrate_state", lambda *args, **kwargs: ({}, None))
    monkeypatch.setattr(paper, "load_verified_snapshot", lambda *args, **kwargs: _snapshot())
    monkeypatch.setattr(paper, "build_snapshot_dataset_fetcher", lambda *args, **kwargs: object())

    def matrix_cycle(**kwargs):
        last_hour4 = DATA_AS_OF_MS - 14_400_000
        with pytest.raises(paper.MultiPairRecentArchivePaperError, match="cursor is ahead"):
            kwargs["now_resolver"]("BTCUSDT", "hour4", last_hour4 + 14_400_000, 240)
        return (
            {"data_mode": paper.recent.TRANSPORT_ORIGIN, "dataset_sha256": SNAPSHOT_DIGEST},
            {
                "data_mode": paper.recent.TRANSPORT_ORIGIN,
                "dataset_sha256": SNAPSHOT_DIGEST,
                "paper_only": True,
                "live_trading_authority": False,
                "private_credentials_used": False,
                "automatic_strategy_promotion": False,
                "deterministic_risk_final_authority": True,
            },
        )

    monkeypatch.setattr(paper, "run_matrix_cycle", matrix_cycle)
    monkeypatch.setattr(paper, "verify_v2_snapshot", lambda *args, **kwargs: {"decision": "pass"})
    paper.run_recent_archive_paper_cycle(
        manifest_path=tmp_path / "manifest.json",
        legacy_manifest_path=tmp_path / "legacy.json",
        state_path=tmp_path / "state.json",
        state_root=tmp_path,
        snapshot_root=tmp_path / "recent",
        expected_snapshot_digest=SNAPSHOT_DIGEST,
        source_sha=SOURCE_SHA,
        run_id="123",
        now_ms=DATA_AS_OF_MS + 1,
    )
