from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any, Mapping

from phase5_data_binding import CanonicalDataError, validate_canonical_dataset
from product_research_runtime import ProductResearchError, ProductResearchRuntime, TIMEFRAMES
from product_runtime import ProductRuntime

OFFLINE_CONTRACT = "nexus.product-offline.v1"
MAX_OFFLINE_DATASET_BYTES = 2_000_000
MAX_OFFLINE_DATASETS = 24
_BINDING_RE = re.compile(r"^[0-9a-f]{64}$")


class ProductOfflineError(RuntimeError):
    pass


def _registry_path() -> Path:
    from phase5_data_binding import REGISTRY_PATH
    return Path(os.environ.get("NEXUS_MARKET_REGISTRY_PATH", str(REGISTRY_PATH)))


def _canonical_bytes(value: Mapping[str, Any]) -> bytes:
    try:
        raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ProductOfflineError("offline dataset is not canonical JSON") from exc
    if len(raw) > MAX_OFFLINE_DATASET_BYTES:
        raise ProductOfflineError("offline dataset exceeds bounded import size")
    return raw


def _dataset_summary(dataset: Mapping[str, Any]) -> dict[str, Any]:
    rows = dataset["rows"]
    return {
        "binding_sha256": dataset["binding_sha256"],
        "manifest_sha256": dataset["manifest_sha256"],
        "instrument": dataset["instrument"],
        "source": dataset["source"],
        "source_symbol": dataset["source_symbol"],
        "timeframe": dataset["manifest_timeframe"],
        "row_count": dataset["row_count"],
        "first_open_time_ms": rows[0]["open_time_ms"],
        "last_open_time_ms": rows[-1]["open_time_ms"],
        "paper_only": True,
    }


class OfflineDatasetStore:
    """Durable, bounded store for provenance-bound canonical datasets imported from local media."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        if self.root.is_symlink():
            raise ProductOfflineError("offline dataset root must not be a symlink")

    def _path(self, binding_sha256: str) -> Path:
        candidate = str(binding_sha256).strip().lower()
        if not _BINDING_RE.fullmatch(candidate):
            raise ProductOfflineError("invalid offline dataset binding")
        return self.root / f"{candidate}.json"

    def import_dataset(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, Mapping):
            raise ProductOfflineError("offline import requires one canonical dataset object")
        try:
            dataset = validate_canonical_dataset(payload, registry_path=_registry_path())
        except (CanonicalDataError, OSError, ValueError) as exc:
            raise ProductOfflineError(f"offline canonical dataset rejected: {exc}") from exc
        if dataset.get("source") != "Bybit" or dataset.get("source_role") != "primary":
            raise ProductOfflineError("offline dataset is not canonical Bybit primary data")
        row_count = dataset.get("row_count")
        if isinstance(row_count, bool) or not isinstance(row_count, int) or not 60 <= row_count <= 500:
            raise ProductOfflineError("offline dataset must contain 60..500 canonical closed candles")
        raw = _canonical_bytes(dataset)
        target = self._path(dataset["binding_sha256"])
        if target.exists():
            if target.is_symlink() or not target.is_file() or target.stat().st_size > MAX_OFFLINE_DATASET_BYTES:
                raise ProductOfflineError("existing offline dataset artifact is unsafe")
            if target.read_bytes() != raw:
                raise ProductOfflineError("existing offline dataset binding has conflicting bytes")
            return {"contract_version": OFFLINE_CONTRACT, "status": "already_present", "dataset": _dataset_summary(dataset)}
        existing = [path for path in self.root.glob("*.json") if path.is_file() and not path.is_symlink()]
        if len(existing) >= MAX_OFFLINE_DATASETS:
            raise ProductOfflineError("offline dataset retention bound reached")
        fd, tmp_name = tempfile.mkstemp(prefix=".nexus-offline-", suffix=".tmp", dir=self.root)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(raw)
                handle.flush()
                os.fsync(handle.fileno())
            Path(tmp_name).replace(target)
        finally:
            try: Path(tmp_name).unlink(missing_ok=True)
            except OSError: pass
        return {"contract_version": OFFLINE_CONTRACT, "status": "imported", "dataset": _dataset_summary(dataset)}

    def load(self, binding_sha256: str) -> dict[str, Any]:
        target = self._path(binding_sha256)
        if not target.exists() or target.is_symlink() or not target.is_file():
            raise ProductOfflineError("offline dataset not found")
        if target.stat().st_size <= 2 or target.stat().st_size > MAX_OFFLINE_DATASET_BYTES:
            raise ProductOfflineError("offline dataset artifact size is invalid")
        try:
            payload = json.loads(target.read_text(encoding="utf-8"))
            dataset = validate_canonical_dataset(payload, registry_path=_registry_path())
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, CanonicalDataError, ValueError) as exc:
            raise ProductOfflineError(f"stored offline dataset failed validation: {exc}") from exc
        if dataset["binding_sha256"] != binding_sha256.lower():
            raise ProductOfflineError("offline dataset filename/binding mismatch")
        return dataset

    def snapshot(self) -> dict[str, Any]:
        datasets: list[dict[str, Any]] = []
        for path in sorted(self.root.glob("*.json")):
            if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_OFFLINE_DATASET_BYTES:
                continue
            binding = path.stem
            if not _BINDING_RE.fullmatch(binding):
                continue
            try: datasets.append(_dataset_summary(self.load(binding)))
            except ProductOfflineError: continue
        return {
            "contract_version": OFFLINE_CONTRACT,
            "mode": "offline_first",
            "internet_required_for_startup": False,
            "internet_required_for_imported_research": False,
            "internet_required_for_live_refresh": True,
            "paper_only": True,
            "live_trading_authority": False,
            "dataset_count": len(datasets),
            "datasets": datasets,
        }


class OfflineProductResearchRuntime(ProductResearchRuntime):
    """Runs the canonical research pipeline from a locally imported dataset without network I/O."""

    def __init__(self, product_runtime: ProductRuntime, store: OfflineDatasetStore, *, source_sha: str | None = None) -> None:
        super().__init__(product_runtime, source_sha=source_sha)
        self.store = store
        self._selected_binding: str | None = None

    def fetch_dataset(self, *, symbol: str, timeframe: str, limit: int = 240) -> dict[str, Any]:
        if self._selected_binding is None:
            raise ProductResearchError("select an imported canonical dataset before offline research")
        dataset = self.store.load(self._selected_binding)
        spec = TIMEFRAMES.get(timeframe)
        if spec is None:
            raise ProductResearchError("unsupported product timeframe")
        if dataset["source_symbol"] != str(symbol).upper().strip() or dataset["manifest_timeframe"] != spec["manifest"]:
            raise ProductResearchError("offline dataset does not match requested canonical symbol/timeframe")
        if dataset["row_count"] != limit:
            raise ProductResearchError("offline research must use the complete bound dataset; partial slicing is denied")
        return dataset

    def run_imported_research(self, *, binding_sha256: str, family: str) -> dict[str, Any]:
        dataset = self.store.load(binding_sha256)
        reverse_timeframes = {spec["manifest"]: name for name, spec in TIMEFRAMES.items()}
        timeframe = reverse_timeframes.get(dataset["manifest_timeframe"])
        if timeframe is None:
            raise ProductResearchError("offline dataset timeframe is unsupported by product research")
        self._selected_binding = dataset["binding_sha256"]
        result = self.run_research(
            symbol=dataset["source_symbol"],
            timeframe=timeframe,
            family=family,
            limit=dataset["row_count"],
        )
        return {**result, "data_mode": "offline_import", "internet_used": False, "historical_research_allowed": True}
