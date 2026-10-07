"""Bounded Bybit-only public ticker bridge for the Windows Product UI.

On the owner Windows laptop the canonical Bybit network lane is WSL. This
module never accepts arbitrary URLs, credentials, order paths, or private API
headers. It only fetches the public linear ticker and returns the native Bybit
payload for the existing shared-Paper display validator.
"""
from __future__ import annotations

import json
import math
import os
import re
import subprocess
from pathlib import Path
from typing import Any, Callable

from bybit_derivatives_core_v1 import Client as BybitPublicClient, ValidationError

_TICKER_PATH = "/v5/market/tickers"
_OFFICIAL_HOSTS = ("https://api.bytick.com", "https://api.bybit.com")
_SYMBOL_RE = re.compile(r"^[A-Z0-9]{3,32}$")
_MAX_STDOUT_BYTES = 200_000
_WSL_TIMEOUT_SECONDS = 7.0


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
    symbol = str(params.get("symbol", "")).strip().upper()
    if not _SYMBOL_RE.fullmatch(symbol):
        raise WSLBybitBridgeError("unsupported Bybit symbol")
    return symbol


def _validate_payload(payload: Any, symbol: str) -> dict[str, Any]:
    if not isinstance(payload, dict) or payload.get("retCode") != 0:
        raise WSLBybitBridgeError("invalid Bybit public ticker response")
    result = payload.get("result")
    rows = result.get("list") if isinstance(result, dict) else None
    if result is None or result.get("category") != "linear" or not isinstance(rows, list) or len(rows) != 1:
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


class BybitPublicDisplayClient:
    """Use the canonical WSL Bybit lane on Windows and direct REST elsewhere."""

    def __init__(
        self,
        direct: BybitPublicClient,
        *,
        runner: Callable[..., subprocess.CompletedProcess[bytes]] = subprocess.run,
        windows: bool | None = None,
        wsl_executable: str | None = None,
    ) -> None:
        self.direct = direct
        self.runner = runner
        self.windows = os.name == "nt" if windows is None else windows
        self.wsl_executable = wsl_executable or _default_wsl_executable()
        self.last_transport = "not_used"
        self.bases = direct.bases
        self.attempts = direct.attempts
        self.timeout = direct.timeout

    def _wsl_get(self, symbol: str) -> dict[str, Any]:
        infrastructure_seen = False
        failures: list[str] = []
        for host in _OFFICIAL_HOSTS:
            url = f"{host}{_TICKER_PATH}?category=linear&symbol={symbol}"
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
                url,
            ]
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
            except subprocess.TimeoutExpired:
                infrastructure_seen = True
                failures.append(f"{host}:timeout")
                continue
            infrastructure_seen = True
            if completed.returncode != 0:
                failures.append(f"{host}:curl_{completed.returncode}")
                continue
            raw = completed.stdout
            if not isinstance(raw, (bytes, bytearray)) or not 0 < len(raw) <= _MAX_STDOUT_BYTES:
                failures.append(f"{host}:response_size")
                continue
            try:
                payload = json.loads(bytes(raw).decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                failures.append(f"{host}:json")
                continue
            validated = _validate_payload(payload, symbol)
            self.last_transport = "bybit_official_wsl_public"
            return validated
        if not infrastructure_seen:
            raise WSLBybitInfrastructureUnavailable("WSL Bybit bridge unavailable")
        raise WSLBybitBridgeError("WSL Bybit public ticker unavailable: " + ",".join(failures))

    def get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        symbol = _validate_request(path, params)
        if self.windows:
            try:
                return self._wsl_get(symbol)
            except WSLBybitInfrastructureUnavailable:
                # Portable Windows installs without WSL may still use the same
                # approved direct public Bybit client. Network failures inside
                # a present WSL fail closed instead of silently changing venue.
                pass
        payload = self.direct.get(path, {"category": "linear", "symbol": symbol})
        self.last_transport = "bybit_official_windows_public" if self.windows else "bybit_official_public"
        return _validate_payload(payload, symbol)
