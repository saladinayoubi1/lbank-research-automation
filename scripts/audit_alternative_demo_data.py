"""Bounded public-feed qualification; never opens a Paper account or sends orders.

Each successful HTTP body is immutable and cached by URL for resumable audits.
A 401/403 stops that provider; only one retry for transient transport failures.
The output qualifies data collection, not a strategy, adapter or Demo promotion.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import math
from pathlib import Path
import time
import urllib.error
import urllib.parse
import urllib.request

BAR = 4 * 3600
DAY = 86400
ALLOWED = {
    "api.bitget.com": {"/api/v2/spot/market/history-candles", "/api/v2/mix/market/history-candles",
        "/api/v2/mix/market/history-mark-candles", "/api/v2/mix/market/history-fund-rate",
        "/api/v2/mix/market/contracts", "/api/v2/mix/market/query-position-lever"},
    "api.kucoin.com": {"/api/ua/v1/market/kline"},
    "api-futures.kucoin.com": {"/api/v1/contract/funding-rates",
        "/api/v1/contracts/XBTUSDTM", "/api/v1/contracts/ETHUSDTM",
        "/api/v1/contracts/risk-limit/XBTUSDTM", "/api/v1/contracts/risk-limit/ETHUSDTM"},
}


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def atomic_json(path, value):
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_bytes(canonical(value) + b"\n")
    temp.replace(path)


class AuditFailure(Exception):
    pass


class RequestBudget(AuditFailure):
    pass


class PublicReader:
    def __init__(self, root, budget=48):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self.budget = budget
        self.requests = 0
        self.evidence = []
        self.denied_hosts = set()
        # Direct verified TLS to official public endpoints; no account, proxy or credentials.
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())

    def get(self, host, endpoint, params=None):
        if host not in ALLOWED or endpoint not in ALLOWED[host]:
            raise AuditFailure("DESTINATION_NOT_ALLOWED")
        if host in self.denied_hosts:
            raise AuditFailure("PROVIDER_ACCESS_DENIED")
        url = "https://" + host + endpoint
        if params:
            url += "?" + urllib.parse.urlencode(sorted(params.items()))
        key = hashlib.sha256(url.encode()).hexdigest()
        cached = self.root / (key + ".json")
        if cached.exists():
            receipt = json.loads(cached.read_bytes())
            if receipt.get("url") != url or hashlib.sha256(canonical(receipt["body"])).hexdigest() != receipt.get("body_sha256"):
                raise AuditFailure("CACHE_DIGEST_MISMATCH")
            self.evidence.append({k: v for k, v in receipt.items() if k != "body"})
            return receipt["body"]
        for attempt in range(2):
            if self.requests >= self.budget:
                raise RequestBudget("REQUEST_BUDGET_CHECKPOINT")
            self.requests += 1
            try:
                request = urllib.request.Request(url, headers={"User-Agent": "NEXUS-public-data-audit/1", "Accept": "application/json"})
                with self.opener.open(request, timeout=8) as response:
                    raw = response.read(2_000_001)
                    if len(raw) > 2_000_000:
                        raise AuditFailure("BODY_TOO_LARGE")
                    body = json.loads(raw)
                    if body.get("code") not in {"00000", "200000"}:
                        raise AuditFailure("PROVIDER_CODE_" + str(body.get("code", "MISSING")))
                receipt = {"url": url, "observed_at": dt.datetime.now(dt.timezone.utc).isoformat(),
                    "http_status": 200, "attempts": attempt + 1,
                    "body_sha256": hashlib.sha256(canonical(body)).hexdigest(), "body": body}
                atomic_json(cached, receipt)
                self.evidence.append({k: v for k, v in receipt.items() if k != "body"})
                return body
            except urllib.error.HTTPError as exc:
                self.evidence.append({"url": url, "http_status": exc.code, "attempts": attempt + 1})
                if exc.code in {401, 403}:
                    self.denied_hosts.update({host} if host == "api.bitget.com" else {"api.kucoin.com", "api-futures.kucoin.com"})
                    raise AuditFailure("PROVIDER_ACCESS_DENIED") from exc
                if exc.code not in {500, 502, 503, 504} or attempt:
                    raise AuditFailure("HTTP_" + str(exc.code)) from exc
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
                if attempt:
                    raise AuditFailure("TRANSPORT_OR_JSON_FAILURE") from exc
        raise AuditFailure("TRANSPORT_FAILURE")


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise AuditFailure("HTTP_REDIRECT_REJECTED")


def rows_from(body):
    data = body.get("data")
    if isinstance(data, dict):
        return data.get("list", [])
    return data if isinstance(data, list) else []


def check_bars(rows, start, end, interval=BAR, *, milliseconds=False, volume=True):
    expected = set(range(start, end, interval))
    values = {}
    invalid = 0
    duplicates = 0
    conflicts = 0
    outside = 0
    for row in rows:
        try:
            timestamp = float(row[0]) / (1000 if milliseconds else 1)
            t = int(timestamp)
            if timestamp != t or t % interval:
                raise ValueError("unaligned timestamp")
            if t not in expected:
                outside += 1
                continue
            nums = [float(x) for x in row[1:5]]
            if len(nums) != 4 or not all(math.isfinite(x) and x > 0 for x in nums):
                raise ValueError("invalid prices")
            o, h, low, c = nums
            if low > min(o, c) or h < max(o, c) or low > h:
                raise ValueError("invalid OHLC order")
            v = float(row[5]) if volume else 0.0
            if not math.isfinite(v) or v < 0:
                raise ValueError("invalid volume")
            normalized = [t, *nums, v]
            if t in values:
                duplicates += 1
                conflicts += values[t] != normalized
            else:
                values[t] = normalized
        except (ValueError, TypeError, IndexError, OverflowError):
            invalid += 1
    missing = sorted(expected - values.keys())
    ordered = [values[t] for t in sorted(values)]
    return {"expected": len(expected), "valid": len(values), "missing": len(missing),
        "missing_first": missing[:8], "invalid": invalid, "duplicates": duplicates, "conflicts": conflicts,
        "outside_requested_closed_grid": outside, "complete": not missing and not invalid and not conflicts,
        "first": ordered[0][0] if ordered else None, "last": ordered[-1][0] if ordered else None,
        "normalized_sha256": hashlib.sha256(canonical(ordered)).hexdigest()}


def spot_warmup(reader, provider, asset, start, end):
    rows = []
    if provider == "bitget":
        cursor = end * 1000
        for _ in range(12):
            batch = rows_from(reader.get("api.bitget.com", "/api/v2/spot/market/history-candles",
                {"symbol": asset + "USDT", "granularity": "4h", "endTime": cursor, "limit": 200}))
            if not batch:
                break
            rows.extend(batch)
            first = min(int(x[0]) for x in batch)
            if first <= start * 1000:
                break
            if first >= cursor:
                raise AuditFailure("PAGINATION_NOT_ADVANCING")
            # Bitget floors endTime to the candle boundary and excludes that
            # boundary. Subtracting 1ms would skip an entire candle per page.
            cursor = first
        return check_bars(rows, start, end, milliseconds=True)
    for cursor in range(start, end, 1400 * BAR):
        rows.extend(rows_from(reader.get("api.kucoin.com", "/api/ua/v1/market/kline",
            {"tradeType": "SPOT", "symbol": asset + "-USDT", "interval": "4hour",
             "startAt": cursor, "endAt": min(end, cursor + 1400 * BAR) - 1})))
    return check_bars(rows, start, end)


def cell(reader, provider, asset, end):
    start = end - 300 * DAY
    out = {"asset": asset, "spot_300d_4h": spot_warmup(reader, provider, asset, start, end)}
    recent = end - DAY
    native = asset + "USDT" if provider == "bitget" else ("XBTUSDTM" if asset == "BTC" else "ETHUSDTM")
    if provider == "bitget":
        common = {"symbol": native, "productType": "USDT-FUTURES", "granularity": "4H",
            "startTime": recent * 1000, "endTime": end * 1000, "limit": 200}
        for name, endpoint in [("trade_4h", "history-candles"), ("mark_4h", "history-mark-candles")]:
            bars = rows_from(reader.get("api.bitget.com", "/api/v2/mix/market/" + endpoint, common))
            out[name] = check_bars(bars, recent, end, milliseconds=True, volume=name != "mark_4h")
        minute_params = {**common, "granularity": "1m", "startTime": (end - BAR) * 1000,
            "endTime": (end - BAR + 5 * 60) * 1000}
        minute = rows_from(reader.get("api.bitget.com", "/api/v2/mix/market/history-candles", minute_params))
        spec = rows_from(reader.get("api.bitget.com", "/api/v2/mix/market/contracts", {"symbol": native, "productType": "USDT-FUTURES"}))
        if len(spec) != 1 or spec[0].get("symbol") != native:
            raise AuditFailure("INSTRUMENT_BINDING_FAILED")
        spec = spec[0]
        tiers = rows_from(reader.get("api.bitget.com", "/api/v2/mix/market/query-position-lever", {"symbol": native, "productType": "USDT-FUTURES"}))
        funding = rows_from(reader.get("api.bitget.com", "/api/v2/mix/market/history-fund-rate", {"symbol": native, "productType": "USDT-FUTURES", "pageSize": 100, "pageNo": 1}))
        funding_interval = int(spec.get("fundInterval", 0)) * 3600
        rates = [(int(x["fundingTime"]) // 1000, float(x["fundingRate"])) for x in funding]
        keys = ["symbol", "minTradeNum", "sizeMultiplier", "minTradeUSDT", "pricePlace", "priceEndStep", "makerFeeRate", "takerFeeRate", "fundInterval"]
        required = ["minTradeNum", "sizeMultiplier", "minTradeUSDT", "makerFeeRate", "takerFeeRate", "fundInterval"]
        out["minute_execution_5m"] = check_bars(minute, end - BAR, end - BAR + 300, 60, milliseconds=True)
    else:
        common = {"tradeType": "FUTURES", "interval": "4hour", "startAt": recent, "endAt": end - 1}
        for name, symbol in [("trade_4h", native), ("mark_4h", native + "-mark-price")]:
            bars = rows_from(reader.get("api.kucoin.com", "/api/ua/v1/market/kline", {**common, "symbol": symbol}))
            out[name] = check_bars(bars, recent, end, volume=name != "mark_4h")
        minute = rows_from(reader.get("api.kucoin.com", "/api/ua/v1/market/kline", {"tradeType": "FUTURES", "symbol": native,
            "interval": "1min", "startAt": end - BAR, "endAt": end - BAR + 299}))
        spec = reader.get("api-futures.kucoin.com", "/api/v1/contracts/" + native)["data"]
        if spec.get("symbol") != native or spec.get("isInverse") is not False:
            raise AuditFailure("INSTRUMENT_BINDING_FAILED")
        tiers = rows_from(reader.get("api-futures.kucoin.com", "/api/v1/contracts/risk-limit/" + native))
        funding = rows_from(reader.get("api-futures.kucoin.com", "/api/v1/contract/funding-rates", {"symbol": native, "from": recent * 1000, "to": end * 1000 - 1}))
        funding_interval = int(spec.get("fundingRateGranularity", 0)) // 1000
        rates = [(int(x["timepoint"]) // 1000, float(x["fundingRate"])) for x in funding]
        keys = ["symbol", "lotSize", "multiplier", "tickSize", "makerFeeRate", "takerFeeRate", "fundingRateGranularity", "isInverse", "settleCurrency"]
        required = ["lotSize", "multiplier", "tickSize", "makerFeeRate", "takerFeeRate", "fundingRateGranularity"]
        out["minute_execution_5m"] = check_bars(minute, end - BAR, end - BAR + 300, 60)
    expected_funding = set(range(((recent + funding_interval - 1) // funding_interval) * funding_interval, end, funding_interval)) if funding_interval > 0 else set()
    observed_funding = {t for t, rate in rates if recent <= t < end and math.isfinite(rate)}
    out["funding_24h"] = {"interval_seconds": funding_interval, "expected": len(expected_funding),
        "observed": len(observed_funding), "complete": bool(expected_funding) and observed_funding == expected_funding}
    out["instrument"] = {k: spec.get(k) for k in keys}
    out["instrument_fields_present"] = all(spec.get(k) is not None for k in required)
    out["risk_tiers"] = {"count": len(tiers), "sha256": hashlib.sha256(canonical(tiers)).hexdigest(),
        "present": bool(tiers), "mode": "isolated"}
    out["collection_checks_passed"] = all(out[k]["complete"] for k in ["spot_300d_4h", "trade_4h", "mark_4h", "minute_execution_5m", "funding_24h"]) and out["instrument_fields_present"] and bool(tiers)
    out["demo_replacement_authorized"] = False
    return out


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--provider", required=True, choices=["bitget", "kucoin"])
    parser.add_argument("--end", type=int, help="exclusive UTC 4h boundary; fixed across resumed runs")
    parser.add_argument("--budget", type=int, default=48)
    args = parser.parse_args()
    root = Path(args.output)
    root.mkdir(parents=True, exist_ok=True)
    metadata = root / (args.provider + "-manifest.json")
    source_sha = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    previous = json.loads(metadata.read_bytes()) if metadata.exists() else None
    end = args.end or (previous["end_exclusive"] if previous else int(time.time()) // BAR * BAR)
    if end % BAR or args.budget < 1 or args.budget > 48:
        raise SystemExit("invalid bounded audit inputs")
    if previous and (previous["source_sha256"] != source_sha or previous["end_exclusive"] != end):
        raise SystemExit("immutable source/window mismatch; use a new audit directory")
    reader = PublicReader(root / "public-http", args.budget)
    result = {"schema": "nexus.alternative-demo-data-audit.v1", "provider": args.provider,
        "source_sha256": source_sha, "end_exclusive": end, "warmup_days": 300,
        "observed_at": dt.datetime.now(dt.timezone.utc).isoformat(), "cells": [],
        "private_credentials_used": False, "orders_sent": False, "owner_paper_mutated": False,
        "demo_replacement_authorized": False, "requires": ["provider-native adapter", "full historical replay",
            "independent numerical QA", "isolated Paper risk/fee/funding reconciliation", "persistent feed verification"]}
    for asset in ["BTC", "ETH"]:
        try:
            result["cells"].append(cell(reader, args.provider, asset, end))
        except RequestBudget as exc:
            result["checkpoint"] = str(exc)
            break
        except (AuditFailure, ValueError, KeyError, TypeError) as exc:
            result["cells"].append({"asset": asset, "collection_checks_passed": False,
                "reason": str(exc) if isinstance(exc, AuditFailure) else "PROVIDER_SCHEMA_OR_NUMERICAL_INVALID"})
            if str(exc) == "PROVIDER_ACCESS_DENIED":
                break
    result["requests_this_run"] = reader.requests
    result["http_evidence"] = reader.evidence
    result["collection_checks_passed"] = len(result["cells"]) == 2 and all(x.get("collection_checks_passed") for x in result["cells"])
    result["status"] = "CHECKPOINT" if "checkpoint" in result else "COLLECTION_CANDIDATE" if result["collection_checks_passed"] else "COLLECTION_FAILED"
    atomic_json(metadata, result)
    print(json.dumps({k: v for k, v in result.items() if k != "http_evidence"}, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
