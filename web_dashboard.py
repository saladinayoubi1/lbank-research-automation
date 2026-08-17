"""Fail-closed read-only NEXUS dashboard gateway.

Local mode is loopback-only. Remote mode is explicit, TLS-only, bearer-authenticated,
and exact-host/origin allowlisted. The gateway exposes generated read-only reports
and allowlisted static UI assets; it never calls exchanges or exposes secrets.
"""
from __future__ import annotations

import argparse
import csv
import hmac
import ipaddress
import json
import mimetypes
import os
import ssl
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import parse_qs, urlsplit

from dashboard_integrations import (
    IntegrationUnavailableError,
    load_research_summary,
    load_zotero_summary,
)

DEFAULT_DATA_ROOT = Path("data/market")
DEFAULT_UI_ROOT = Path("web_ui")
SUMMARY_FILENAME = "_data_readiness.json"
SERIES_FILENAME = "_data_readiness.csv"
MISSION_CONTROL_FILENAME = "_mission_control.json"
MISSION_CONTROL_CONTRACT_VERSION = "nexus.mission-control.read.v1"
API_CONTRACT_VERSION = "nexus.dashboard.read.v1"
GATEWAY_CONTRACT_VERSION = "nexus.gateway.v1"
MAX_REPORT_BYTES = 1_000_000
MAX_RESPONSE_BYTES = 1_000_000
MAX_REQUEST_TARGET_BYTES = 4096
MAX_QUERY_VALUE_CHARS = 160
MAX_SERIES_LIMIT = 200
MAX_SERIES_OFFSET = 100_000
DEFAULT_SERIES_LIMIT = 100
STATIC_ALLOWLIST = {
    "/": "index.html",
    "/ui/index.html": "index.html",
    "/ui/app.js": "app.js",
    "/ui/styles.css": "styles.css",
    "/ui/phase4.css": "phase4.css",
}
SECURITY_HEADERS = {
    "Cache-Control": "no-store",
    "Pragma": "no-cache",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=(), usb=()",
    "Cross-Origin-Resource-Policy": "same-origin",
    "Content-Security-Policy": "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'",
}


class ReportUnavailableError(RuntimeError):
    """Raised when a generated dashboard report cannot be safely served."""


class GatewayConfigurationError(ValueError):
    """Raised when gateway access settings are unsafe or ambiguous."""


@dataclass(frozen=True)
class ApiResponse:
    status: int
    payload: dict[str, Any]
    headers: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class ByteResponse:
    status: int
    body: bytes
    content_type: str
    headers: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class GatewayConfig:
    mode: str = "local"
    host: str = "127.0.0.1"
    port: int = 8000
    allowed_hosts: tuple[str, ...] = ()
    allowed_origins: tuple[str, ...] = ()
    access_token: str | None = None
    tls_cert: Path | None = None
    tls_key: Path | None = None
    rate_limit: int = 120
    rate_window_seconds: int = 60
    max_response_bytes: int = MAX_RESPONSE_BYTES
    max_request_target_bytes: int = MAX_REQUEST_TARGET_BYTES

    @property
    def remote_access_enabled(self) -> bool:
        return self.mode == "remote"

    @property
    def auth_required(self) -> bool:
        return self.mode == "remote"


class RateLimiter:
    """Small bounded in-memory fixed-window-equivalent limiter for gateway requests."""

    def __init__(self, limit: int, window_seconds: int) -> None:
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
            raise GatewayConfigurationError("rate limit must be a positive integer")
        if isinstance(window_seconds, bool) or not isinstance(window_seconds, int) or window_seconds < 1:
            raise GatewayConfigurationError("rate window must be a positive integer")
        self.limit = limit
        self.window_seconds = window_seconds
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.RLock()

    def allow(self, principal: str, now: float | None = None) -> tuple[bool, int]:
        current = time.monotonic() if now is None else float(now)
        cutoff = current - self.window_seconds
        with self._lock:
            hits = self._hits[principal]
            while hits and hits[0] <= cutoff:
                hits.popleft()
            if len(hits) >= self.limit:
                retry = max(1, int(self.window_seconds - (current - hits[0])) + 1)
                return False, retry
            hits.append(current)
            # Bound principal cardinality from long-dead entries.
            if len(self._hits) > 4096:
                stale = [key for key, values in self._hits.items() if not values or values[-1] <= cutoff]
                for key in stale[:2048]:
                    self._hits.pop(key, None)
            return True, 0


def _loopback_host(host: str) -> bool:
    if host.casefold() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _default_local_hosts(port: int) -> tuple[str, ...]:
    return (
        "localhost",
        f"localhost:{port}",
        "127.0.0.1",
        f"127.0.0.1:{port}",
        "[::1]",
        f"[::1]:{port}",
    )


def _default_local_origins(port: int) -> tuple[str, ...]:
    return (
        f"http://localhost:{port}",
        f"http://127.0.0.1:{port}",
        f"http://[::1]:{port}",
    )


def validate_gateway_config(config: GatewayConfig) -> GatewayConfig:
    if config.mode not in {"local", "remote"}:
        raise GatewayConfigurationError("gateway mode must be local or remote")
    if isinstance(config.port, bool) or not isinstance(config.port, int) or not (1 <= config.port <= 65535):
        raise GatewayConfigurationError("gateway port is invalid")
    if config.rate_limit < 1 or config.rate_window_seconds < 1:
        raise GatewayConfigurationError("gateway rate limit is invalid")
    if config.max_response_bytes < 1024 or config.max_request_target_bytes < 256:
        raise GatewayConfigurationError("gateway size bounds are invalid")

    if config.mode == "local":
        if not _loopback_host(config.host):
            raise GatewayConfigurationError("local gateway must bind loopback only")
        if config.access_token is not None:
            raise GatewayConfigurationError("local mode does not accept a bearer token")
        if config.tls_key is not None and config.tls_cert is None:
            raise GatewayConfigurationError("TLS key requires TLS certificate")
    else:
        if not isinstance(config.access_token, str) or len(config.access_token) < 32:
            raise GatewayConfigurationError("remote gateway requires a strong runtime bearer token")
        if config.tls_cert is None or config.tls_key is None:
            raise GatewayConfigurationError("remote gateway requires TLS certificate and key")
        if not config.allowed_hosts:
            raise GatewayConfigurationError("remote gateway requires exact allowed hosts")
        if not config.allowed_origins:
            raise GatewayConfigurationError("remote gateway requires exact allowed origins")
        if any("*" in value for value in (*config.allowed_hosts, *config.allowed_origins)):
            raise GatewayConfigurationError("wildcards are forbidden in remote access allowlists")
        for origin in config.allowed_origins:
            parsed = urlsplit(origin)
            if parsed.scheme != "https" or not parsed.netloc or parsed.path not in {"", "/"}:
                raise GatewayConfigurationError("remote origins must be exact HTTPS origins")
    return config


def effective_hosts(config: GatewayConfig) -> tuple[str, ...]:
    return config.allowed_hosts or _default_local_hosts(config.port)


def effective_origins(config: GatewayConfig) -> tuple[str, ...]:
    return config.allowed_origins or _default_local_origins(config.port)


def _access_error(status: int, code: str, config: GatewayConfig, **extra: Any) -> ApiResponse:
    return ApiResponse(
        status,
        versioned({
            "error": code,
            "gateway": gateway_disclosure(config),
            **extra,
        }),
    )


def gateway_disclosure(config: GatewayConfig) -> dict[str, Any]:
    return {
        "contract_version": GATEWAY_CONTRACT_VERSION,
        "access_mode": config.mode,
        "remote_access_enabled": config.remote_access_enabled,
        "auth_required": config.auth_required,
        "read_only": True,
    }


def authorize_request(
    config: GatewayConfig,
    *,
    headers: Mapping[str, str],
    client_ip: str,
) -> ApiResponse | None:
    validate_gateway_config(config)
    host = headers.get("Host", "")
    if host not in effective_hosts(config):
        return _access_error(HTTPStatus.BAD_REQUEST, "invalid_host", config)

    try:
        client = ipaddress.ip_address(client_ip)
    except ValueError:
        return _access_error(HTTPStatus.FORBIDDEN, "invalid_client_address", config)
    if config.mode == "local" and not client.is_loopback:
        return _access_error(HTTPStatus.FORBIDDEN, "non_loopback_client", config)

    origin = headers.get("Origin")
    if origin and origin not in effective_origins(config):
        return _access_error(HTTPStatus.FORBIDDEN, "origin_denied", config)

    if config.mode == "remote":
        auth = headers.get("Authorization", "")
        prefix = "Bearer "
        supplied = auth[len(prefix):] if auth.startswith(prefix) else ""
        expected = config.access_token or ""
        if not supplied or not hmac.compare_digest(supplied.encode("utf-8"), expected.encode("utf-8")):
            return _access_error(HTTPStatus.UNAUTHORIZED, "authentication_required", config)
    return None


def versioned(payload: dict[str, Any]) -> dict[str, Any]:
    """Attach the immutable read-only dashboard contract version."""
    return {"contract_version": API_CONTRACT_VERSION, **payload}


def _report_metadata(path: Path) -> dict[str, Any]:
    stat = path.stat()
    return {"source": path.name, "generated_report_mtime_ns": stat.st_mtime_ns, "stale_possible": True}


def _read_json_report(path: Path, name: str) -> dict[str, Any]:
    try:
        stat = path.stat()
        if stat.st_size > MAX_REPORT_BYTES:
            raise ReportUnavailableError(f"report exceeds bounded size: {name}")
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ReportUnavailableError(f"missing report: {name}") from exc
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ReportUnavailableError(f"invalid report: {name}") from exc
    if not isinstance(payload, dict):
        raise ReportUnavailableError(f"invalid report root: {name}")
    return payload


def load_summary(data_root: Path) -> dict[str, Any]:
    path = data_root / SUMMARY_FILENAME
    return {"summary": _read_json_report(path, SUMMARY_FILENAME), "metadata": _report_metadata(path)}


def load_series(
    data_root: Path,
    *,
    symbol: str | None = None,
    timeframe: str | None = None,
    limit: int = DEFAULT_SERIES_LIMIT,
    offset: int = 0,
) -> dict[str, Any]:
    path = data_root / SERIES_FILENAME
    try:
        if path.stat().st_size > MAX_REPORT_BYTES:
            raise ReportUnavailableError(f"report exceeds bounded size: {SERIES_FILENAME}")
        with path.open("r", encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
    except FileNotFoundError as exc:
        raise ReportUnavailableError(f"missing report: {SERIES_FILENAME}") from exc
    except (OSError, UnicodeError, csv.Error) as exc:
        raise ReportUnavailableError(f"invalid report: {SERIES_FILENAME}") from exc
    if symbol is not None:
        rows = [row for row in rows if row.get("symbol") == symbol]
    if timeframe is not None:
        rows = [row for row in rows if row.get("timeframe") == timeframe]
    total = len(rows)
    page = rows[offset: offset + limit]
    next_offset = offset + limit if offset + limit < total else None
    return {
        "series": page,
        "count": len(page),
        "total": total,
        "filters": {"symbol": symbol, "timeframe": timeframe},
        "pagination": {"limit": limit, "offset": offset, "total": total, "next_offset": next_offset},
        "metadata": _report_metadata(path),
    }


def load_mission_control(data_root: Path) -> dict[str, Any]:
    path = data_root.parent / "mission_control" / MISSION_CONTROL_FILENAME
    payload = _read_json_report(path, MISSION_CONTROL_FILENAME)
    if payload.get("contract_version") != MISSION_CONTROL_CONTRACT_VERSION:
        raise ReportUnavailableError("incompatible Mission Control report contract")
    required = {"mission", "queue", "agents", "runners", "local_node", "data", "providers", "paper", "circuits", "limits", "notifications"}
    if not required.issubset(payload):
        raise ReportUnavailableError("incomplete Mission Control report")
    return {"mission_control": payload, "metadata": _report_metadata(path)}


def _parse_single_query(query: Mapping[str, list[str]], key: str) -> str | None:
    values = query.get(key)
    if values is None:
        return None
    if len(values) != 1 or len(values[0]) > MAX_QUERY_VALUE_CHARS:
        raise ValueError(f"invalid query parameter: {key}")
    return values[0]


def _bounded_int_query(query: Mapping[str, list[str]], key: str, default: int, maximum: int) -> int:
    value = _parse_single_query(query, key)
    if value is None:
        return default
    if not value.isascii() or not value.isdigit():
        raise ValueError(f"invalid query parameter: {key}")
    parsed = int(value)
    if parsed < 0 or parsed > maximum:
        raise ValueError(f"query parameter out of range: {key}")
    return parsed


def _validated_query(parsed_path: Any) -> dict[str, Any]:
    if not parsed_path.query:
        return {"symbol": None, "timeframe": None, "limit": DEFAULT_SERIES_LIMIT, "offset": 0}
    if parsed_path.path != "/api/readiness/series":
        raise ValueError("query parameters are not allowed on this route")
    query = parse_qs(parsed_path.query, keep_blank_values=True, strict_parsing=True, max_num_fields=8)
    allowed = {"symbol", "timeframe", "limit", "offset"}
    if set(query) - allowed:
        raise ValueError("unknown query parameter")
    symbol = _parse_single_query(query, "symbol")
    timeframe = _parse_single_query(query, "timeframe")
    if symbol == "" or timeframe == "":
        raise ValueError("empty filters are not allowed")
    limit = _bounded_int_query(query, "limit", DEFAULT_SERIES_LIMIT, MAX_SERIES_LIMIT)
    if limit < 1:
        raise ValueError("limit must be at least one")
    offset = _bounded_int_query(query, "offset", 0, MAX_SERIES_OFFSET)
    return {"symbol": symbol, "timeframe": timeframe, "limit": limit, "offset": offset}


def dispatch_get(
    path_with_query: str,
    data_root: Path = DEFAULT_DATA_ROOT,
    config: GatewayConfig | None = None,
) -> ApiResponse:
    config = validate_gateway_config(config or GatewayConfig())
    if len(path_with_query.encode("utf-8")) > config.max_request_target_bytes:
        return _access_error(HTTPStatus.REQUEST_URI_TOO_LONG, "request_target_too_long", config)
    try:
        parsed = urlsplit(path_with_query)
        query = _validated_query(parsed)
    except (ValueError, UnicodeError) as exc:
        return _access_error(HTTPStatus.BAD_REQUEST, "invalid_query", config, detail=str(exc))
    integration_root = data_root.parent / "integrations"

    if parsed.path == "/health":
        return ApiResponse(HTTPStatus.OK, versioned({
            "status": "ok",
            "service": "lbank-research-readiness-dashboard",
            "mode": "read-only",
            "gateway": gateway_disclosure(config),
        }))

    try:
        if parsed.path == "/api/readiness/summary":
            return ApiResponse(HTTPStatus.OK, versioned({**load_summary(data_root), "gateway": gateway_disclosure(config)}))
        if parsed.path == "/api/readiness/series":
            return ApiResponse(HTTPStatus.OK, versioned({
                **load_series(data_root, **query),
                "gateway": gateway_disclosure(config),
            }))
        if parsed.path == "/api/mission-control":
            return ApiResponse(HTTPStatus.OK, versioned({**load_mission_control(data_root), "gateway": gateway_disclosure(config)}))
        if parsed.path == "/api/integrations/zotero":
            return ApiResponse(HTTPStatus.OK, versioned({
                "summary": load_zotero_summary(integration_root),
                "gateway": gateway_disclosure(config),
            }))
        if parsed.path == "/api/integrations/research":
            return ApiResponse(HTTPStatus.OK, versioned({
                "summary": load_research_summary(integration_root),
                "gateway": gateway_disclosure(config),
            }))
    except (ReportUnavailableError, IntegrationUnavailableError) as exc:
        return _access_error(HTTPStatus.SERVICE_UNAVAILABLE, "report_unavailable", config, detail=str(exc))

    return _access_error(HTTPStatus.NOT_FOUND, "not_found", config, path=parsed.path)


def load_static_asset(path: str, ui_root: Path = DEFAULT_UI_ROOT) -> ByteResponse | None:
    filename = STATIC_ALLOWLIST.get(path)
    if filename is None:
        return None
    root = ui_root.resolve(strict=True)
    target = (root / filename).resolve(strict=True)
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise ReportUnavailableError("static asset escaped UI root") from exc
    if target.is_symlink() or not target.is_file() or target.stat().st_size > MAX_RESPONSE_BYTES:
        raise ReportUnavailableError("static asset is unsafe or oversized")
    body = target.read_bytes()
    content_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
    if target.suffix == ".js":
        content_type = "text/javascript; charset=utf-8"
    elif target.suffix == ".css":
        content_type = "text/css; charset=utf-8"
    elif target.suffix == ".html":
        content_type = "text/html; charset=utf-8"
    return ByteResponse(HTTPStatus.OK, body, content_type)


def _safe_headers(origin: str | None = None) -> tuple[tuple[str, str], ...]:
    headers = list(SECURITY_HEADERS.items())
    if origin:
        headers.extend((("Access-Control-Allow-Origin", origin), ("Vary", "Origin")))
    return tuple(headers)


def build_handler(
    data_root: Path,
    *,
    config: GatewayConfig | None = None,
    ui_root: Path = DEFAULT_UI_ROOT,
    limiter: RateLimiter | None = None,
):
    config = validate_gateway_config(config or GatewayConfig())
    limiter = limiter or RateLimiter(config.rate_limit, config.rate_window_seconds)

    class DashboardHandler(BaseHTTPRequestHandler):
        server_version = "NEXUSGateway/1"
        sys_version = ""

        def _send(self, response: ApiResponse | ByteResponse, *, head_only: bool = False) -> None:
            origin = self.headers.get("Origin")
            if isinstance(response, ApiResponse):
                body = json.dumps(response.payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
                content_type = "application/json; charset=utf-8"
            else:
                body = response.body
                content_type = response.content_type
            if len(body) > config.max_response_bytes:
                payload = versioned({"error": "response_too_large", "gateway": gateway_disclosure(config)})
                body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
                response = ApiResponse(HTTPStatus.SERVICE_UNAVAILABLE, payload)
                content_type = "application/json; charset=utf-8"
            self.send_response(int(response.status))
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            for key, value in _safe_headers(origin if origin in effective_origins(config) else None):
                self.send_header(key, value)
            for key, value in response.headers:
                self.send_header(key, value)
            self.end_headers()
            if not head_only:
                self.wfile.write(body)

        def _authorized(self) -> bool:
            error = authorize_request(config, headers=self.headers, client_ip=self.client_address[0])
            if error is not None:
                self._send(error)
                return False
            principal = self.client_address[0]
            if config.mode == "remote":
                principal = "remote:" + _digest(self.headers.get("Authorization", ""))[:16]
            allowed, retry_after = limiter.allow(principal)
            if not allowed:
                self._send(_access_error(
                    HTTPStatus.TOO_MANY_REQUESTS,
                    "rate_limited",
                    config,
                ).__class__(
                    HTTPStatus.TOO_MANY_REQUESTS,
                    versioned({"error": "rate_limited", "gateway": gateway_disclosure(config)}),
                    (("Retry-After", str(retry_after)),),
                ))
                return False
            return True

        def _read(self, *, head_only: bool = False) -> None:
            if not self._authorized():
                return
            if len(self.path.encode("utf-8")) > config.max_request_target_bytes:
                self._send(_access_error(HTTPStatus.REQUEST_URI_TOO_LONG, "request_target_too_long", config), head_only=head_only)
                return
            parsed = urlsplit(self.path)
            if parsed.path in STATIC_ALLOWLIST:
                if parsed.query:
                    self._send(_access_error(HTTPStatus.BAD_REQUEST, "invalid_query", config), head_only=head_only)
                    return
                try:
                    response = load_static_asset(parsed.path, ui_root)
                except (OSError, ReportUnavailableError) as exc:
                    self._send(_access_error(HTTPStatus.SERVICE_UNAVAILABLE, "static_asset_unavailable", config, detail=str(exc)), head_only=head_only)
                    return
                if response is None:
                    self._send(_access_error(HTTPStatus.NOT_FOUND, "not_found", config, path=parsed.path), head_only=head_only)
                else:
                    self._send(response, head_only=head_only)
                return
            self._send(dispatch_get(self.path, data_root, config), head_only=head_only)

        def do_GET(self) -> None:  # noqa: N802
            self._read()

        def do_HEAD(self) -> None:  # noqa: N802
            self._read(head_only=True)

        def _method_denied(self) -> None:
            if not self._authorized():
                return
            self._send(ApiResponse(
                HTTPStatus.METHOD_NOT_ALLOWED,
                versioned({"error": "method_not_allowed", "allowed": ["GET", "HEAD"], "gateway": gateway_disclosure(config)}),
                (("Allow", "GET, HEAD"),),
            ))

        def do_POST(self) -> None:  # noqa: N802
            self._method_denied()

        def do_PUT(self) -> None:  # noqa: N802
            self._method_denied()

        def do_PATCH(self) -> None:  # noqa: N802
            self._method_denied()

        def do_DELETE(self) -> None:  # noqa: N802
            self._method_denied()

        def do_OPTIONS(self) -> None:  # noqa: N802
            self._method_denied()

        def log_message(self, format: str, *args: object) -> None:
            # Access logs are intentionally disabled so bearer material/query values cannot leak.
            return

    return DashboardHandler


def serve(
    host: str,
    port: int,
    data_root: Path,
    *,
    mode: str = "local",
    allowed_hosts: tuple[str, ...] = (),
    allowed_origins: tuple[str, ...] = (),
    access_token: str | None = None,
    tls_cert: Path | None = None,
    tls_key: Path | None = None,
    ui_root: Path = DEFAULT_UI_ROOT,
) -> None:
    config = validate_gateway_config(GatewayConfig(
        mode=mode,
        host=host,
        port=port,
        allowed_hosts=allowed_hosts,
        allowed_origins=allowed_origins,
        access_token=access_token,
        tls_cert=tls_cert,
        tls_key=tls_key,
    ))
    server = ThreadingHTTPServer((host, port), build_handler(data_root, config=config, ui_root=ui_root))
    if tls_cert is not None:
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.load_cert_chain(certfile=str(tls_cert), keyfile=str(tls_key) if tls_key else None)
        server.socket = context.wrap_socket(server.socket, server_side=True)
    scheme = "https" if tls_cert is not None else "http"
    print(f"NEXUS read-only gateway listening on {scheme}://{host}:{port} ({mode} mode)")
    print(f"Serving generated reports from {data_root.resolve()}")
    server.serve_forever()


def _csv_env(name: str) -> tuple[str, ...]:
    value = os.environ.get(name, "")
    return tuple(item.strip() for item in value.split(",") if item.strip())


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default=os.environ.get("NEXUS_GATEWAY_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("NEXUS_GATEWAY_PORT", "8000")))
    parser.add_argument("--mode", choices=("local", "remote"), default=os.environ.get("NEXUS_GATEWAY_MODE", "local"))
    parser.add_argument("--data-root", type=Path, default=DEFAULT_DATA_ROOT)
    parser.add_argument("--ui-root", type=Path, default=DEFAULT_UI_ROOT)
    parser.add_argument("--tls-cert", type=Path, default=Path(os.environ["NEXUS_GATEWAY_TLS_CERT"]) if os.environ.get("NEXUS_GATEWAY_TLS_CERT") else None)
    parser.add_argument("--tls-key", type=Path, default=Path(os.environ["NEXUS_GATEWAY_TLS_KEY"]) if os.environ.get("NEXUS_GATEWAY_TLS_KEY") else None)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    serve(
        args.host,
        args.port,
        args.data_root,
        mode=args.mode,
        allowed_hosts=_csv_env("NEXUS_GATEWAY_ALLOWED_HOSTS"),
        allowed_origins=_csv_env("NEXUS_GATEWAY_ALLOWED_ORIGINS"),
        access_token=os.environ.get("NEXUS_GATEWAY_TOKEN"),
        tls_cert=args.tls_cert,
        tls_key=args.tls_key,
        ui_root=args.ui_root,
    )


if __name__ == "__main__":
    main()
