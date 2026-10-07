"""Bounded Bybit-only public-price bridge for the Windows Product UI.

On the owner Windows laptop the canonical Bybit network lane is WSL. This
module never accepts arbitrary URLs, credentials, order paths, or private API
headers. It prefers the official linear ticker mark; if that response is stale,
it may use a fresh official Bybit order-book midpoint for display-only PnL.
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
