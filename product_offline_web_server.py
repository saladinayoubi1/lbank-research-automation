from __future__ import annotations

import argparse
import json
import os
from http import HTTPStatus
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlsplit

from product_control_runtime import ProductControlRuntime
from product_mission_runtime import ProductMissionError, ProductMissionRuntime
from product_offline_runtime import (
    MAX_OFFLINE_DATASET_BYTES,
    CachingProductResearchRuntime,
    OfflineDatasetStore,
    OfflineProductResearchRuntime,
    ProductOfflineError,
)
from product_research_runtime import ProductResearchError, ProductResearchRuntime
from product_runtime import ProductRuntime
from product_web_server import PRODUCT_UI_ROOT, _json_error, _safe_asset, build_handler as build_product_handler
from web_dashboard import ApiResponse, ByteResponse, GatewayConfig, validate_gateway_config

DEFAULT_DATA_ROOT = Path("data/market")
MAX_OFFLINE_REQUEST_BYTES = MAX_OFFLINE_DATASET_BYTES + 65_536
OFFLINE_STATIC = {
    "/ui/product-offline.js": "product-offline.js",
    "/ui/product-offline.css": "product-offline.css",
    "/ui/product-mission.js": "product-mission.js",
    "/ui/product-mission.css": "product-mission.css",
}


def build_handler(
    data_root: Path,
    *,
    config: GatewayConfig | None = None,
    ui_root: Path = PRODUCT_UI_ROOT,
    runtime: ProductRuntime | None = None,
    online_research: ProductResearchRuntime | None = None,
    controls: ProductControlRuntime | None = None,
    store: OfflineDatasetStore | None = None,
    offline_research: OfflineProductResearchRuntime | None = None,
    mission: ProductMissionRuntime | None = None,
):
    active_config = validate_gateway_config(config or GatewayConfig())
    runtime = runtime or ProductRuntime(data_root.parent)
    store = store or OfflineDatasetStore(data_root.parent / "offline-datasets")
    online_research = online_research or CachingProductResearchRuntime(runtime, store)
    controls = controls or ProductControlRuntime(runtime)
    offline_research = offline_research or OfflineProductResearchRuntime(runtime, store)
    mission = mission or ProductMissionRuntime(runtime.root, integration_root=data_root.parent)
    BaseProductHandler = build_product_handler(
        data_root,
        config=active_config,
        ui_root=ui_root,
        runtime=runtime,
        research_runtime=online_research,
        control_runtime=controls,
    )

    class OfflineProductHandler(BaseProductHandler):
        def _read_offline_json(self) -> Mapping[str, Any] | None:
            if self.headers.get("Transfer-Encoding"):
                self._send(_json_error(HTTPStatus.BAD_REQUEST, "transfer_encoding_denied", "chunked request bodies are denied", active_config)); return None
            content_type = self.headers.get("Content-Type", "").split(";", 1)[0].strip().casefold()
            if content_type != "application/json":
                self._send(_json_error(HTTPStatus.UNSUPPORTED_MEDIA_TYPE, "json_required", "application/json required", active_config)); return None
            raw_length = self.headers.get("Content-Length", "")
            if not raw_length.isascii() or not raw_length.isdigit():
                self._send(_json_error(HTTPStatus.LENGTH_REQUIRED, "content_length_required", "bounded Content-Length required", active_config)); return None
            length = int(raw_length)
            if length < 2 or length > MAX_OFFLINE_REQUEST_BYTES:
                self._send(_json_error(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "offline_import_out_of_bounds", "offline request exceeds bounded import size", active_config)); return None
            try: payload = json.loads(self.rfile.read(length).decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                self._send(_json_error(HTTPStatus.BAD_REQUEST, "invalid_json", "malformed JSON", active_config)); return None
            if not isinstance(payload, Mapping):
                self._send(_json_error(HTTPStatus.BAD_REQUEST, "invalid_offline_request", "JSON object required", active_config)); return None
            return payload

        def _offline_index(self, *, head_only: bool = False) -> None:
            try: response = _safe_asset(ui_root, "index.html")
            except Exception as exc:
                self._send(_json_error(HTTPStatus.SERVICE_UNAVAILABLE, "offline_asset_unavailable", str(exc), active_config), head_only=head_only); return
            head_marker = b"</head>"
            body_marker = b"</body>"
            head_injection = b'<link rel="stylesheet" href="/ui/product-offline.css"><link rel="stylesheet" href="/ui/product-mission.css"></head>'
            body_injection = b'<script src="/ui/product-offline.js"></script><script src="/ui/product-mission.js"></script></body>'
            if head_marker not in response.body or body_marker not in response.body:
                self._send(_json_error(HTTPStatus.SERVICE_UNAVAILABLE, "offline_asset_invalid", "product index markers missing", active_config), head_only=head_only); return
            body = response.body.replace(head_marker, head_injection, 1).replace(body_marker, body_injection, 1)
            self._send(ByteResponse(response.status, body, response.content_type, response.headers), head_only=head_only)

        def do_GET(self) -> None:  # noqa: N802
            parsed = urlsplit(self.path)
            if parsed.path == "/":
                if not self._authorized(): return
                if parsed.query:
                    self._send(_json_error(HTTPStatus.BAD_REQUEST, "invalid_query", "product index does not accept query", active_config)); return
                self._offline_index(); return
            if parsed.path in OFFLINE_STATIC:
                if not self._authorized(): return
                if parsed.query:
                    self._send(_json_error(HTTPStatus.BAD_REQUEST, "invalid_query", "offline static routes do not accept query", active_config)); return
                try: response = _safe_asset(ui_root, OFFLINE_STATIC[parsed.path])
                except Exception as exc:
                    self._send(_json_error(HTTPStatus.SERVICE_UNAVAILABLE, "offline_asset_unavailable", str(exc), active_config)); return
                self._send(response); return
            if parsed.path == "/api/product/offline":
                if not self._authorized(): return
                if parsed.query:
                    self._send(_json_error(HTTPStatus.BAD_REQUEST, "invalid_query", "offline status does not accept query", active_config)); return
                self._send(ApiResponse(HTTPStatus.OK, store.snapshot())); return
            if parsed.path == "/api/product/offline/research/last":
                if not self._authorized(): return
                if parsed.query:
                    self._send(_json_error(HTTPStatus.BAD_REQUEST, "invalid_query", "offline research status does not accept query", active_config)); return
                self._send(ApiResponse(HTTPStatus.OK, offline_research.last_research())); return
            if parsed.path == "/api/product/mission/full":
                if not self._authorized(): return
                if parsed.query:
                    self._send(_json_error(HTTPStatus.BAD_REQUEST, "invalid_query", "mission status does not accept query", active_config)); return
                try: payload = mission.snapshot()
                except ProductMissionError as exc:
                    self._send(_json_error(HTTPStatus.SERVICE_UNAVAILABLE, "mission_control_unavailable", str(exc), active_config)); return
                self._send(ApiResponse(HTTPStatus.OK, payload)); return
            if parsed.path == "/api/product/mission/export":
                if not self._authorized(): return
                if parsed.query:
                    self._send(_json_error(HTTPStatus.BAD_REQUEST, "invalid_query", "mission export does not accept query", active_config)); return
                try: payload = mission.export_snapshot()
                except ProductMissionError as exc:
                    self._send(_json_error(HTTPStatus.SERVICE_UNAVAILABLE, "mission_export_unavailable", str(exc), active_config)); return
                self._send(ApiResponse(HTTPStatus.OK, payload)); return
            if parsed.path == "/api/product/strategies/evidence":
                if not self._authorized(): return
                if parsed.query:
                    self._send(_json_error(HTTPStatus.BAD_REQUEST, "invalid_query", "strategy evidence does not accept query", active_config)); return
                try: payload = mission.strategy_store.history()
                except ProductMissionError as exc:
                    self._send(_json_error(HTTPStatus.SERVICE_UNAVAILABLE, "strategy_evidence_unavailable", str(exc), active_config)); return
                self._send(ApiResponse(HTTPStatus.OK, payload)); return
            super().do_GET()

        def do_HEAD(self) -> None:  # noqa: N802
            parsed = urlsplit(self.path)
            if parsed.path == "/":
                if not self._authorized(): return
                if parsed.query:
                    self._send(_json_error(HTTPStatus.BAD_REQUEST, "invalid_query", "product index does not accept query", active_config), head_only=True); return
                self._offline_index(head_only=True); return
            if parsed.path in OFFLINE_STATIC:
                if not self._authorized(): return
                try: response = _safe_asset(ui_root, OFFLINE_STATIC[parsed.path])
                except Exception as exc:
                    self._send(_json_error(HTTPStatus.SERVICE_UNAVAILABLE, "offline_asset_unavailable", str(exc), active_config), head_only=True); return
                self._send(response, head_only=True); return
            super().do_HEAD()

        def do_POST(self) -> None:  # noqa: N802
            parsed = urlsplit(self.path)
            routes = {
                "/api/product/offline/import", "/api/product/offline/research",
                "/api/product/offline/paper/auto", "/api/product/mission/import",
            }
            if parsed.path not in routes:
                super().do_POST(); return
            if not self._authorized(): return
            if parsed.query:
                self._send(_json_error(HTTPStatus.BAD_REQUEST, "invalid_query", "offline mutation does not accept query", active_config)); return
            payload = self._read_offline_json()
            if payload is None: return
            try:
                if parsed.path == "/api/product/offline/import":
                    result = store.import_dataset(payload)
                elif parsed.path == "/api/product/offline/research":
                    if set(payload) != {"binding_sha256", "family"}: raise ProductOfflineError("offline research request schema mismatch")
                    result = offline_research.run_imported_research(binding_sha256=str(payload["binding_sha256"]), family=str(payload["family"]))
                elif parsed.path == "/api/product/offline/paper/auto":
                    if set(payload): raise ProductOfflineError("offline auto-paper request must be an empty object")
                    result = offline_research.auto_paper()
                else:
                    result = mission.import_snapshot(payload)
            except (ProductOfflineError, ProductResearchError, ProductMissionError) as exc:
                self._send(_json_error(HTTPStatus.BAD_REQUEST, "offline_action_rejected", str(exc), active_config)); return
            except Exception as exc:
                self._send(_json_error(HTTPStatus.SERVICE_UNAVAILABLE, "offline_action_unavailable", str(exc), active_config)); return
            self._send(ApiResponse(HTTPStatus.OK, result))

    return OfflineProductHandler


def serve(host: str, port: int, data_root: Path, *, ui_root: Path = PRODUCT_UI_ROOT) -> None:
    config = validate_gateway_config(GatewayConfig(mode="local", host=host, port=port))
    server = ThreadingHTTPServer((host, port), build_handler(data_root, config=config, ui_root=ui_root))
    print(f"NEXUS final mission-control gateway listening on http://{host}:{port}", flush=True)
    server.serve_forever()


def main() -> None:
    parser = argparse.ArgumentParser(description="NEXUS offline-first final Mission Control gateway")
    parser.add_argument("--host", default=os.environ.get("NEXUS_PRODUCT_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("NEXUS_PRODUCT_PORT", "8765")))
    parser.add_argument("--data-root", type=Path, default=DEFAULT_DATA_ROOT)
    parser.add_argument("--ui-root", type=Path, default=PRODUCT_UI_ROOT)
    args = parser.parse_args()
    serve(args.host, args.port, data_root=args.data_root, ui_root=args.ui_root)


if __name__ == "__main__": main()
