"""Provider-labelled Bitget data; no Bybit substitution or execution authority."""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from decimal import Decimal
from datetime import datetime
from pathlib import Path

from bitget_isolated_demo_adapter import (
    BitgetDemoAdapterError, parse_closed_bars, parse_instrument,
    normalized_demo_price, normalized_demo_quantity, parse_risk_tiers, parse_funding_points,
)
from product_research_reports import ResearchReportError, canonical_bytes, safe_json

SYMBOLS = ("BTCUSDT", "ETHUSDT")
STEPS = {"15m": 900_000, "1h": 3_600_000, "4h": 14_400_000}
GRANULARITY = {"15m": "15min", "1h": "1h", "4h": "4h"}
HOST = "https://api.bitget.com"
SPOT_PATH = "/api/v2/spot/market/history-candles"
CONTRACT = "nexus.bitget-public-data.v1"


class AlternativeMarketError(ValueError):
    pass


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise AlternativeMarketError("public_redirect_rejected")


def public_json(url: str) -> dict:
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != "https" or parsed.netloc != "api.bitget.com" or parsed.path != SPOT_PATH:
        raise AlternativeMarketError("public_endpoint_rejected")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())
    request = urllib.request.Request(url, headers={"Accept": "application/json",
                                                  "User-Agent": "NEXUS-public-backup/1"})
    try:
        with opener.open(request, timeout=6) as response:
            if response.status != 200:
                raise AlternativeMarketError("public_http_failure")
            raw = response.read(1_000_001)
        if len(raw) > 1_000_000:
            raise AlternativeMarketError("public_response_oversized")
        value = json.loads(raw)
    except urllib.error.HTTPError as exc:
        raise AlternativeMarketError(f"public_http_{exc.code}") from exc
    except (OSError, ValueError) as exc:
        raise AlternativeMarketError("public_transport_or_json_failure") from exc
    if not isinstance(value, dict) or value.get("code") != "00000" or not isinstance(value.get("data"), list):
        raise AlternativeMarketError("public_provider_schema_failure")
    return value


def _atomic(path: Path, value: dict) -> None:
    # Check existing parents and final target before any replace; links cannot be
    # used to redirect this public-data cache into another profile.
    for candidate in (path, *path.parents):
        if candidate.exists():
            mode = candidate.lstat()
            if candidate.is_symlink() or getattr(mode, "st_file_attributes", 0) & 0x400:
                raise AlternativeMarketError("cache_link_rejected")
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".bitget-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as output:
            output.write(canonical_bytes(value))
            output.flush()
            os.fsync(output.fileno())
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def _validate(value: dict) -> dict:
    if (value.get("contract_version") != CONTRACT or value.get("provider") != "bitget"
            or value.get("market_category") != "spot" or value.get("symbol") not in SYMBOLS
            or value.get("timeframe") not in STEPS or value.get("execution_eligible") is not False):
        raise AlternativeMarketError("provider_dataset_identity_failure")
    core = {k: v for k, v in value.items() if k != "dataset_sha256"}
    if hashlib.sha256(canonical_bytes(core)).hexdigest() != value.get("dataset_sha256"):
        raise AlternativeMarketError("provider_dataset_digest_failure")
    start, end = value.get("start_ms"), value.get("end_exclusive_ms")
    step = STEPS[value["timeframe"]]
    if (type(start) is not int or type(end) is not int or start % step or end % step
            or not 3 <= (end - start) // step <= 1800
            or type(value.get("observed_at_ms")) is not int
            or end > value["observed_at_ms"]):
        raise AlternativeMarketError("provider_closed_window_failure")
    try:
        parse_closed_bars(value.get("rows", []), interval_ms=step,
                          start_ms=start, end_exclusive_ms=end)
    except (BitgetDemoAdapterError, TypeError) as exc:
        raise AlternativeMarketError("provider_candle_integrity_failure") from exc
    return value


def _dataset(symbol, timeframe, rows, start, end, observed, evidence, *, historical=False):
    core = {"contract_version": CONTRACT, "provider": "bitget", "market_category": "spot",
            "symbol": symbol, "timeframe": timeframe, "start_ms": start,
            "end_exclusive_ms": end, "observed_at_ms": observed,
            "historical_only": historical, "execution_eligible": False,
            "source_evidence": evidence, "rows": rows}
    return _validate({**core, "dataset_sha256": hashlib.sha256(canonical_bytes(core)).hexdigest()})


class AlternativeMarketStore:
    def __init__(self, root: Path, *, fetcher=public_json, clock_ms=None, interval_seconds=60):
        self.root = root.absolute()
        self.fetcher = fetcher
        self.clock_ms = clock_ms or (lambda: int(time.time() * 1000))
        self.interval_seconds = interval_seconds
        self.lock = threading.RLock()
        self.refresh_lock = threading.Lock()
        self.stop_event = threading.Event()
        self.thread = None
        self.enabled = False
        self.state = {"status": "not_checked", "successful_cycles": 0, "failures": 0, "cells": []}
        settings = self.root / "settings.json"
        if settings.exists():
            persisted = safe_json(settings)
            if type(persisted.get("enabled")) is not bool:
                raise AlternativeMarketError("invalid_feed_settings")
            if persisted["enabled"]:
                self.set_polling(True)

    def _summary(self, value: dict) -> dict:
        now = self.clock_ms()
        end = value["end_exclusive_ms"]
        fresh = (not value["historical_only"] and 0 <= now - value["observed_at_ms"] <= 180_000
                 and end == now // STEPS[value["timeframe"]] * STEPS[value["timeframe"]])
        return {k: value[k] for k in ("provider", "market_category", "symbol", "timeframe",
                                     "start_ms", "end_exclusive_ms", "observed_at_ms",
                                     "dataset_sha256", "historical_only", "execution_eligible")} | {
                                         "row_count": len(value["rows"]), "fresh": fresh}

    def snapshot(self) -> dict:
        datasets, rejected = [], []
        for path in sorted([*self.root.glob("latest-*.json"), *self.root.glob("historical-*.json")]):
            try:
                datasets.append(self._summary(_validate(safe_json(path, limit=2_000_000))))
            except (OSError, ResearchReportError, AlternativeMarketError) as exc:
                rejected.append({"file": path.name, "status": "rejected", "reason": str(exc)})
        with self.lock:
            state = json.loads(json.dumps(self.state))
        fresh = sum(d["fresh"] for d in datasets)
        state["feed_healthy"] = fresh == 6 and state["status"] == "available"
        return {"contract_version": "nexus.alternative-market-status.v1", "provider": "bitget",
                "source_label": "Bitget · independent research backup", "read_only_market_data": True,
                "primary_execution_provider": "Bybit", "execution_eligible": False,
                "paper_mutation_authority": False, "live_trading_authority": False,
                "polling_enabled": self.enabled, "poll_interval_seconds": self.interval_seconds,
                "dataset_count": len(datasets), "datasets": datasets, "rejected": rejected,
                "state": state}

    def refresh(self) -> dict:
        if not self.refresh_lock.acquire(blocking=False):
            return {"status": "already_running"}
        cells, now = [], self.clock_ms()
        try:
            with self.lock:
                self.state["status"] = "refreshing"
            for symbol in SYMBOLS:
                for timeframe, step in STEPS.items():
                    end = now // step * step
                    start = end - 120 * step
                    params = {"symbol": symbol, "granularity": GRANULARITY[timeframe],
                              "endTime": str(end), "limit": "120"}
                    url = HOST + SPOT_PATH + "?" + urllib.parse.urlencode(sorted(params.items()))
                    try:
                        body = self.fetcher(url)
                        if body.get("code") != "00000" or not isinstance(body.get("data"), list):
                            raise AlternativeMarketError("public_provider_schema_failure")
                        raw_rows = body["data"]
                        # The active candle can be returned by public endpoints.
                        # Retain only the requested closed window; exact coverage is
                        # still required by the provider-native validator.
                        if any(not isinstance(r, list) or len(r) < 7 or not isinstance(r[0], str)
                               or not r[0].isdigit() for r in raw_rows):
                            raise AlternativeMarketError("public_candle_row_schema_failure")
                        rows = [r for r in raw_rows if start <= int(r[0]) < end]
                        rows.sort(key=lambda r: int(r[0]))
                        value = _dataset(symbol, timeframe, rows, start, end, now,
                                         {"url": url, "http_status": 200,
                                          "body_sha256": hashlib.sha256(canonical_bytes(body)).hexdigest()})
                        _atomic(self.root / f"latest-{symbol}-{timeframe}.json", value)
                        cells.append({"symbol": symbol, "timeframe": timeframe, "status": "available"})
                    except (OSError, ValueError) as exc:
                        cells.append({"symbol": symbol, "timeframe": timeframe,
                                      "status": "unavailable", "reason": str(exc)})
            success = all(c["status"] == "available" for c in cells)
            with self.lock:
                self.state = {"status": "available" if success else "degraded", "checked_at_ms": now,
                              "successful_cycles": self.state["successful_cycles"] + 1 if success else 0,
                              "failures": 0 if success else self.state["failures"] + 1, "cells": cells}
                _atomic(self.root / "status.json", self.state)
            return self.snapshot()
        finally:
            self.refresh_lock.release()

    def set_polling(self, enabled: bool) -> dict:
        if type(enabled) is not bool:
            raise AlternativeMarketError("enabled_must_be_boolean")
        with self.lock:
            if enabled and self.thread is not None and self.thread.is_alive():
                return {"status": "already_running"}
            self.enabled = enabled
            _atomic(self.root / "settings.json", {"enabled": enabled})
            if not enabled:
                self.stop_event.set()
                return {"status": "stopped"}
            self.stop_event = threading.Event()
            self.thread = threading.Thread(target=self._poll, daemon=True, name="bitget-public-data")
            self.thread.start()
            return {"status": "started", "poll_interval_seconds": self.interval_seconds}

    def _poll(self):
        while not self.stop_event.is_set():
            try:
                self.refresh()
            except (OSError, ValueError) as exc:
                with self.lock:
                    self.state["status"] = "cache_failure"
                    self.state["reason"] = str(exc)
                    self.enabled = False
                return
            if self.state["failures"] >= 2:
                with self.lock:
                    self.state["status"] = "paused_after_two_failed_cycles"
                    self.enabled = False
                    _atomic(self.root / "settings.json", {"enabled": False})
                    _atomic(self.root / "status.json", self.state)
                return
            self.stop_event.wait(self.interval_seconds)

    def import_audit(self, audit_root: Path) -> dict:
        """Load the already-collected official audit, keeping its historical label."""
        manifest = safe_json(audit_root / "bitget-manifest.json", limit=2_000_000)
        if (manifest.get("provider") != "bitget" or manifest.get("collection_checks_passed") is not True
                or manifest.get("demo_replacement_authorized") is not False
                or len(manifest.get("cells", [])) != 2
                or {c.get("asset") for c in manifest["cells"]} != {"BTC", "ETH"}):
            raise AlternativeMarketError("audit_manifest_rejected")
        receipts = []
        for item in manifest["http_evidence"]:
            url = item["url"]
            parts = urllib.parse.urlsplit(url)
            if parts.scheme != "https" or parts.netloc != "api.bitget.com" or item["http_status"] != 200:
                raise AlternativeMarketError("audit_transport_rejected")
            key = hashlib.sha256(url.encode()).hexdigest()
            receipt = safe_json(audit_root / "public-http" / f"{key}.json", limit=2_000_000)
            if (receipt.get("url") != url or receipt.get("http_status") != 200
                    or hashlib.sha256(canonical_bytes(receipt["body"])).hexdigest() != item["body_sha256"]
                    or receipt.get("body_sha256") != item["body_sha256"]):
                raise AlternativeMarketError("audit_receipt_digest_failure")
            receipts.append(receipt)
        end = manifest["end_exclusive"] * 1000
        observed = int(datetime.fromisoformat(manifest["observed_at"]).timestamp() * 1000)
        checks = []
        for cell in manifest["cells"]:
            symbol = cell["asset"] + "USDT"
            rows = []
            relevant = []
            for receipt in receipts:
                url = urllib.parse.urlsplit(receipt["url"])
                query = urllib.parse.parse_qs(url.query)
                if query.get("symbol") != [symbol]:
                    continue
                if url.path == SPOT_PATH:
                    rows.extend(receipt["body"]["data"])
                    relevant.append({k: receipt[k] for k in ("url", "http_status", "body_sha256", "observed_at")})
            start = end - 300 * 86_400_000
            rows = [r for r in rows if start <= int(r[0]) < end]
            rows.sort(key=lambda r: int(r[0]))
            if len(rows) != 1800 or not cell["spot_300d_4h"]["complete"]:
                raise AlternativeMarketError("audit_historical_coverage_failure")
            normalized = [[int(r[0]) // 1000, *[float(v) for v in r[1:6]]] for r in rows]
            if hashlib.sha256(canonical_bytes(normalized)).hexdigest() != cell["spot_300d_4h"]["normalized_sha256"]:
                raise AlternativeMarketError("audit_normalized_digest_failure")
            value = _dataset(symbol, "4h", rows, start, end, observed, relevant, historical=True)
            _atomic(self.root / f"historical-{symbol}-4h.json", value)
            contracts = [r["body"]["data"] for r in receipts if "/contracts?" in r["url"]
                         and urllib.parse.parse_qs(urllib.parse.urlsplit(r["url"]).query).get("symbol") == [symbol]]
            tiers = [r["body"]["data"] for r in receipts if "/query-position-lever?" in r["url"]
                     and urllib.parse.parse_qs(urllib.parse.urlsplit(r["url"]).query).get("symbol") == [symbol]]
            if len(contracts) != 1 or len(contracts[0]) != 1 or len(tiers) != 1:
                raise AlternativeMarketError("audit_native_instrument_binding_failure")
            instrument = parse_instrument(contracts[0][0], expected_symbol=symbol)
            native_tiers = parse_risk_tiers(tiers[0])
            source_receipts = [r for r in receipts
                               if urllib.parse.parse_qs(urllib.parse.urlsplit(r["url"]).query).get("symbol") == [symbol]]
            trade_rows = [r["body"]["data"] for r in source_receipts
                          if urllib.parse.urlsplit(r["url"]).path == "/api/v2/mix/market/history-candles"
                          and urllib.parse.parse_qs(urllib.parse.urlsplit(r["url"]).query).get("granularity") == ["4H"]]
            funding_rows = [r["body"]["data"] for r in source_receipts
                            if urllib.parse.urlsplit(r["url"]).path == "/api/v2/mix/market/history-fund-rate"]
            if len(trade_rows) != 1 or len(funding_rows) != 1:
                raise AlternativeMarketError("audit_futures_source_binding_failure")
            bars = parse_closed_bars(trade_rows[0], interval_ms=14_400_000,
                                     start_ms=end - 86_400_000, end_exclusive_ms=end)
            selected_funding = [r for r in funding_rows[0] if end - 86_400_000 <= int(r["fundingTime"]) < end]
            selected_funding.sort(key=lambda r: int(r["fundingTime"]))
            funding = parse_funding_points(selected_funding, interval_hours=instrument.funding_interval_hours)
            if len(funding) != cell["funding_24h"]["expected"]:
                raise AlternativeMarketError("audit_funding_coverage_failure")
            price = normalized_demo_price(price=str(bars[-1].close), instrument=instrument)
            quantity = normalized_demo_quantity(target_notional="100", price=str(price), instrument=instrument)
            checks.append({"symbol": symbol, "provider": "bitget", "purpose": "native_units_fee_check_only",
                           "quantity": str(quantity), "price_tick": str(instrument.price_tick),
                           "quantity_step": str(instrument.quantity_step),
                           "example_taker_fee_usdt": str(quantity * price * instrument.taker_fee_rate),
                           "example_long_funding_usdt": [str(quantity * price * p.rate) for p in funding],
                           "price_source": "Bitget USDT-FUTURES closed trade candle",
                           "funding_interval_hours": instrument.funding_interval_hours,
                           "risk_tier_count": len(native_tiers), "orders_sent": False,
                           "paper_mutated": False, "demo_replacement_authorized": False})
        _atomic(self.root / "audit-reconciliation.json", {"status": "verified", "checks": checks,
                                                        "execution_eligible": False})
        return {"status": "imported", "historical_datasets": 2, "native_adapter_checks": checks}
