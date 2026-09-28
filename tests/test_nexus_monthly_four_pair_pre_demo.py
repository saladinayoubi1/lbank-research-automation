"""Offline regression for the 31-day, 36-cell no-Demo official archive contract."""
from __future__ import annotations

import json

import pandas as pd
import pytest

import bybit_spot_archive_collector as collector
import bybit_spot_backfill as backfill
import nexus_monthly_four_pair_pre_demo as monthly
from nexus_multipair_trusted_surface import SYMBOLS, TIMEFRAMES


SOURCE = "f" * 40


def _frames():
    frames = {}
    periods = monthly.EXPECTED_ROWS
    frequencies = {"minute15": "15min", "hour1": "1h", "hour4": "4h"}
    for timeframe in TIMEFRAMES:
        timestamps = pd.date_range(monthly.START_DATE, periods=periods[timeframe],
                                   freq=frequencies[timeframe], tz="UTC")
        for number, symbol in enumerate(SYMBOLS):
            base = 100.0 + number * 10
            vals = [base + (i % 29) / 10 + i / 10000 for i in range(len(timestamps))]
            frames[(symbol, timeframe)] = pd.DataFrame({
                "timestamp": timestamps, "open": vals, "high": [x + 1 for x in vals],
                "low": [x - 1 for x in vals], "close": [x + 0.1 for x in vals],
                "volume": [10.0] * len(timestamps),
                "symbol": [collector.canonical_symbol(symbol)] * len(timestamps),
                "timeframe": [timeframe] * len(timestamps),
            })
    return frames


def _official_sources():
    out = []
    for symbol in SYMBOLS:
        filename = f"{symbol}-{monthly.MONTH}.csv.gz"
        out.append({
            "symbol": symbol, "unit_id": f"monthly:{monthly.MONTH}",
            "unit_kind": "monthly", "filename": filename,
            "url": backfill.archive_url(symbol, filename),
            "start_date": monthly.START_DATE, "end_date": monthly.END_DATE,
            "sha256": "a" * 64, "size_bytes": 1_000_000,
            "http_status": 200, "source_rows": 100,
            "valid_trade_rows": 100,
            "invalid_numeric_rows": 0, "invalid_symbol_rows": 0,
            "invalid_side_rows": 0, "non_positive_price_rows": 0,
            "negative_size_rows": 0, "outside_range_rows": 0,
            "duplicate_trade_id_count": 0, "source_rows_skipped": 0,
            "malformed_csv_rows": 0,
        })
    return out


def _report():
    return {
        "configuration": {"start_date": monthly.START_DATE,
                          "end_date": monthly.END_DATE, "symbols": list(SYMBOLS)},
        "summary": {"plan_units": 1, "plan_archives": len(SYMBOLS),
                    "completed_units": 1, "remaining_units": 0,
                    "run_failures": 0, "backfill_complete": True,
                    "current_dataset_integrity_ok": True},
    }


def test_full_month_four_pair_twelve_series_36_research_cells_no_demo():
    output = monthly.calculate(_frames(), source_sha=SOURCE)
    rows = output["rows"]
    assert len(rows) == 36
    assert {v["symbol"] for v in rows} == set(SYMBOLS)
    assert {v["timeframe"] for v in rows} == set(TIMEFRAMES)
    assert {v["family"] for v in rows} == {"momentum", "trend_breakout", "mean_reversion"}
    assert all(v["monthly_coverage"] for v in rows)
    assert all(v["bars"] == monthly.EXPECTED_ROWS[v["timeframe"]] for v in rows)
    assert all(v["qualification"] == "RESEARCH_ONLY_REQUIRES_INDEPENDENT_REQUALIFICATION"
               for v in rows)
    assert all(not v["demo_promoted"] and not v["live_enabled"] for v in rows)
    assert output["automatic_paper_promotion"] is False


def test_shortened_month_cannot_be_reported_as_full_month():
    frames = _frames()
    frames[(SYMBOLS[0], TIMEFRAMES[0])] = frames[(SYMBOLS[0], TIMEFRAMES[0])].iloc[1:]
    with pytest.raises(monthly.MonthlyResearchError, match="monthly coverage"):
        monthly.calculate(frames, source_sha=SOURCE)


def test_exact_four_public_monthly_sources_verified_and_tamper_rejected(tmp_path):
    path = tmp_path / backfill.SOURCE_MANIFEST_NAME
    sources = _official_sources()
    path.write_text(json.dumps(sources), encoding="utf-8")
    assert len(monthly._verify_sources(tmp_path, _report())) == 4
    sources[0]["url"] = "https://not-bybit.example.invalid/fake"
    path.write_text(json.dumps(sources), encoding="utf-8")
    with pytest.raises(monthly.MonthlyResearchError):
        monthly._verify_sources(tmp_path, _report())
    sources = _official_sources()
    sources[1]["malformed_csv_rows"] = 1
    path.write_text(json.dumps(sources), encoding="utf-8")
    with pytest.raises(monthly.MonthlyResearchError):
        monthly._verify_sources(tmp_path, _report())


def test_full_utc_cadence_and_cross_pair_integrity(tmp_path):
    frames = _frames()
    for (symbol, timeframe), frame in frames.items():
        path = tmp_path / "bybit_market" / collector.canonical_symbol(symbol) / f"{timeframe}.parquet"
        path.parent.mkdir(parents=True, exist_ok=True)
        frame.to_parquet(path, index=False)
    assert len(monthly._load_full_month(tmp_path)) == 12
    first = tmp_path / "bybit_market" / collector.canonical_symbol(SYMBOLS[0]) / f"{TIMEFRAMES[0]}.parquet"
    tampered = pd.read_parquet(first)
    tampered.loc[100, "timestamp"] = tampered.loc[99, "timestamp"]
    tampered.to_parquet(first, index=False)
    with pytest.raises(monthly.MonthlyResearchError):
        monthly._load_full_month(tmp_path)


def test_reuse_verified_three_month_official_state_without_redownload(tmp_path, monkeypatch):
    """Contract: policy-approved historical job already fetched 12 exact archives."""
    import nexus_multipair_archive_snapshot as archive

    state = tmp_path / "verified-state"
    state.mkdir()
    report = {
        "configuration": {"start_date": archive.SOURCE_START_DATE,
                          "end_date": archive.SOURCE_END_DATE, "symbols": list(SYMBOLS)},
        "summary": {"plan_units": 3, "plan_archives": 12,
                    "completed_units": 3, "remaining_units": 0,
                    "run_failures": 0, "backfill_complete": True,
                    "current_dataset_integrity_ok": True},
        "run_failures": [],
    }
    (state / backfill.REPORT_NAME).write_text(json.dumps(report), encoding="utf-8")
    sources = []
    for month in archive.SOURCE_MONTHS:
        begin, end = archive._month_bounds(month)
        for symbol in SYMBOLS:
            filename = f"{symbol}-{month}.csv.gz"
            record = _official_sources()[0].copy()
            record.update({
                "symbol": symbol, "unit_id": f"monthly:{month}",
                "filename": filename, "url": backfill.archive_url(symbol, filename),
                "start_date": begin, "end_date": end,
            })
            sources.append(record)
    (state / backfill.SOURCE_MANIFEST_NAME).write_text(
        json.dumps(sources), encoding="utf-8"
    )
    # The standard snapshot engine stores full state while exporting its
    # separate 500-row discovery tail. The monthly job consumes full state.
    frames = _frames()
    for (symbol, timeframe), frame in frames.items():
        target = state / "bybit_market" / collector.canonical_symbol(symbol) / f"{timeframe}.parquet"
        target.parent.mkdir(parents=True, exist_ok=True)
        frame.to_parquet(target, index=False)
    result = monthly.run_verified_three_month_backfill(
        source_sha=SOURCE, state=state, output=tmp_path / "month-results"
    )
    assert len(result["rows"]) == 36
    assert len(result["archive_sources"]) == 4
    assert len(result["verified_three_month_source_manifest_sha256"]) == 64
    assert all(not row["demo_promoted"] for row in result["rows"])
    assert (tmp_path / "month-results" / "monthly-table.csv").is_file()
    sources[0]["url"] = "https://not-bybit.invalid/fake.csv.gz"
    (state / backfill.SOURCE_MANIFEST_NAME).write_text(json.dumps(sources), encoding="utf-8")
    with pytest.raises(archive.MultiPairArchiveSnapshotError):
        monthly.run_verified_three_month_backfill(
            source_sha=SOURCE, state=state, output=tmp_path / "unsafe-report"
        )


@pytest.mark.parametrize(
    ("column", "value", "failure_name"),
    [
        ("high", -1.0, "high_envelope"),
        ("low", 10000000.0, "low_envelope"),
        ("volume", -1.0, "nonnegative_volume"),
        ("symbol", "btc_wrong", "canonical_symbol"),
        ("timeframe", "hour1", "timeframe_identity"),
    ],
)
def test_full_month_rejection_names_without_exposing_raw_data(tmp_path, column, value, failure_name):
    """Identifies exact original fail-closed guard on real parquet-format fixtures."""
    frames = _frames()
    key = (SYMBOLS[0], TIMEFRAMES[0])
    frames[key].loc[100, column] = value
    for (symbol, timeframe), frame in frames.items():
        path = tmp_path / "bybit_market" / collector.canonical_symbol(symbol) / f"{timeframe}.parquet"
        path.parent.mkdir(parents=True, exist_ok=True)
        frame.to_parquet(path, index=False)
    with pytest.raises(monthly.MonthlyResearchError, match=f"violated=.*{failure_name}") as err:
        monthly._load_full_month(tmp_path)
    assert "BTCUSDT/minute15" in str(err.value)
    assert "10000000" not in str(err.value)
