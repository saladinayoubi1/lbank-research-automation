from __future__ import annotations

from pathlib import Path

import nexus_a7_daily_recent_source as source


def _inventories():
    days = source.expected_days("2026-09-02", "2026-10-01")
    return {
        symbol: source.backfill.ArchiveInventory(
            symbol=symbol,
            monthly={"2026-09": f"{symbol}-2026-09.csv.gz"},
            daily={day: f"{symbol}_{day}.csv.gz" for day in days},
        )
        for symbol in source.SYMBOLS
    }


def test_a7_recent_window_is_exactly_30_complete_days():
    assert source.window_start("2026-10-01") == "2026-09-02"
    days = source.expected_days("2026-09-02", "2026-10-01")
    assert len(days) == 30
    assert days[0] == "2026-09-02"
    assert days[-1] == "2026-10-01"


def test_daily_only_inventory_strips_monthly_surface():
    inventory = next(iter(_inventories().values()))
    daily = source.daily_only_inventory(inventory)
    assert daily.symbol == inventory.symbol
    assert daily.monthly == {}
    assert daily.daily == inventory.daily


def test_acquire_forces_four_symbol_daily_only_120_archive_surface(tmp_path, monkeypatch):
    inventories = _inventories()
    monkeypatch.setattr(
        source.backfill,
        "fetch_archive_inventory",
        lambda symbol: inventories[symbol],
    )
    monkeypatch.setattr(
        source.recent,
        "select_latest_common_complete_date",
        lambda values, now_ms: "2026-10-01",
    )
    captured = {}

    def fake_run_backfill(**kwargs):
        captured.update(kwargs)
        for symbol in source.SYMBOLS:
            selected = kwargs["inventory_fetcher"](symbol)
            assert selected.monthly == {}
            assert len(selected.daily) == 30
        return {"summary": {"backfill_complete": True}}

    monkeypatch.setattr(source.backfill, "run_backfill", fake_run_backfill)
    proof = {
        "schema": source.SCHEMA,
        "source_sha": "a" * 40,
        "source_window_start": "2026-09-02",
        "source_window_end": "2026-10-01",
        "archive_source_count": 120,
        "dataset_digest": "b" * 64,
        "research_only": True,
        "automatic_strategy_promotion": False,
        "live_trading_authority": False,
    }
    monkeypatch.setattr(source, "build_proof", lambda *args, **kwargs: dict(proof))
    monkeypatch.setattr(source, "verify_proof", lambda *args, **kwargs: None)

    output = tmp_path / "proof"
    result = source.acquire(
        tmp_path / "state",
        tmp_path / "cache",
        output,
        source_sha="a" * 40,
        now_ms=1,
    )
    assert result == proof
    assert captured["start_date"] == "2026-09-02"
    assert captured["end_date"] == "2026-10-01"
    assert captured["max_archives_per_run"] == 120
    assert captured["symbols"] == source.SYMBOLS
    assert captured["clean"] is True
    assert (output / source.PROOF_NAME).is_file()
