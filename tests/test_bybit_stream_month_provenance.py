import gzip
import hashlib
import json
import shutil
from pathlib import Path

import pandas as pd
import pytest

import bybit_spot_backfill as backfill
import stream_bybit_symbol_month as stream
from scripts import combine_bybit_source_bound_month as combiner
from scripts import validate_bybit_month_csv_reference as reference


@pytest.fixture(scope="module")
def month(tmp_path_factory):
    root = tmp_path_factory.mktemp("stream-stable-model")
    archive = root / "official-schema-fixture.csv.gz"
    with gzip.open(archive, "wt") as handle:
        for i, at in enumerate(pd.date_range("2024-07-01", periods=31 * 96, freq="15min", tz="UTC")):
            for j in range(24 if i == 0 else 1):
                handle.write(f"{i}-{j},{int(at.timestamp()*1000)},{100+i%7+j},{0.01},Buy,0\n")
    sha = hashlib.sha256(archive.read_bytes()).hexdigest()
    source = {"symbol": "BTCUSDT", "filename": "BTCUSDT-2024-07.csv.gz", "path": str(archive),
              "sha256": sha, "url": "https://public.bybit.com/spot/BTCUSDT/BTCUSDT-2024-07.csv.gz"}
    mp = pytest.MonkeyPatch()
    mp.setattr(stream, "CHUNK_SIZE", 17)
    mp.setattr(backfill, "fetch_archive_inventory", lambda s: backfill.ArchiveInventory(s, {"2024-07": source["filename"]}, {}))
    mp.setattr(backfill, "download_archive_file", lambda *a, **k: dict(source))
    output = root / "BTCUSDT"
    stream.build_symbol_month("BTCUSDT", "2024-07-01", "2024-07-31", output, root / "cache")
    qa = reference.verify(output, archive)
    (output / "_independent_csv_qa.json").write_text(json.dumps(qa))
    mp.undo()
    return root, archive, output


def test_original_equal_timestamp_rows_survive_chunk_boundaries(month):
    _, _, output = month
    candle = pd.read_parquet(output / "bybit_market/btc_usdt/minute15.parquet").iloc[0]
    assert candle["open"] == 100 and candle["close"] == 123
    assert candle["high"] == 123 and candle["low"] == 100
    assert candle["volume"] == pytest.approx(0.24)


def test_independent_decimal_reference_and_resumable_model_receipt(month):
    _, archive, output = month
    qa = reference.verify(output, archive)
    assert qa["passed"] and qa["source_rows"] == 31 * 96 + 23
    assert qa["numeric_comparisons"] == (31 * 96 + 31 * 24 + 31 * 6) * 5
    backfill.validate_candle_model_state(output)
    model = json.loads((output / "_candle_model.json").read_text())
    assert model == stream.candle_model_receipt()


def test_independent_reference_rejects_tampered_close(month, tmp_path):
    _, archive, output = month
    copy = tmp_path / "tampered"
    shutil.copytree(output, copy)
    candle = copy / "bybit_market/btc_usdt/minute15.parquet"
    frame = pd.read_parquet(candle)
    frame.loc[0, "close"] = 122
    frame.to_parquet(candle, index=False)
    with pytest.raises(ValueError, match="independent OHLCV mismatch"):
        reference.verify(copy, archive)


def test_nonempty_output_is_rejected_before_any_network(month, monkeypatch):
    root, _, output = month
    monkeypatch.setattr(backfill, "fetch_archive_inventory", lambda *a: pytest.fail("network attempted"))
    with pytest.raises(stream.StreamMonthError, match="output must be new"):
        stream.build_symbol_month("BTCUSDT", "2024-07-01", "2024-07-31", output, root / "cache")


def test_combination_preserves_models_and_both_sources(month, tmp_path):
    _, _, btc = month
    parts = tmp_path / "parts"
    shutil.copytree(btc, parts / "part-BTC")
    eth = parts / "part-ETH"
    shutil.copytree(btc, eth)
    source = json.loads((eth / "_source_manifest.json").read_text())
    source[0]["symbol"] = "ETHUSDT"
    source[0]["filename"] = "ETHUSDT-2024-07.csv.gz"
    source[0]["url"] = "https://public.bybit.com/spot/ETHUSDT/ETHUSDT-2024-07.csv.gz"
    (eth / "_source_manifest.json").write_text(json.dumps(source))
    report = json.loads((eth / "_backfill_report.json").read_text())
    for item in report["statuses"]:
        item["symbol"] = "ETHUSDT"
    (eth / "_backfill_report.json").write_text(json.dumps(report))
    (eth / "bybit_market/btc_usdt").rename(eth / "bybit_market/eth_usdt")
    for path in (eth / "bybit_market/eth_usdt").glob("*.parquet"):
        frame = pd.read_parquet(path)
        frame["symbol"] = "eth_usdt"
        frame.to_parquet(path, index=False)
    qa = reference.verify(eth, month[1])
    (eth / "_independent_csv_qa.json").write_text(json.dumps(qa))
    output = tmp_path / "combined"
    combiner.combine(parts, "part-*", output, "2024-07-01", "2024-07-31")
    backfill.validate_candle_model_state(output)
    assert len(list((output / "bybit_market").glob("*/*.parquet"))) == 6
    assert len(json.loads((output / "_source_manifest.json").read_text())) == 2
    (eth / "_candle_model.json").unlink()
    with pytest.raises(FileNotFoundError):
        combiner.combine(parts, "part-*", tmp_path / "legacy-rejected", "2024-07-01", "2024-07-31")
    assert not (tmp_path / "legacy-rejected").exists()
