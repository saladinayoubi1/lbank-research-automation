from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

import bybit_spot_backfill as backfill


def inventory(symbol: str) -> backfill.ArchiveInventory:
    return backfill.ArchiveInventory(
        symbol=symbol,
        monthly={
            "2022-12": f"{symbol}-2022-12.csv.gz",
            "2023-01": f"{symbol}-2023-01.csv.gz",
        },
        daily={
            f"2022-11-{day:02d}": f"{symbol}_2022-11-{day:02d}.csv.gz"
            for day in range(10, 31)
        },
    )


def write_month_archive(path: Path, period: str) -> None:
    month = pd.Period(period, freq="M")
    timestamps = pd.date_range(
        month.start_time.tz_localize("UTC"),
        month.end_time.floor("15min").tz_localize("UTC"),
        freq="15min",
    )
    frame = pd.DataFrame(
        {
            "id": [str(index + 1) for index in range(len(timestamps))],
            "timestamp": timestamps.astype("int64") // 1_000_000,
            "price": 100.0 + pd.Series(range(len(timestamps))) / 10000.0,
            "volume": 1.0,
            "side": ["buy", "sell"] * (len(timestamps) // 2),
            "rpi": 0,
        }
    )
    frame.to_csv(path, index=False, compression="gzip")


def make_downloader(source_root: Path):
    def downloader(symbol, filename, cache_root):
        path = source_root / filename
        return {
            "symbol": symbol,
            "filename": filename,
            "url": f"test://{filename}",
            "path": path.as_posix(),
            "size_bytes": path.stat().st_size,
            "sha256": "test",
            "http_status": 200,
            "download_attempts": 1,
            "loaded_from_cache": False,
        }

    return downloader


def test_parse_archive_inventory_supports_monthly_and_daily():
    html = """
    <a href="BTCUSDT-2022-12.csv.gz">monthly</a>
    <a href="BTCUSDT_2023-01-01.csv.gz">daily</a>
    <a href="ignored.txt">ignored</a>
    """
    result = backfill.parse_archive_inventory("BTCUSDT", html)
    assert result.monthly == {"2022-12": "BTCUSDT-2022-12.csv.gz"}
    assert result.daily == {"2023-01-01": "BTCUSDT_2023-01-01.csv.gz"}


def test_plan_prefers_monthly_for_full_month_and_daily_for_partial_month():
    inventories = {
        symbol: inventory(symbol)
        for symbol in ("BTCUSDT", "ETHUSDT")
    }
    plan = backfill.build_archive_plan(
        inventories,
        "2022-11-10",
        "2022-12-31",
    )
    assert plan["daily_units"] == 21
    assert plan["monthly_units"] == 1
    assert plan["total_archives"] == 44
    assert plan["units"][0]["unit_id"] == "daily:2022-11-10"
    assert plan["units"][-1]["unit_id"] == "monthly:2022-12"
    assert plan["unavailable_dates"] == []


def test_plan_reports_dates_missing_from_one_symbol():
    btc = inventory("BTCUSDT")
    eth = inventory("ETHUSDT")
    del eth.daily["2022-11-15"]
    plan = backfill.build_archive_plan(
        {"BTCUSDT": btc, "ETHUSDT": eth},
        "2022-11-14",
        "2022-11-16",
    )
    assert plan["unavailable_dates"] == ["2022-11-15"]
    assert [unit["unit_id"] for unit in plan["units"]] == [
        "daily:2022-11-14",
        "daily:2022-11-16",
    ]


def test_validate_trade_range_rejects_duplicate_trade_ids():
    frame = pd.DataFrame(
        {
            "timestamp": pd.to_datetime(
                ["2022-12-01T00:00:00Z", "2022-12-01T00:15:00Z"]
            ),
            "symbol": ["BTCUSDT", "BTCUSDT"],
            "side": ["Buy", "Sell"],
            "size": [1.0, 1.0],
            "price": [100.0, 101.0],
            "trade_id": ["same", "same"],
        }
    )
    with pytest.raises(backfill.BybitBackfillError, match="validation failed"):
        backfill.validate_trade_range(
            frame,
            "BTCUSDT",
            "2022-12-01",
            "2022-12-31",
        )


def test_merge_without_overlap_rejects_duplicate_candle_time():
    existing = pd.DataFrame(
        {"timestamp": pd.to_datetime(["2022-12-01T00:00:00Z"])}
    )
    incoming = existing.copy()
    with pytest.raises(backfill.BybitBackfillError, match="overlaps"):
        backfill.merge_without_overlap(existing, incoming)


def test_one_month_backfill_writes_checkpoint_and_six_parquets(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    for symbol in ("BTCUSDT", "ETHUSDT"):
        write_month_archive(source / f"{symbol}-2022-12.csv.gz", "2022-12")

    state = tmp_path / "state"
    result = backfill.run_backfill(
        start_date="2022-12-01",
        end_date="2022-12-31",
        state_root=state,
        cache_root=tmp_path / "cache",
        max_archives_per_run=2,
        inventory_fetcher=lambda symbol: inventory(symbol),
        downloader=make_downloader(source),
        clean=True,
    )
    assert result["summary"]["backfill_complete"] is True
    assert result["summary"]["current_dataset_integrity_ok"] is True
    assert result["summary"]["archives_completed_this_run"] == 2
    assert len(list((state / "bybit_market").glob("*/*.parquet"))) == 6
    checkpoint = backfill.load_checkpoint(state)
    assert [unit["unit_id"] for unit in checkpoint["completed_units"]] == [
        "monthly:2022-12"
    ]


def test_second_run_resumes_without_reprocessing_completed_month(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    for symbol in ("BTCUSDT", "ETHUSDT"):
        for period in ("2022-12", "2023-01"):
            write_month_archive(source / f"{symbol}-{period}.csv.gz", period)

    state = tmp_path / "state"
    kwargs = {
        "start_date": "2022-12-01",
        "end_date": "2023-01-31",
        "state_root": state,
        "cache_root": tmp_path / "cache",
        "max_archives_per_run": 2,
        "inventory_fetcher": lambda symbol: inventory(symbol),
        "downloader": make_downloader(source),
    }
    first = backfill.run_backfill(**kwargs, clean=True)
    second = backfill.run_backfill(**kwargs, clean=False)
    assert first["summary"]["completed_units"] == 1
    assert second["summary"]["completed_units"] == 2
    assert second["summary"]["backfill_complete"] is True
    checkpoint = backfill.load_checkpoint(state)
    assert [unit["unit_id"] for unit in checkpoint["completed_units"]] == [
        "monthly:2022-12",
        "monthly:2023-01",
    ]
    btc_15 = pd.read_parquet(state / "bybit_market/btc_usdt/minute15.parquet")
    assert len(btc_15) == (31 + 31) * 96


def test_atomic_unit_failure_does_not_write_partial_dataset(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    write_month_archive(source / "BTCUSDT-2022-12.csv.gz", "2022-12")

    def downloader(symbol, filename, cache_root):
        if symbol == "ETHUSDT":
            raise RuntimeError("source unavailable")
        return make_downloader(source)(symbol, filename, cache_root)

    state = tmp_path / "state"
    result = backfill.run_backfill(
        start_date="2022-12-01",
        end_date="2022-12-31",
        state_root=state,
        cache_root=tmp_path / "cache",
        max_archives_per_run=2,
        inventory_fetcher=lambda symbol: inventory(symbol),
        downloader=downloader,
        clean=True,
    )
    assert result["summary"]["run_failures"] == 1
    assert result["summary"]["completed_units"] == 0
    assert list((state / "bybit_market").glob("*/*.parquet")) == []


def test_archive_budget_must_cover_both_symbols(tmp_path):
    with pytest.raises(backfill.BybitBackfillError, match="at least 2"):
        backfill.run_backfill(
            start_date="2022-12-01",
            end_date="2022-12-31",
            state_root=tmp_path / "state",
            cache_root=tmp_path / "cache",
            max_archives_per_run=1,
            inventory_fetcher=lambda symbol: inventory(symbol),
            downloader=lambda *args: {},
            clean=True,
        )
