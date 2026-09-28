from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from phase6_research_pipeline import bind_bybit_closed_dataset
from product_offline_runtime import (
    CachingProductResearchRuntime,
    OfflineDatasetStore,
    OfflineProductResearchRuntime,
    ProductOfflineError,
)
from product_research_runtime import ProductResearchError
from product_runtime import ProductRuntime

STEP = 900_000


def _candles(now_ms: int, count: int = 120):
    end_open = ((now_ms - STEP) // STEP) * STEP
    start = end_open - (count - 1) * STEP
    rows = []
    for index in range(count):
        price = 90.0 + index * 0.2 + (2.0 if index % 9 == 0 else 0.0)
        rows.append({
            "source": "Bybit", "market_type": "spot", "symbol": "BTCUSDT", "interval": "15",
            "open_time_ms": start + index * STEP,
            "close_time_ms": start + (index + 1) * STEP - 1,
            "open": f"{price:.8f}", "high": f"{price * 1.01:.8f}", "low": f"{price * 0.99:.8f}",
            "close": f"{price:.8f}", "volume": "10", "turnover": f"{price * 10:.8f}", "closed": True,
        })
    return rows


def _dataset(now_ms: int, count: int = 120):
    return bind_bybit_closed_dataset(_candles(now_ms, count), canonical_symbol="BTC/USDT", source_symbol="BTCUSDT", interval="15")


def test_offline_store_accepts_only_bound_canonical_data_and_persists_by_digest(tmp_path: Path) -> None:
    store = OfflineDatasetStore(tmp_path / "offline")
    dataset = _dataset(int(time.time() * 1000))
    imported = store.import_dataset(dataset)
    assert imported["status"] == "imported"
    assert imported["dataset"]["binding_sha256"] == dataset["binding_sha256"]
    assert store.load(dataset["binding_sha256"])["binding_sha256"] == dataset["binding_sha256"]
    snapshot = store.snapshot()
    assert snapshot["mode"] == "offline_first"
    assert snapshot["internet_required_for_startup"] is False
    assert snapshot["internet_required_for_imported_research"] is False
    assert snapshot["internet_required_for_live_refresh"] is True
    assert snapshot["live_trading_authority"] is False
    assert snapshot["dataset_count"] == 1


def test_offline_store_rejects_tamper_and_never_uses_user_filename(tmp_path: Path) -> None:
    store = OfflineDatasetStore(tmp_path / "offline")
    dataset = _dataset(int(time.time() * 1000))
    tampered = json.loads(json.dumps(dataset))
    tampered["rows"][-1]["close"] = "999999"
    with pytest.raises(ProductOfflineError, match="rejected"):
        store.import_dataset(tampered)
    with pytest.raises(ProductOfflineError, match="invalid offline dataset binding"):
        store.load("../../escape")
    assert not list((tmp_path / "offline").glob("*.json"))


def test_historical_canonical_dataset_can_research_offline_but_not_auto_paper(tmp_path: Path) -> None:
    now = int(time.time() * 1000)
    historical = _dataset(now - 30 * STEP)
    store = OfflineDatasetStore(tmp_path / "offline")
    store.import_dataset(historical)
    runtime = ProductRuntime(tmp_path / "state")
    research = OfflineProductResearchRuntime(runtime, store, source_sha="a" * 40)
    result = research.run_imported_research(binding_sha256=historical["binding_sha256"], family="momentum")
    assert result["paper_only"] is True
    assert result["live_execution_allowed"] is False
    assert result["data_mode"] == "offline_import"
    assert result["internet_used"] is False
    assert result["dataset"]["binding_sha256"] == historical["binding_sha256"]
    with pytest.raises(ProductResearchError, match="stale canonical data"):
        research.auto_paper()


def test_successful_online_fetch_is_cached_for_future_offline_research(tmp_path: Path) -> None:
    now = int(time.time() * 1000)
    dataset = _dataset(now)
    store = OfflineDatasetStore(tmp_path / "offline")
    runtime = ProductRuntime(tmp_path / "state")
    research = CachingProductResearchRuntime(runtime, store, source_sha="b" * 40)
    research.dataset_fetcher = lambda **_: dataset
    fetched = research.fetch_dataset(symbol="BTCUSDT", timeframe="minute15", limit=120)
    assert fetched["binding_sha256"] == dataset["binding_sha256"]
    assert store.snapshot()["dataset_count"] == 1


def test_packaged_offline_qualification_uses_verified_registry_from_any_cwd(tmp_path: Path) -> None:
    """Exercise the real nested phase5 qualifier in a cold non-repo process.

    The installed Electron sidecar passes its absolute bundled registry through
    NEXUS_MARKET_REGISTRY_PATH. Direct phase5 callers must use that same file.
    """
    source_root = Path(__file__).resolve().parents[1]
    canonical_registry = (source_root / "docs/architecture/market-data-source-registry.yaml").resolve(strict=True)
    dataset = _dataset(int(time.time() * 1000) - 30 * STEP)
    fixture_path = tmp_path / "prevalidated-historical.json"
    fixture_path.write_text(json.dumps(dataset), encoding="utf-8")
    env = os.environ.copy()
    env["NEXUS_MARKET_REGISTRY_PATH"] = str(canonical_registry)
    env["PYTHONPATH"] = str(source_root) + os.pathsep + env.get("PYTHONPATH", "")
    child = r'''
import json
import os
from pathlib import Path
from phase5_data_binding import REGISTRY_PATH
from product_offline_runtime import OfflineDatasetStore, OfflineProductResearchRuntime
from product_research_runtime import ProductResearchError
from product_runtime import ProductRuntime

expected = Path(os.environ["NEXUS_MARKET_REGISTRY_PATH"])
assert expected.is_absolute()
assert REGISTRY_PATH == expected
dataset = json.loads(Path("prevalidated-historical.json").read_text(encoding="utf-8"))
store = OfflineDatasetStore(Path("offline-datasets"))
imported = store.import_dataset(dataset)
assert imported["status"] == "imported"
research = OfflineProductResearchRuntime(
    ProductRuntime(Path("product-state")),
    store, source_sha="a" * 40,
)
result = research.run_imported_research(
    binding_sha256=dataset["binding_sha256"], family="momentum",
)
assert result["data_mode"] == "offline_import"
assert result["internet_used"] is False
assert result["historical_research_allowed"] is True
assert result["live_execution_allowed"] is False
assert result["profitability_claim"] is False
try:
    research.auto_paper()
except ProductResearchError as exc:
    assert "stale canonical data" in str(exc)
else:
    raise AssertionError("Expired offline history was silently promoted to Paper")
print("PACKAGED_OFFLINE_RESEARCH_PASS")
'''
    result = subprocess.run(
        [sys.executable, "-c", child], cwd=tmp_path, env=env,
        capture_output=True, text=True, timeout=90, check=False,
    )
    assert result.returncode == 0, (result.stdout, result.stderr)
    assert "PACKAGED_OFFLINE_RESEARCH_PASS" in result.stdout


@pytest.mark.parametrize("registry_kind", ["missing", "symlink"])
def test_packaged_registry_override_fails_closed_if_missing_or_linked(
    tmp_path: Path, registry_kind: str
) -> None:
    source_root = Path(__file__).resolve().parents[1]
    canonical_registry = (source_root / "docs/architecture/market-data-source-registry.yaml").resolve(strict=True)
    candidate = tmp_path / "invalid-registry.yaml"
    if registry_kind == "symlink":
        try:
            candidate.symlink_to(canonical_registry)
        except (OSError, NotImplementedError):
            pytest.skip("runner cannot create symlinks")
    env = os.environ.copy()
    env["NEXUS_MARKET_REGISTRY_PATH"] = str(candidate)
    env["PYTHONPATH"] = str(source_root) + os.pathsep + env.get("PYTHONPATH", "")
    child = (
        "from phase5_data_binding import REGISTRY_PATH\n"
        "from market_data_source_validator import load_and_validate\n"
        "assert str(REGISTRY_PATH).endswith('invalid-registry.yaml')\n"
        "load_and_validate(REGISTRY_PATH)\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", child], cwd=tmp_path, env=env,
        capture_output=True, text=True, timeout=25, check=False,
    )
    assert result.returncode != 0, (result.stdout, result.stderr)
    assert "regular non-symlink file" in result.stderr
