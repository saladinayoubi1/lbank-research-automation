from __future__ import annotations

import json
from copy import deepcopy

import pytest
import yaml

from backtest_engine import BacktestConfig
from canonical_backtest import CanonicalBacktestError, run_canonical_target_exposure_backtest
from phase5_data_binding import REGISTRY_PATH
from phase6_research_pipeline import bind_bybit_closed_dataset

START_15M = 1_700_000_100_000


def _candles(*, interval: str = "15", count: int = 60):
    step = 900_000 if interval == "15" else 3_600_000
    start = START_15M if interval == "15" else (START_15M // step) * step
    rows = []
    for index in range(count):
        price = 100 + index * 0.25
        rows.append({
            "source": "Bybit",
            "market_type": "spot",
            "symbol": "BTCUSDT",
            "interval": interval,
            "open_time_ms": start + index * step,
            "close_time_ms": start + (index + 1) * step - 1,
            "open": f"{price:.8f}",
            "high": f"{price * 1.01:.8f}",
            "low": f"{price * 0.99:.8f}",
            "close": f"{price:.8f}",
            "volume": "10",
            "turnover": f"{price * 10:.8f}",
            "closed": True,
        })
    return rows


def _dataset(interval: str = "15"):
    return bind_bybit_closed_dataset(
        _candles(interval=interval),
        canonical_symbol="BTC/USDT",
        source_symbol="BTCUSDT",
        interval=interval,
    )


def _run(dataset):
    return run_canonical_target_exposure_backtest(
        dataset,
        [1.0] * dataset["row_count"],
        BacktestConfig(initial_cash=10_000.0, fee_bps=10.0, slippage_bps=5.0),
    )


@pytest.mark.parametrize("interval,manifest", [("15", "15m"), ("60", "1h")])
def test_exact_policy_target_tuples_cross_authoritative_backtest_boundary(interval, manifest):
    dataset = _dataset(interval)
    assert dataset["source"] == "Bybit"
    assert dataset["source_role"] == "primary"
    assert dataset["manifest_timeframe"] == manifest
    result = _run(dataset)
    assert result.metrics["fill_count"] >= 1


@pytest.mark.parametrize(
    "field,value",
    [
        ("source", "Binance"),
        ("source_role", "secondary_validation"),
        ("candidate_timeframe", "hourly"),
        ("manifest_timeframe", "1h"),
        ("category", "linear"),
        ("endpoint_contract", "/v5/market/kline?category=linear&symbol=BTCUSDT&interval=15"),
        ("mapping_policy_version", "0.9.0"),
        ("finality", "open_allowed"),
        ("binding_sha256", "0" * 64),
    ],
)
def test_semantic_or_binding_tamper_is_blocked_before_backtest(field, value):
    dataset = _dataset()
    dataset[field] = value
    with pytest.raises(CanonicalBacktestError):
        _run(dataset)


def test_primary_source_status_change_blocks_authoritative_backtest(tmp_path):
    payload = yaml.safe_load(REGISTRY_PATH.read_text(encoding="utf-8"))
    target = next(
        mapping for mapping in payload["mappings"]
        if mapping["canonical_symbol"] == "BTC/USDT" and mapping["timeframe"] == "minute15"
    )
    bybit = next(source for source in target["sources"] if source["exchange"] == "Bybit")
    bybit["status"] = "incompatible"
    registry = tmp_path / "registry.yaml"
    registry.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    dataset = _dataset()
    with pytest.raises(CanonicalBacktestError):
        run_canonical_target_exposure_backtest(
            dataset,
            [1.0] * dataset["row_count"],
            registry_path=registry,
        )


def test_row_payload_or_manifest_tamper_is_blocked_before_backtest():
    dataset = _dataset()
    dataset["rows"][0]["close"] = "1"
    with pytest.raises(CanonicalBacktestError):
        _run(dataset)

    dataset = _dataset()
    dataset["manifest"]["source"] = "Binance"
    with pytest.raises(CanonicalBacktestError):
        _run(dataset)


def test_incomplete_raw_rows_cannot_impersonate_canonical_artifact():
    raw = {"rows": _dataset()["rows"], "downstream_eligible": True, "paper_only": True}
    with pytest.raises(CanonicalBacktestError):
        run_canonical_target_exposure_backtest(raw, [1.0] * len(raw["rows"]))


def test_invalid_provenance_survives_persistence_recovery_and_stays_blocked():
    invalid = _dataset()
    invalid["endpoint_contract"] = "/v5/market/kline?category=linear&symbol=BTCUSDT&interval=15"
    persisted = json.dumps(invalid, sort_keys=True, separators=(",", ":"))
    recovered = json.loads(persisted)
    assert recovered["endpoint_contract"] == invalid["endpoint_contract"]
    assert recovered["binding_sha256"] == invalid["binding_sha256"]
    with pytest.raises(CanonicalBacktestError):
        _run(recovered)


def test_slice_backtests_cannot_detach_from_full_canonical_binding():
    dataset = _dataset()
    targets = [1.0] * dataset["row_count"]
    result = run_canonical_target_exposure_backtest(dataset, targets, start=40, end=60)
    assert result.metrics["fill_count"] >= 1

    tampered = deepcopy(dataset)
    tampered["rows"][0]["close"] = "999"
    with pytest.raises(CanonicalBacktestError):
        run_canonical_target_exposure_backtest(tampered, targets, start=40, end=60)
