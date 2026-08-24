"""Secure NEXUS browser gateway with one bounded AI Room control-plane endpoint.

All ordinary dashboard routes remain read-only. The only accepted POST route is
``/api/ai-room/message``. It never grants ambient mutation or trading authority: after
``evaluate_ai_action`` it may execute only the policy-approved, reversible, read-only
L3 ``mission-runner`` orchestration route. L2 paper actions remain staged behind the
deterministic Risk/Paper Execution path, and L4 remains owner-required.
"""
from __future__ import annotations

import argparse
import json
import mimetypes
import os
import ssl
from dataclasses import dataclass
from http import HTTPStatus
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable, Mapping
from urllib.parse import urlsplit

from ai_room import AIRoomError, evaluate_room_message, load_project_memory_snapshot
from web_dashboard import (
    DEFAULT_DATA_ROOT,
    ApiResponse,
    ByteResponse,
    GatewayConfig,
    ReportUnavailableError,
    build_handler as build_secure_handler,
    dispatch_get,
    gateway_disclosure,
    load_mission_control,
    validate_gateway_config,
    versioned,
)

UI_ROOT = Path(__file__).with_name("web_ui")
PROJECT_MEMORY_PATH = Path(__file__).with_name("docs") / "project_memory" / "STATE.json"
MAX_AI_REQUEST_BYTES = 16_384
STATIC_ROUTES = {
    "/": "index.html",
    "/ui/app.js": "app.js",
    "/ui/styles.css": "styles.css",
    "/ui/phase4.css": "phase4.css",
}
RUNTIME_BUNDLES = {
    "/ui/app.js": ("app.js", "ai_room.js"),
    "/ui/phase4.css": ("phase4.css", "ai_room.css"),
}


@dataclass(frozen=True)
class WebResponse:
    status: int
    body: bytes
    content_type: str


def _safe_file(root: Path, filename: str) -> Path:
    resolved_root = root.resolve(strict=True)
    target = (resolved_root / filename).resolve(strict=True)
    try:
        target.relative_to(resolved_root)
    except ValueError as exc:
        raise ReportUnavailableError("runtime asset escaped UI root") from exc
    if target.is_symlink() or not target.is_file():
        raise ReportUnavailableError("runtime asset is unsafe")
    return target


def load_runtime_asset(path: str, ui_root: Path = UI_ROOT) -> ByteResponse | None:
    names = RUNTIME_BUNDLES.get(path)
    if names is None:
        return None
    try:
        chunks = [_safe_file(ui_root, name).read_bytes() for name in names]
    except OSError as exc:
        raise ReportUnavailableError("runtime asset is unavailable") from exc
    body = b"\n".join(chunks)
    if len(body) > 1_000_000:
        raise ReportUnavailableError("runtime asset exceeds bounded size")
    content_type = "text/javascript; charset=utf-8" if path.endswith(".js") else "text/css; charset=utf-8"
    return ByteResponse(HTTPStatus.OK, body, content_type)


def dispatch(path_with_query: str, data_root: Path, ui_root: Path = UI_ROOT) -> WebResponse:
    """Compatibility GET dispatcher used by offline/unit callers; no write route lives here."""
    path = urlsplit(path_with_query).path
    if path.startswith("/api/") or path == "/health":
        response: ApiResponse = dispatch_get(path_with_query, data_root)
        return WebResponse(
            int(response.status),
            json.dumps(response.payload, sort_keys=True).encode(),
            "application/json; charset=utf-8",
        )
    filename = STATIC_ROUTES.get(path)
    if filename is None:
        return WebResponse(HTTPStatus.NOT_FOUND, b"Not found", "text/plain; charset=utf-8")
    try:
        body = (ui_root / filename).read_bytes()
    except OSError:
        return WebResponse(HTTPStatus.SERVICE_UNAVAILABLE, b"UI unavailable", "text/plain; charset=utf-8")
    return WebResponse(
        HTTPStatus.OK,
        body,
        mimetypes.guess_type(filename)[0] or "application/octet-stream",
    )


def dispatch_ai_post(
    path_with_query: str,
    payload: Mapping[str, Any],
    *,
    data_root: Path,
    project_memory_path: Path = PROJECT_MEMORY_PATH,
    config: GatewayConfig | None = None,
    evaluated_at: str | None = None,
    product_context: Mapping[str, Any] | None = None,
) -> ApiResponse:
    active_config = validate_gateway_config(config or GatewayConfig())
    parsed = urlsplit(path_with_query)
    if parsed.path != "/api/ai-room/message":
        return ApiResponse(
            HTTPStatus.METHOD_NOT_ALLOWED,
            versioned({
                "error": "method_not_allowed",
                "allowed": ["GET", "HEAD"],
                "gateway": gateway_disclosure(active_config),
            }),
            (("Allow", "GET, HEAD"),),
        )
    if parsed.query:
        return ApiResponse(
            HTTPStatus.BAD_REQUEST,
            versioned({"error": "invalid_query", "gateway": gateway_disclosure(active_config)}),
        )
    try:
        project_memory = load_project_memory_snapshot(project_memory_path)
    except AIRoomError as exc:
        return ApiResponse(
            HTTPStatus.SERVICE_UNAVAILABLE,
            versioned({
                "error": "ai_context_unavailable",
                "detail": str(exc),
                "gateway": gateway_disclosure(active_config),
            }),
        )
    try:
        mission_control = load_mission_control(data_root)["mission_control"]
    except (ReportUnavailableError, OSError, KeyError, TypeError):
        mission_control = None
    try:
        result = evaluate_room_message(
            payload,
            project_memory_snapshot=project_memory,
            mission_control=mission_control,
            product_context=product_context,
            evaluated_at=evaluated_at,
        )
    except AIRoomError as exc:
        return ApiResponse(
            HTTPStatus.BAD_REQUEST,
            versioned({
                "error": "invalid_ai_room_request",
                "detail": str(exc),
                "gateway": gateway_disclosure(active_config),
            }),
        )
    return ApiResponse(
        HTTPStatus.OK,
        versioned({"ai_room": result, "gateway": gateway_disclosure(active_config)}),
    )


def build_handler(
    data_root: Path,
    ui_root: Path = UI_ROOT,
    *,
    config: GatewayConfig | None = None,
    project_memory_path: Path = PROJECT_MEMORY_PATH,
    product_context_provider: Callable[[], Mapping[str, Any]] | None = None,
):
    active_config = validate_gateway_config(config or GatewayConfig())
    BaseHandler = build_secure_handler(data_root, config=active_config, ui_root=ui_root)

    class Handler(BaseHandler):
        def _runtime_read(self, *, head_only: bool = False) -> bool:
            parsed = urlsplit(self.path)
            if parsed.path not in RUNTIME_BUNDLES:
                return False
            if not self._authorized():
                return True
            if parsed.query:
                self._send(
                    ApiResponse(
                        HTTPStatus.BAD_REQUEST,
                        versioned({"error": "invalid_query", "gateway": gateway_disclosure(active_config)}),
                    ),
                    head_only=head_only,
                )
                return True
            try:
                response = load_runtime_asset(parsed.path, ui_root)
            except (OSError, ReportUnavailableError) as exc:
                self._send(
                    ApiResponse(
                        HTTPStatus.SERVICE_UNAVAILABLE,
                        versioned({
                            "error": "static_asset_unavailable",
                            "detail": str(exc),
                            "gateway": gateway_disclosure(active_config),
                        }),
                    ),
                    head_only=head_only,
                )
                return True
            if response is None:
                return False
            self._send(response, head_only=head_only)
            return True

        def do_GET(self) -> None:  # noqa: N802
            if not self._runtime_read():
                super().do_GET()

        def do_HEAD(self) -> None:  # noqa: N802
            if not self._runtime_read(head_only=True):
                super().do_HEAD()

        def do_POST(self) -> None:  # noqa: N802
            parsed = urlsplit(self.path)
            if parsed.path != "/api/ai-room/message":
                super().do_POST()
                return
            if not self._authorized():
                return
            if parsed.query:
                self._send(ApiResponse(
                    HTTPStatus.BAD_REQUEST,
                    versioned({"error": "invalid_query", "gateway": gateway_disclosure(active_config)}),
                ))
                return
            if self.headers.get("Transfer-Encoding"):
                self._send(ApiResponse(
                    HTTPStatus.BAD_REQUEST,
                    versioned({"error": "transfer_encoding_denied", "gateway": gateway_disclosure(active_config)}),
                ))
                return
            content_type = self.headers.get("Content-Type", "").split(";", 1)[0].strip().casefold()
            if content_type != "application/json":
                self._send(ApiResponse(
                    HTTPStatus.UNSUPPORTED_MEDIA_TYPE,
                    versioned({"error": "json_required", "gateway": gateway_disclosure(active_config)}),
                ))
                return
            raw_length = self.headers.get("Content-Length", "")
            if not raw_length.isascii() or not raw_length.isdigit():
                self._send(ApiResponse(
                    HTTPStatus.LENGTH_REQUIRED,
                    versioned({"error": "content_length_required", "gateway": gateway_disclosure(active_config)}),
                ))
                return
            length = int(raw_length)
            if length < 2 or length > MAX_AI_REQUEST_BYTES:
                self._send(ApiResponse(
                    HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
                    versioned({"error": "request_body_out_of_bounds", "gateway": gateway_disclosure(active_config)}),
                ))
                return
            raw = self.rfile.read(length)
            try:
                payload = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                self._send(ApiResponse(
                    HTTPStatus.BAD_REQUEST,
                    versioned({"error": "invalid_json", "gateway": gateway_disclosure(active_config)}),
                ))
                return
            if not isinstance(payload, Mapping):
                self._send(ApiResponse(
                    HTTPStatus.BAD_REQUEST,
                    versioned({"error": "invalid_ai_room_request", "gateway": gateway_disclosure(active_config)}),
                ))
                return
            product_context = None
            if product_context_provider is not None:
                try:
                    product_context = product_context_provider()
                except Exception:
                    product_context = None
            self._send(dispatch_ai_post(
                self.path,
                payload,
                data_root=data_root,
                project_memory_path=project_memory_path,
                config=active_config,
                product_context=product_context,
            ))

    return Handler


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
    ui_root: Path = UI_ROOT,
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
    server = ThreadingHTTPServer(
        (host, port),
        build_handler(data_root, ui_root, config=config),
    )
    if tls_cert is not None:
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.load_cert_chain(certfile=str(tls_cert), keyfile=str(tls_key) if tls_key else None)
        server.socket = context.wrap_socket(server.socket, server_side=True)
    scheme = "https" if tls_cert is not None else "http"
    print(f"NEXUS gateway available at {scheme}://{host}:{port} ({mode} mode)")
    server.serve_forever()


def _csv_env(name: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in os.environ.get(name, "").split(",") if item.strip())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default=os.environ.get("NEXUS_GATEWAY_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("NEXUS_GATEWAY_PORT", "8000")))
    parser.add_argument("--mode", choices=("local", "remote"), default=os.environ.get("NEXUS_GATEWAY_MODE", "local"))
    parser.add_argument("--data-root", type=Path, default=DEFAULT_DATA_ROOT)
    parser.add_argument("--ui-root", type=Path, default=UI_ROOT)
    parser.add_argument("--tls-cert", type=Path, default=Path(os.environ["NEXUS_GATEWAY_TLS_CERT"]) if os.environ.get("NEXUS_GATEWAY_TLS_CERT") else None)
    parser.add_argument("--tls-key", type=Path, default=Path(os.environ["NEXUS_GATEWAY_TLS_KEY"]) if os.environ.get("NEXUS_GATEWAY_TLS_KEY") else None)
    args = parser.parse_args()
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
