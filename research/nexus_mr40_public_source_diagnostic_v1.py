"""Bounded read-only Bybit Spot source diagnostic; never starts Paper or orders."""
from __future__ import annotations

import argparse
import base64
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import platform
import socket
import ssl
import struct
import time

import requests

CLASSIFIER_SHA = "133d231e7a080c3187d4cfd26e40b244801b2d04a8b9f3774315429079be116c"
STEP = 14_400_000
MAX_BODY = 262_144


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def spot_stream_probe():
    """One official public Spot connection, fresh quote only; no credentials."""
    host, path = "stream.bybit.com", "/v5/public/spot"
    result = {"url": "wss://" + host + path, "attempted": True, "fresh_quote": False}
    deadline = time.monotonic() + 16
    sock = None
    try:
        raw = socket.create_connection((host, 443), timeout=4)
        sock = ssl.create_default_context().wrap_socket(raw, server_hostname=host)
        sock.settimeout(4)
        key = base64.b64encode(os.urandom(16)).decode()
        request = (f"GET {path} HTTP/1.1\r\nHost: {host}\r\nUpgrade: websocket\r\n"
                   f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n")
        sock.sendall(request.encode())
        data = b""
        while b"\r\n\r\n" not in data:
            if len(data) > 16384 or time.monotonic() >= deadline:
                raise ValueError("handshake bound exceeded")
            part = sock.recv(4096)
            if not part:
                raise ValueError("handshake closed")
            data += part
        header, buffered = data.split(b"\r\n\r\n", 1)
        result["http_status_line"] = header.split(b"\r\n", 1)[0].decode("ascii", errors="replace")
        if not header.startswith(b"HTTP/1.1 101 "):
            result["response_excerpt"] = buffered[:512].decode("utf-8", errors="replace")
            return result
        headers = dict(line.split(b":", 1) for line in header.split(b"\r\n")[1:] if b":" in line)
        headers = {k.lower(): v.strip() for k, v in headers.items()}
        expected = base64.b64encode(hashlib.sha1((key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()).digest())
        if headers.get(b"sec-websocket-accept") != expected:
            raise ValueError("invalid websocket accept")

        def send(opcode, payload):
            mask = os.urandom(4)
            if len(payload) >= 126:
                raise ValueError("bounded subscription only")
            sock.sendall(bytes((0x80 | opcode, 0x80 | len(payload))) + mask
                         + bytes(v ^ mask[i % 4] for i, v in enumerate(payload)))

        def take(count):
            nonlocal buffered
            while len(buffered) < count:
                if time.monotonic() >= deadline:
                    raise TimeoutError("stream observation deadline")
                piece = sock.recv(max(4096, count - len(buffered)))
                if not piece:
                    raise ValueError("stream closed")
                buffered += piece
            out, buffered = buffered[:count], buffered[count:]
            return out

        send(1, json.dumps({"op": "subscribe", "args": ["tickers.BTCUSDT"]}).encode())
        for _ in range(20):
            first, second = take(2)
            if not first & 0x80 or second & 0x80 or first & 0x70:
                raise ValueError("unsupported server frame")
            length = second & 127
            if length == 126:
                length = struct.unpack("!H", take(2))[0]
            elif length == 127:
                length = struct.unpack("!Q", take(8))[0]
            if length > 65536:
                raise ValueError("oversized server frame")
            content = take(length)
            opcode = first & 15
            if opcode == 9:
                send(10, content)
                continue
            if opcode == 8:
                raise ValueError("server close")
            if opcode != 1:
                continue
            message = json.loads(content)
            if message.get("topic") != "tickers.BTCUSDT":
                continue
            ticker = message.get("data", {})
            if ticker.get("symbol") != "BTCUSDT":
                continue
            stamp, price = int(message["ts"]), float(ticker["lastPrice"])
            age = int(time.time() * 1000) - stamp
            if not price > 0 or not price < float("inf"):
                raise ValueError("invalid price")
            result.update({"quote_timestamp_ms": stamp, "quote_age_ms": age,
                           "last_price": ticker["lastPrice"], "fresh_quote": -10000 <= age <= 120000})
            send(8, b"")
            return result
        raise ValueError("no bounded Spot ticker observation")
    except Exception as exc:
        result.update({"error_type": type(exc).__name__, "error": str(exc)[:256]})
        return result
    finally:
        if sock is not None:
            sock.close()


def run(classifier_path, output):
    if output.exists():
        raise ValueError("refuse diagnostic overwrite")
    raw = classifier_path.read_bytes().replace(b"\r\n", b"\n")
    if hashlib.sha256(raw).hexdigest() != CLASSIFIER_SHA:
        raise ValueError("classifier substitution")
    spec = importlib.util.spec_from_file_location("mr40_frozen_source_classifier", classifier_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    report = {"schema": "nexus.mr40-public-source-diagnostic.v1", "worker": platform.node(),
              "started_utc": datetime.now(timezone.utc).isoformat(), "python": platform.python_version(),
              "classifier_sha256": CLASSIFIER_SHA, "requests_version": requests.__version__,
              "source_ready": False, "http_observations": [], "exchange_orders": 0,
              "actual_demo_started": False, "live_enabled": False, "state_mutations": False}
    explicit_restriction = False
    with requests.Session() as session:
        for host in module.OFFICIAL_MAINNET_BASE_URLS:
            item = {"url": host + "/v5/market/kline", "params": {"category": "spot", "symbol": "BTCUSDT", "interval": "240", "limit": 200}}
            report["http_observations"].append(item)
            try:
                with session.get(item["url"], params=item["params"], timeout=(4, 8),
                                 allow_redirects=False, stream=True, headers={"Accept": "application/json"}) as response:
                    body = response.raw.read(MAX_BODY + 1, decode_content=True)
                    if len(body) > MAX_BODY:
                        raise ValueError("oversized HTTP response")
                    response._content = body
                    item.update({"http_status": response.status_code, "content_type": module._safe_content_type(response),
                                 "edge": module._edge_class(response), "server": response.headers.get("Server"),
                                 "body_bytes": len(body), "body_sha256": hashlib.sha256(body).hexdigest(),
                                 "request_body_is_none": response.request.body is None})
                    if response.status_code == 403:
                        reason, code, code_category, message_category = module._classify_403(response)
                        item.update({"classification": reason, "ret_code": code, "ret_code_category": code_category,
                                     "ret_msg_category": message_category, "response_excerpt": body[:512].decode("utf-8", errors="replace")})
                        if reason != "unclassified":
                            explicit_restriction = True
                            break
                    elif response.status_code == 200:
                        payload = response.json()
                        now = int(time.time() * 1000)
                        stamp = payload.get("time")
                        current = now // STEP * STEP
                        # Discard the forming candle before strict normalization.
                        selected = [row for row in payload.get("result", {}).get("list", []) if current - 181 * STEP <= int(row[0]) < current]
                        filtered = {**payload, "result": {**payload.get("result", {}), "list": selected}}
                        candles = module.normalize_closed_klines(filtered, symbol="BTCUSDT", interval="240", now_ms=now,
                                                                 start_time_ms=current - 181 * STEP, end_time_ms=current - STEP)
                        metadata = payload.get("result", {})
                        if metadata.get("symbol") != "BTCUSDT" or metadata.get("category") != "spot":
                            raise ValueError("wrong market identity")
                        fresh = isinstance(stamp, int) and -10000 <= now - stamp <= 120000
                        item.update({"closed_bars": len(candles), "server_time_ms": stamp, "server_time_fresh": fresh})
                        report["source_ready"] = fresh and len(candles) == 181
                        if report["source_ready"]:
                            break
                    elif response.status_code in (429, 451):
                        explicit_restriction = True
                        break
            except Exception as exc:
                item.update({"error_type": type(exc).__name__, "error": str(exc)[:256]})
    report["explicit_restriction"] = explicit_restriction
    report["websocket"] = ({"attempted": False, "reason": "explicit_access_or_rate_rejection"}
                            if explicit_restriction else spot_stream_probe())
    report["finished_utc"] = datetime.now(timezone.utc).isoformat()
    report["source_sha256"] = hashlib.sha256(Path(__file__).read_bytes().replace(b"\r\n", b"\n")).hexdigest()
    report["digest"] = digest(report)
    output.write_text(json.dumps(report, sort_keys=True, indent=2, allow_nan=False) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(report), flush=True)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--classifier-path", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    run(**vars(parser.parse_args()))
