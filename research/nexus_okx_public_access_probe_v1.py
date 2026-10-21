"""One user-requested OKX public-data trial. No private API or Paper integration."""
import argparse
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import platform
import time

STEP = 14_400_000
BASE = "https://www.okx.com"
ENDPOINTS = (
    ("server_time", "/api/v5/public/time", {}),
    ("ticker", "/api/v5/market/ticker", {"instId": "BTC-USDT"}),
    ("candles", "/api/v5/market/candles", {"instId": "BTC-USDT", "bar": "4H", "limit": "200"}),
)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def validate(observations, *, require_server_time=True):
    by_name = {item["name"]: item for item in observations}
    checks = {}
    required = ENDPOINTS if require_server_time else ENDPOINTS[1:]
    for name, _, _ in required:
        item = by_name.get(name)
        if not item or item.get("http_status") != 200 or item.get("payload", {}).get("code") != "0":
            raise ValueError("public endpoint unavailable: " + name)
    checks["server_time_verified"] = require_server_time
    checks["freshness_reference"] = "worker_utc_clock"
    if require_server_time:
        stamp = int(by_name["server_time"]["payload"]["data"][0]["ts"])
        checks["server_time_age_ms"] = by_name["server_time"]["observed_ms"] - stamp
    tick = by_name["ticker"]["payload"]["data"]
    if len(tick) != 1 or tick[0].get("instId") != "BTC-USDT" or tick[0].get("instType") != "SPOT":
        raise ValueError("wrong Spot ticker identity")
    tick = tick[0]
    last, bid, ask = (Decimal(tick[field]) for field in ("last", "bidPx", "askPx"))
    if not all(v.is_finite() and v > 0 for v in (last, bid, ask)) or bid > ask:
        raise ValueError("invalid Spot price or bid/ask")
    checks["ticker_age_ms"] = by_name["ticker"]["observed_ms"] - int(tick["ts"])
    ages = ("server_time_age_ms", "ticker_age_ms") if require_server_time else ("ticker_age_ms",)
    if not all(-10000 <= checks[k] <= 120000 for k in ages):
        raise ValueError("stale or future server time/ticker")
    candles = by_name["candles"]["payload"]["data"]
    seen, closed, forming = set(), [], 0
    now = by_name["candles"]["observed_ms"]
    for row in candles:
        if not isinstance(row, list) or len(row) != 9 or row[8] not in ("0", "1"):
            raise ValueError("invalid original OKX candle schema")
        opened = int(row[0])
        if opened % STEP or opened in seen or opened > now // STEP * STEP:
            raise ValueError("off-grid, duplicate or future candle")
        seen.add(opened)
        values = list(map(Decimal, row[1:8]))
        op, hi, lo, cl = values[:4]
        if not all(x.is_finite() for x in values) or min(op, hi, lo, cl) <= 0 or min(values[4:]) < 0:
            raise ValueError("invalid OHLCV")
        if hi < max(op, lo, cl) or lo > min(op, hi, cl):
            raise ValueError("invalid OHLC envelope")
        if row[8] == "1":
            if opened + STEP > now:
                raise ValueError("confirmed future/incomplete candle")
            closed.append(opened)
        else:
            forming += 1
    closed.sort()
    expected_last = now // STEP * STEP - STEP
    if len(closed) < 181 or closed[-181:] != list(range(expected_last - 180 * STEP, expected_last + STEP, STEP)):
        raise ValueError("latest 181 complete four-hour bars missing or stale")
    checks.update({"instrument": "BTC-USDT", "market": "SPOT", "timeframe": "4H",
                   "received_candles": len(candles), "confirmed_closed_candles": len(closed),
                   "forming_candles_excluded": forming, "latest_181_closed_grid_complete": True,
                   "latest_closed_open_ms": closed[-1], "oldest_received_open_ms": min(seen)})
    return checks


def run(output, market_only=False):
    if output.exists():
        raise ValueError("refuse trial overwrite")
    import requests
    result = {"schema": "nexus.okx-public-access-trial.v1", "worker": platform.node(),
              "started_utc": datetime.now(timezone.utc).isoformat(), "python": platform.python_version(),
              "requests_version": requests.__version__, "observations": [],
              "exchange": "OKX", "user_requested_trial": True, "fresh_public_data_verified": False,
              "market_only": market_only,
              "actual_demo_started": False, "exchange_orders": 0, "paper_state_mutated": False,
              "primary_exchange_configuration_changed": False, "live_enabled": False}
    with requests.Session() as session:
        for name, path, params in (ENDPOINTS[1:] if market_only else ENDPOINTS):
            item = {"name": name, "url": BASE + path, "params": params}
            result["observations"].append(item)
            started = time.monotonic()
            try:
                with session.get(item["url"], params=params, timeout=(4, 10), allow_redirects=False, stream=True) as response:
                    raw = response.raw.read(262145, decode_content=True)
                    item.update({"http_status": response.status_code, "observed_ms": int(time.time() * 1000),
                                 "elapsed_ms": round((time.monotonic() - started) * 1000),
                                 "content_type": response.headers.get("Content-Type"), "server": response.headers.get("Server"),
                                 "body_bytes": len(raw), "body_sha256": hashlib.sha256(raw).hexdigest(),
                                 "request_body_is_none": response.request.body is None,
                                 "auth_headers_present": any(k.lower().startswith("ok-access-") for k in response.request.headers)})
                    if len(raw) > 262144:
                        raise ValueError("oversized public response")
                    if response.status_code == 200:
                        item["payload"] = json.loads(raw)
                    else:
                        item["response_excerpt"] = raw[:512].decode("utf-8", errors="replace")
                        lower = raw.lower()
                        item["denial_markers"] = {
                            "cloudflare_attention_required": b"attention required! | cloudflare" in lower,
                            "you_have_been_blocked": b"you have been blocked" in lower,
                            "country_restriction_message": any(s in lower for s in (b"block access from your country", b"restricted country", b"country is not supported")),
                            "challenge_header": response.headers.get("cf-mitigated", "") == "challenge",
                        }
                    if response.status_code in (403, 429, 451) or 300 <= response.status_code < 400:
                        break
            except Exception as exc:
                item.update({"error_type": type(exc).__name__, "error": str(exc)[:256]})
    try:
        result["checks"] = validate(result["observations"], require_server_time=not market_only)
        result["fresh_public_data_verified"] = True
    except Exception as exc:
        result["validation_error"] = str(exc)
    result["finished_utc"] = datetime.now(timezone.utc).isoformat()
    result["source_sha256"] = hashlib.sha256(Path(__file__).read_bytes().replace(b"\r\n", b"\n")).hexdigest()
    result["digest"] = digest(result)
    with output.open("x", encoding="utf-8", newline="\n") as out:
        json.dump(result, out, sort_keys=True, indent=2, allow_nan=False)
        out.write("\n")
    print(json.dumps({k: v for k, v in result.items() if k != "observations"}), flush=True)
    print(json.dumps({"http": [{k: v for k, v in item.items() if k != "payload"} for item in result["observations"]]}), flush=True)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--market-only", action="store_true")
    run(**vars(parser.parse_args()))
