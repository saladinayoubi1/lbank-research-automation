from __future__ import annotations

import hashlib
from pathlib import Path

import pandas as pd

import bybit_spot_archive_audit as archive_audit
import nexus_multipair_bybit_archive_probe as probe
from nexus_multipair_trusted_surface import SYMBOLS, TIMEFRAMES


def _write_archive(path: Path, audit_date: str) -> None:
    timestamps = pd.date_range(
        pd.Timestamp(audit_date, tz="UTC"),
        periods=24 * 60,
        freq="1min",
    )
    frame = pd.DataFrame(
        {
            "id": [str(index + 1) for index in range(len(timestamps))],
            "timestamp": timestamps.astype("int64") // 1_000_000,
            "price": 100.0 + pd.Series(range(len(timestamps))) / 1000.0,
            "volume": 1.0,
            "side": ["buy", "sell"] * (len(timestamps) // 2),
            "rpi": 0,
        }
    )
    frame.to_csv(path, index=False, compression="gzip")


def _source(tmp_path: Path, audit_date: str):
    root = tmp_path / "source"
    root.mkdir()
    records = {}
    for symbol in SYMBOLS:
        path = root / archive_audit.archive_filename(symbol, audit_date)
        _write_archive(path, audit_date)
        records[symbol] = path
    return records


def _downloader(records):
    def download(symbol, audit_date, cache_root):
        path = records[symbol]
        content = path.read_bytes()
        return {
            "symbol": symbol,
            "audit_date": audit_date,
            "url": archive_audit.archive_url(symbol, audit_date),
            "path": path.as_posix(),
            "size_bytes": len(content),
            "sha256": hashlib.sha256(content).hexdigest(),
            "http_status": 200,
            "download_attempts": 1,
            "loaded_from_cache": False,
        }

    return download


def test_probe_uses_trusted_four_symbol_surface_and_passes_12_cells(tmp_path):
    assert tuple(SYMBOLS) == ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT")
    assert tuple(TIMEFRAMES) == ("minute15", "hour1", "hour4")
    records = _source(tmp_path, probe.DEFAULT_AUDIT_DATE)

    result = probe.build_probe(
        audit_date=probe.DEFAULT_AUDIT_DATE,
        cache_root=tmp_path / "cache",
        downloader=_downloader(records),
    )

    assert result["decision"] == "pass"
    assert result["archives_passed"] == 4
    assert result["series_passed"] == 12
    assert result["symbols"] == list(SYMBOLS)
    assert result["timeframes"] == list(TIMEFRAMES)
    assert {(row["symbol"], row["timeframe"]) for row in result["series"]} == {
        (symbol, timeframe) for symbol in SYMBOLS for timeframe in TIMEFRAMES
    }
    assert all(
        row["url"].startswith("https://public.bybit.com/spot/")
        and row["url"] == archive_audit.archive_url(row["symbol"], probe.DEFAULT_AUDIT_DATE)
        and len(row["sha256"]) == 64
        for row in result["archives"]
    )
    assert probe.verify_probe(result)["decision"] == "pass"


def test_probe_fails_closed_when_one_official_archive_is_missing(tmp_path):
    records = _source(tmp_path, probe.DEFAULT_AUDIT_DATE)

    def downloader(symbol, audit_date, cache_root):
        if symbol == "XRPUSDT":
            raise RuntimeError("missing")
        return _downloader(records)(symbol, audit_date, cache_root)

    result = probe.build_probe(
        audit_date=probe.DEFAULT_AUDIT_DATE,
        cache_root=tmp_path / "cache",
        downloader=downloader,
    )

    assert result["decision"] == "reject"
    assert result["archives_passed"] == 3
    assert len(result["errors"]) == 1
    assert result["errors"][0]["symbol"] == "XRPUSDT"
    assert probe.verify_probe(result)["decision"] == "reject"


def test_probe_verifier_rejects_source_substitution_and_digest_tamper(tmp_path):
    records = _source(tmp_path, probe.DEFAULT_AUDIT_DATE)
    result = probe.build_probe(
        audit_date=probe.DEFAULT_AUDIT_DATE,
        cache_root=tmp_path / "cache",
        downloader=_downloader(records),
    )

    substituted = dict(result)
    substituted["archives"] = [dict(row) for row in result["archives"]]
    substituted["archives"][0]["url"] = "https://example.com/substitute.csv.gz"
    assert probe.verify_probe(substituted)["decision"] == "reject"

    tampered = dict(result)
    tampered["series_passed"] = 11
    assert probe.verify_probe(tampered)["decision"] == "reject"


def test_probe_authority_is_research_only(tmp_path):
    records = _source(tmp_path, probe.DEFAULT_AUDIT_DATE)
    result = probe.build_probe(
        audit_date=probe.DEFAULT_AUDIT_DATE,
        cache_root=tmp_path / "cache",
        downloader=_downloader(records),
    )

    assert result["research_only"] is True
    assert result["paper_execution_started"] is False
    assert result["live_trading_authority"] is False
    assert result["private_credentials_used"] is False
    assert result["real_exchange_orders"] is False
    assert result["automatic_strategy_promotion"] is False
    assert result["silent_exchange_substitution"] is False
    assert result["third_party_proxy_used"] is False
    assert result["issue_984_state_touched"] is False
