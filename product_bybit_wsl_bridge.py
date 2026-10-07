"""Bounded Bybit-only public-price bridge for the Windows Product UI.

On the owner Windows laptop the canonical Bybit network lane is WSL. This
module never accepts arbitrary URLs, credentials, order paths, or private API
headers. It prefers the official linear ticker mark; if that response is stale,
it first uses the official Bybit public linear WebSocket ticker. If that path
is unavailable, the bounded REST mark/order-book fallback remains available
for display-only PnL.
"""
from __future__ import annotations

import json
import math
import os
import re
import subprocess
import time
from pathlib import Path
from typing import Any, Callable

from bybit_derivatives_core_v1 import Client as BybitPublicClient, ValidationError

_TICKER_PATH = "/v5/market/tickers"
_ORDERBOOK_PATH = "/v5/market/orderbook"
_OFFICIAL_HOSTS = ("https://api.bytick.com", "https://api.bybit.com")
_SYMBOL_RE = re.compile(r"^[A-Z0-9]{3,32}$")
_MAX_STDOUT_BYTES = 200_000
_WSL_TIMEOUT_SECONDS = 7.0
_WSL_WS_TIMEOUT_SECONDS = 18.0
_WS_HOST = "stream.bybit.com"
_WS_PATH = "/v5/public/linear"
_MAX_QUOTE_AGE_SECONDS = 120.0
_FUTURE_TOLERANCE_SECONDS = 10.0


class WSLBybitBridgeError(ValidationError):
    pass


class WSLBybitInfrastructureUnavailable(WSLBybitBridgeError):
    pass


def _default_wsl_executable() -> str:
    root = Path(os.environ.get("SystemRoot", r"C:\Windows"))
    candidate = root / "System32" / "wsl.exe"
    return str(candidate) if candidate.is_file() else "wsl.exe"


def _validate_request(path: str, params: dict[str, Any]) -> str:
    if path != _TICKER_PATH or set(params) != {"category", "symbol"}:
        raise WSLBybitBridgeError("WSL Bybit bridge only accepts the public linear ticker")
    if params.get("category") != "linear":
        raise WSLBybitBridgeError("WSL Bybit bridge category must be linear")
    raw_symbol = params.get("symbol")
    if not isinstance(raw_symbol, str):
        raise WSLBybitBridgeError("unsupported Bybit symbol")
    symbol = raw_symbol.strip().upper()
    if not _SYMBOL_RE.fullmatch(symbol):
        raise WSLBybitBridgeError("unsupported Bybit symbol")
    return symbol


def _validate_payload(payload: Any, symbol: str) -> dict[str, Any]:
    if not isinstance(payload, dict) or payload.get("retCode") != 0:
        raise WSLBybitBridgeError("invalid Bybit public ticker response")
    result = payload.get("result")
    rows = result.get("list") if isinstance(result, dict) else None
    if not isinstance(result, dict) or result.get("category") != "linear" or not isinstance(rows, list) or len(rows) != 1:
        raise WSLBybitBridgeError("invalid Bybit public ticker result")
    row = rows[0]
    if not isinstance(row, dict) or row.get("symbol") != symbol:
        raise WSLBybitBridgeError("mismatched Bybit public ticker symbol")
    try:
        mark = float(row.get("markPrice"))
        stamp = float(payload.get("time"))
    except (TypeError, ValueError) as exc:
        raise WSLBybitBridgeError("malformed Bybit public ticker fields") from exc
    if not math.isfinite(mark) or mark <= 0 or not math.isfinite(stamp) or stamp <= 0:
        raise WSLBybitBridgeError("invalid Bybit public ticker fields")
    return payload


def _validate_orderbook_payload(payload: Any, symbol: str) -> tuple[float, float]:
    if not isinstance(payload, dict) or payload.get("retCode") != 0:
        raise WSLBybitBridgeError("invalid Bybit public orderbook response")
    result = payload.get("result")
    if not isinstance(result, dict) or result.get("s") != symbol:
        raise WSLBybitBridgeError("mismatched Bybit public orderbook symbol")
    bids, asks = result.get("b"), result.get("a")
    if not isinstance(bids, list) or not bids or not isinstance(asks, list) or not asks:
        raise WSLBybitBridgeError("missing Bybit public orderbook levels")
    try:
        bid = float(bids[0][0])
        ask = float(asks[0][0])
        stamp = float(result.get("ts") or payload.get("time"))
    except (TypeError, ValueError, IndexError) as exc:
        raise WSLBybitBridgeError("malformed Bybit public orderbook fields") from exc
    if not all(math.isfinite(v) and v > 0 for v in (bid, ask, stamp)) or bid > ask:
        raise WSLBybitBridgeError("invalid Bybit public orderbook fields")
    return (bid + ask) / 2.0, stamp


def _fresh(stamp_ms: float, now_ms: float) -> bool:
    age = (float(now_ms) - float(stamp_ms)) / 1000.0
    return -_FUTURE_TOLERANCE_SECONDS <= age <= _MAX_QUOTE_AGE_SECONDS


def _wsl_ws_script(symbol: str) -> str:
    symbol_literal = json.dumps(symbol)
    return f"""import base64, hashlib, json, os, socket, ssl, struct, time

HOST={json.dumps(_WS_HOST)}
PATH={json.dumps(_WS_PATH)}
SYMBOL={symbol_literal}
GUID="258EAFA5-E914-47DA-95CA-C5AB0DC85B11"

class Reader:
    def __init__(self, sock, initial=b""):
        self.sock=sock
        self.buf=initial
    def take(self,n):
        while len(self.buf)<n:
            part=self.sock.recv(max(4096,n-len(self.buf)))
            if not part:
                raise RuntimeError("socket closed")
            self.buf+=part
        out,self.buf=self.buf[:n],self.buf[n:]
        return out

def send_frame(sock, opcode, payload=b""):
    if isinstance(payload,str):
        payload=payload.encode()
    first=0x80 | opcode
    n=len(payload)
    key=os.urandom(4)
    if n<126:
        head=bytes([first,0x80|n])
    elif n<65536:
        head=bytes([first,0x80|126])+struct.pack("!H",n)
    else:
        head=bytes([first,0x80|127])+struct.pack("!Q",n)
    masked=bytes(v ^ key[i%4] for i,v in enumerate(payload))
    sock.sendall(head+key+masked)

def recv_frame(reader):
    b1,b2=reader.take(2)
    opcode=b1 & 0x0f
    n=b2 & 0x7f
    if n==126:
        n=struct.unpack("!H",reader.take(2))[0]
    elif n==127:
        n=struct.unpack("!Q",reader.take(8))[0]
    mask=reader.take(4) if b2 & 0x80 else None
    data=reader.take(n)
    if mask:
        data=bytes(v ^ mask[i%4] for i,v in enumerate(data))
    return opcode,data

raw=socket.create_connection((HOST,443),timeout=6)
ctx=ssl.create_default_context()
sock=ctx.wrap_socket(raw,server_hostname=HOST)
sock.settimeout(8)
key=base64.b64encode(os.urandom(16)).decode()
req=(f"GET {{PATH}} HTTP/1.1\r\nHost: {{HOST}}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
     f"Sec-WebSocket-Key: {{key}}\r\nSec-WebSocket-Version: 13\r\nUser-Agent: NEXUS-WSL-WS/1\r\n\r\n")
sock.sendall(req.encode())
buf=b""
while b"\r\n\r\n" not in buf:
    part=sock.recv(4096)
    if not part:
        raise RuntimeError("handshake closed")
    buf+=part
headers,initial=buf.split(b"\r\n\r\n",1)
if not headers.startswith(b"HTTP/1.1 101"):
    raise RuntimeError("websocket upgrade rejected")
accept=None
for line in headers.split(b"\r\n")[1:]:
    if line.lower().startswith(b"sec-websocket-accept:"):
        accept=line.split(b":",1)[1].strip().decode()
expected=base64.b64encode(hashlib.sha1((key+GUID).encode()).digest()).decode()
if accept!=expected:
    raise RuntimeError("invalid websocket accept")
reader=Reader(sock,initial)
send_frame(sock,1,json.dumps({{"op":"subscribe","args":[f"tickers.{{SYMBOL}}"]}},separators=(",",":")))
deadline=time.time()+10
while time.time()<deadline:
    opcode,data=recv_frame(reader)
    if opcode==9:
        send_frame(sock,10,data)
        continue
    if opcode==8:
        raise RuntimeError("websocket closed")
    if opcode!=1:
        continue
    msg=json.loads(data.decode())
    if msg.get("topic")!=f"tickers.{{SYMBOL}}":
        continue
    row=msg.get("data") or {{}}
    mark=row.get("markPrice")
    stamp=msg.get("ts")
    if mark in (None,"") or stamp in (None,""):
        continue
    payload={{"retCode":0,"time":stamp,"result":{{"category":"linear","list":[{{"symbol":SYMBOL,"markPrice":mark}}]}}}}
    print(json.dumps(payload,separators=(",",":")))
    send_frame(sock,8,b"")
    sock.close()
    break
else:
    raise RuntimeError("ticker snapshot timeout")
"""


class BybitPublicDisplayClient:
    """Use the canonical WSL Bybit lane on Windows and direct REST elsewhere."""

    def __init__(
        self,
        direct: BybitPublicClient,
        *,
        runner: Callable[..., subprocess.CompletedProcess[bytes]] = subprocess.run,
        windows: bool | None = None,
        wsl_executable: str | None = None,
        clock_ms: Callable[[], float] = lambda: time.time() * 1000.0,
    ) -> None:
        self.direct = direct
        self.runner = runner
        self.windows = os.name == "nt" if windows is None else windows
        self.wsl_executable = wsl_executable or _default_wsl_executable()
        self.clock_ms = clock_ms
        self.last_transport = "not_used"
        self.last_price_basis = "not_used"
        self.bases = direct.bases
        self.attempts = direct.attempts
        self.timeout = direct.timeout

    def _wsl_ws_ticker(self, symbol: str) -> dict[str, Any]:
        args = [
            self.wsl_executable,
            "-d",
            "Ubuntu",
            "--exec",
            "python3",
            "-",
        ]
        try:
            completed = self.runner(
                args,
                input=_wsl_ws_script(symbol).encode("utf-8"),
                capture_output=True,
                check=False,
                timeout=_WSL_WS_TIMEOUT_SECONDS,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except FileNotFoundError as exc:
            raise WSLBybitInfrastructureUnavailable("wsl.exe unavailable") from exc
        except subprocess.TimeoutExpired as exc:
            raise WSLBybitBridgeError("Bybit WSL WebSocket timeout") from exc
        if completed.returncode != 0:
            raise WSLBybitBridgeError(f"Bybit WSL WebSocket rc={completed.returncode}")
        raw = completed.stdout
        if not isinstance(raw, (bytes, bytearray)) or not 0 < len(raw) <= _MAX_STDOUT_BYTES:
            raise WSLBybitBridgeError("Bybit WSL WebSocket response_size")
        try:
            payload = json.loads(bytes(raw).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise WSLBybitBridgeError("Bybit WSL WebSocket json") from exc
        payload = _validate_payload(payload, symbol)
        if not _fresh(float(payload["time"]), self.clock_ms()):
            raise WSLBybitBridgeError("Bybit WSL WebSocket ticker stale")
        self.last_transport = "bybit_official_wsl_websocket"
        self.last_price_basis = "mark_price"
        return payload

    def _wsl_json(self, host: str, path: str, query: list[str]) -> dict[str, Any]:
        args = [
            self.wsl_executable,
            "-d",
            "Ubuntu",
            "--",
            "curl",
            "--fail",
            "--silent",
            "--show-error",
            "--connect-timeout",
            "3",
            "--max-time",
            "6",
            "--max-redirs",
            "0",
            "--proto",
            "=https",
            "--get",
        ]
        for item in query:
            args.extend(("--data-urlencode", item))
        args.append(f"{host}{path}")
        try:
            completed = self.runner(
                args,
                capture_output=True,
                check=False,
                timeout=_WSL_TIMEOUT_SECONDS,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except FileNotFoundError as exc:
            raise WSLBybitInfrastructureUnavailable("wsl.exe unavailable") from exc
        except subprocess.TimeoutExpired as exc:
            raise WSLBybitBridgeError(f"{host}{path}:timeout") from exc
        if completed.returncode != 0:
            raise WSLBybitBridgeError(f"{host}{path}:curl_{completed.returncode}")
        raw = completed.stdout
        if not isinstance(raw, (bytes, bytearray)) or not 0 < len(raw) <= _MAX_STDOUT_BYTES:
            raise WSLBybitBridgeError(f"{host}{path}:response_size")
        try:
            payload = json.loads(bytes(raw).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise WSLBybitBridgeError(f"{host}{path}:json") from exc
        if not isinstance(payload, dict):
            raise WSLBybitBridgeError(f"{host}{path}:shape")
        return payload

    def _wsl_get(self, symbol: str) -> dict[str, Any]:
        failures: list[str] = []
        try:
            return self._wsl_ws_ticker(symbol)
        except WSLBybitInfrastructureUnavailable:
            raise
        except WSLBybitBridgeError as exc:
            failures.append(str(exc))

        for host in _OFFICIAL_HOSTS:
            try:
                payload = _validate_payload(
                    self._wsl_json(host, _TICKER_PATH, ["category=linear", f"symbol={symbol}"]),
                    symbol,
                )
                if _fresh(float(payload["time"]), self.clock_ms()):
                    self.last_transport = "bybit_official_wsl_public"
                    self.last_price_basis = "mark_price"
                    return payload
                failures.append(f"{host}:ticker_stale")
            except WSLBybitInfrastructureUnavailable:
                raise
            except WSLBybitBridgeError as exc:
                failures.append(str(exc))

        for host in _OFFICIAL_HOSTS:
            try:
                payload = self._wsl_json(
                    host,
                    _ORDERBOOK_PATH,
                    ["category=linear", f"symbol={symbol}", "limit=1"],
                )
                midpoint, stamp = _validate_orderbook_payload(payload, symbol)
                if not _fresh(stamp, self.clock_ms()):
                    failures.append(f"{host}:orderbook_stale")
                    continue
                self.last_transport = "bybit_official_wsl_orderbook_mid"
                self.last_price_basis = "orderbook_mid"
                return {
                    "retCode": 0,
                    "time": int(stamp),
                    "result": {
                        "category": "linear",
                        "list": [{"symbol": symbol, "markPrice": format(midpoint, ".15g")}],
                    },
                }
            except WSLBybitInfrastructureUnavailable:
                raise
            except WSLBybitBridgeError as exc:
                failures.append(str(exc))
        raise WSLBybitBridgeError("WSL Bybit public price unavailable: " + ",".join(failures))

    def get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        symbol = _validate_request(path, params)
        if self.windows:
            try:
                return self._wsl_get(symbol)
            except WSLBybitInfrastructureUnavailable:
                # Portable Windows installs without WSL may still use the same
                # approved direct public Bybit client. A present WSL lane that
                # cannot obtain a fresh Bybit price fails closed instead.
                pass
        payload = self.direct.get(path, {"category": "linear", "symbol": symbol})
        self.last_transport = "bybit_official_windows_public" if self.windows else "bybit_official_public"
        self.last_price_basis = "mark_price"
        return _validate_payload(payload, symbol)
