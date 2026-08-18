from __future__ import annotations

import argparse
import json
import mimetypes
import os
from http import HTTPStatus
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import parse_qs, urlsplit

from phase5_strategy_factory import ALLOWED_FAMILIES
from product_control_runtime import ProductControlError, ProductControlRuntime
from product_research_runtime import ProductResearchError, ProductResearchRuntime
from product_runtime import ProductRuntime, ProductRuntimeError
from web_dashboard import ApiResponse, ByteResponse, GatewayConfig, ReportUnavailableError, gateway_disclosure, load_mission_control, validate_gateway_config, versioned
from web_ui_server import build_handler as build_ai_handler

PRODUCT_UI_ROOT = Path(__file__).with_name("product_ui")
DEFAULT_DATA_ROOT = Path("data/market")
MAX_PRODUCT_REQUEST_BYTES = 16_384
PRODUCT_STATIC = {
    "/": "index.html",
    "/ui/product.css": "product.css",
    "/ui/product-extra.css": "product-extra.css",
    "/ui/product.js": "product.js",
}


def _safe_asset(ui_root: Path, name: str) -> ByteResponse:
    root = ui_root.resolve(strict=True)
    target = (root / name).resolve(strict=True)
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise ReportUnavailableError("product asset escaped UI root") from exc
    if target.is_symlink() or not target.is_file() or target.stat().st_size > 1_000_000:
        raise ReportUnavailableError("product asset is unsafe or oversized")
    content_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
    if target.suffix == ".js": content_type = "text/javascript; charset=utf-8"
    elif target.suffix == ".css": content_type = "text/css; charset=utf-8"
    elif target.suffix == ".html": content_type = "text/html; charset=utf-8"
    return ByteResponse(HTTPStatus.OK, target.read_bytes(), content_type)


def _phase6_checkpoint() -> dict[str, Any]:
    path = Path(__file__).with_name(".nexus") / "phase6-checkpoint.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"status": "unavailable", "formal_gates_complete": None}
    if not isinstance(payload, dict):
        return {"status": "unavailable", "formal_gates_complete": None}
    return {key: payload.get(key) for key in (
        "status", "phase", "formal_gates", "formal_gates_complete", "paper_only",
        "live_trading_authority", "profitability_claim",
    )}


def _clean_idle_mission_snapshot() -> dict[str, Any]:
    """Truthful clean-install projection; no agents, runners, or providers are fabricated."""
    return {
        "status": "idle",
        "contract_version": "nexus.mission-control.read.v1",
        "projection": "clean_install_idle",
        "reason": "no Mission Control runtime report has been generated yet",
        "mission": {
            "mission_id": None,
            "objective": None,
            "status": "idle",
            "priority": "normal",
            "policy_version": None,
            "schedule": None,
            "last_run": None,
            "next_run": None,
            "completed_steps": 0,
            "total_steps": 0,
            "progress": 0,
            "current_task": None,
        },
        "queue": {"counts": {"READY": 0, "RUNNING": 0, "FAILED": 0, "BLOCKED": 0}},
        "agents": [],
        "runners": [],
        "local_node": {"registered": False, "enabled": False, "healthy": False},
        "data": {"status": "idle", "runtime_report_present": False},
        "providers": {},
        "paper": {"mode": "paper", "live_trading_authority": False},
        "circuits": {},
        "limits": {},
        "notifications": [],
    }


def _mission_snapshot(data_root: Path) -> dict[str, Any]:
    report = data_root.resolve().parent / "mission_control" / "_mission_control.json"
    if not report.exists() and not report.is_symlink():
        return _clean_idle_mission_snapshot()
    try:
        payload = load_mission_control(data_root)["mission_control"]
    except Exception as exc:
        return {"status": "unavailable", "reason": str(exc)}
    return {"status": "available", **payload}


def _strategy_snapshot() -> dict[str, Any]:
    return {
        "contract_version": "nexus.product-strategies.v1",
        "families": [{
            "id": family,
            "status": "qualification_engine_available",
            "promotion_ceiling": "paper_candidate",
            "live_execution_allowed": False,
        } for family in sorted(ALLOWED_FAMILIES)],
        "qualification_path": [
            "Evidence", "Hypothesis", "Preregister", "Robustness",
            "Cost/Funding/Slippage Stress", "Walk-forward", "OOS",
            "Regime Analysis", "Failure Modes", "Paper Candidate",
        ],
        "deterministic_risk_final_authority": True,
    }


def _product_overview(runtime: ProductRuntime, data_root: Path) -> dict[str, Any]:
    paper = runtime.paper_snapshot()
    live = runtime.live_surface()
    mission = _mission_snapshot(data_root)
    return {
        "contract_version": "nexus.product-overview.v2",
        "product": "NEXUS Personal Pro",
        "delivery": "canonical-python-sidecar",
        "formal_phase": _phase6_checkpoint(),
        "paper": paper,
        "live": live,
        "mission_control": {
            "status": mission.get("status"), "mission": mission.get("mission"),
            "queue": mission.get("queue"), "agents": mission.get("agents"),
            "providers": mission.get("providers"), "circuits": mission.get("circuits"),
            "runners": mission.get("runners"), "local_node": mission.get("local_node"),
            "notifications": mission.get("notifications"),
        },
        "capabilities": {
            "canonical_data_registry": "active",
            "public_market_data": "bybit_primary_closed_candles",
            "research_backtest_studio": "active",
            "strategy_factory": "active",
            "regime_decision_pipeline": "active",
            "deterministic_risk": "final_paper_authority",
            "paper_execution": "active",
            "automated_paper_pipeline": "qualification_and_risk_gated",
            "ai_room": "policy_gated",
            "mission_control": mission.get("status", "unavailable"),
            "audit_replay_recovery": "active",
            "reports": "json_csv",
            "live_main": "locked_owner_controlled",
        },
    }


def _parse_limit(path: str, *, default: int = 200, maximum: int = 1000) -> int:
    parsed = urlsplit(path)
    if not parsed.query:
        return default
    query = parse_qs(parsed.query, keep_blank_values=True, strict_parsing=True, max_num_fields=2)
    if set(query) != {"limit"} or len(query["limit"]) != 1:
        raise ProductRuntimeError("invalid bounded limit query")
    value = query["limit"][0]
    if not value.isascii() or not value.isdigit():
        raise ProductRuntimeError("invalid bounded limit")
    limit = int(value)
    if not 1 <= limit <= maximum:
        raise ProductRuntimeError("bounded limit out of range")
    return limit


def _json_error(status: int, code: str, detail: str, config: GatewayConfig) -> ApiResponse:
    return ApiResponse(status, versioned({"error": code, "detail": detail, "gateway": gateway_disclosure(config)}))


def build_handler(
    data_root: Path,
    *,
    config: GatewayConfig | None = None,
    ui_root: Path = PRODUCT_UI_ROOT,
    runtime: ProductRuntime | None = None,
    research_runtime: ProductResearchRuntime | None = None,
    control_runtime: ProductControlRuntime | None = None,
):
    active_config = validate_gateway_config(config or GatewayConfig())
    runtime = runtime or ProductRuntime(data_root.parent)
    research_runtime = research_runtime or ProductResearchRuntime(runtime)
    control_runtime = control_runtime or ProductControlRuntime(runtime)
    BaseHandler = build_ai_handler(data_root, ui_root=ui_root, config=active_config)

    class ProductHandler(BaseHandler):
        def _product_get(self, *, head_only: bool = False) -> bool:
            parsed = urlsplit(self.path)
            if parsed.path in PRODUCT_STATIC:
                if not self._authorized(): return True
                if parsed.query:
                    self._send(_json_error(HTTPStatus.BAD_REQUEST, "invalid_query", "static routes do not accept query", active_config), head_only=head_only); return True
                try: response = _safe_asset(ui_root, PRODUCT_STATIC[parsed.path])
                except Exception as exc:
                    self._send(_json_error(HTTPStatus.SERVICE_UNAVAILABLE, "static_asset_unavailable", str(exc), active_config), head_only=head_only); return True
                self._send(response, head_only=head_only); return True

            if not parsed.path.startswith("/api/product/"):
                return False
            if not self._authorized(): return True
            try:
                if parsed.path == "/api/product/overview":
                    if parsed.query: raise ProductRuntimeError("overview does not accept query")
                    payload = _product_overview(runtime, data_root)
                elif parsed.path == "/api/product/paper":
                    if parsed.query: raise ProductRuntimeError("paper snapshot does not accept query")
                    payload = runtime.paper_snapshot()
                elif parsed.path == "/api/product/paper/events":
                    payload = runtime.paper_events(limit=_parse_limit(self.path))
                elif parsed.path == "/api/product/live":
                    if parsed.query: raise ProductRuntimeError("live status does not accept query")
                    payload = runtime.live_surface()
                elif parsed.path == "/api/product/strategies":
                    if parsed.query: raise ProductRuntimeError("strategies does not accept query")
                    payload = _strategy_snapshot()
                elif parsed.path == "/api/product/mission-control":
                    if parsed.query: raise ProductRuntimeError("mission-control does not accept query")
                    payload = _mission_snapshot(data_root)
                elif parsed.path == "/api/product/data/registry":
                    if parsed.query: raise ProductRuntimeError("registry does not accept query")
                    payload = research_runtime.registry_snapshot()
                elif parsed.path == "/api/product/research/last":
                    if parsed.query: raise ProductRuntimeError("last research does not accept query")
                    payload = research_runtime.last_research()
                elif parsed.path == "/api/product/risk":
                    if parsed.query: raise ProductRuntimeError("risk snapshot does not accept query")
                    payload = control_runtime.risk_snapshot()
                elif parsed.path == "/api/product/recovery":
                    if parsed.query: raise ProductRuntimeError("recovery snapshot does not accept query")
                    payload = control_runtime.recovery_snapshot()
                elif parsed.path == "/api/product/notifications":
                    payload = control_runtime.notifications(limit=_parse_limit(self.path, default=100, maximum=500))
                elif parsed.path == "/api/product/export/paper.json":
                    if parsed.query: raise ProductRuntimeError("export does not accept query")
                    self._send(ByteResponse(HTTPStatus.OK, control_runtime.export_json(), "application/json; charset=utf-8"), head_only=head_only); return True
                elif parsed.path == "/api/product/export/paper.csv":
                    if parsed.query: raise ProductRuntimeError("export does not accept query")
                    self._send(ByteResponse(HTTPStatus.OK, control_runtime.export_csv(), "text/csv; charset=utf-8"), head_only=head_only); return True
                else:
                    self._send(_json_error(HTTPStatus.NOT_FOUND, "not_found", parsed.path, active_config), head_only=head_only); return True
            except (ProductRuntimeError, ProductResearchError, ProductControlError) as exc:
                self._send(_json_error(HTTPStatus.BAD_REQUEST, "product_request_invalid", str(exc), active_config), head_only=head_only); return True
            except Exception as exc:
                self._send(_json_error(HTTPStatus.SERVICE_UNAVAILABLE, "product_runtime_unavailable", str(exc), active_config), head_only=head_only); return True
            self._send(ApiResponse(HTTPStatus.OK, payload), head_only=head_only); return True

        def do_GET(self) -> None:  # noqa: N802
            if not self._product_get(): super().do_GET()

        def do_HEAD(self) -> None:  # noqa: N802
            if not self._product_get(head_only=True): super().do_HEAD()

        def _read_json_body(self) -> Mapping[str, Any] | None:
            if self.headers.get("Transfer-Encoding"):
                self._send(_json_error(HTTPStatus.BAD_REQUEST, "transfer_encoding_denied", "chunked request bodies are denied", active_config)); return None
            content_type = self.headers.get("Content-Type", "").split(";", 1)[0].strip().casefold()
            if content_type != "application/json":
                self._send(_json_error(HTTPStatus.UNSUPPORTED_MEDIA_TYPE, "json_required", "application/json required", active_config)); return None
            raw_length = self.headers.get("Content-Length", "")
            if not raw_length.isascii() or not raw_length.isdigit():
                self._send(_json_error(HTTPStatus.LENGTH_REQUIRED, "content_length_required", "bounded Content-Length required", active_config)); return None
            length = int(raw_length)
            if length < 2 or length > MAX_PRODUCT_REQUEST_BYTES:
                self._send(_json_error(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "request_body_out_of_bounds", "request body outside product bound", active_config)); return None
            try: payload = json.loads(self.rfile.read(length).decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                self._send(_json_error(HTTPStatus.BAD_REQUEST, "invalid_json", "malformed JSON", active_config)); return None
            if not isinstance(payload, Mapping):
                self._send(_json_error(HTTPStatus.BAD_REQUEST, "invalid_product_request", "JSON object required", active_config)); return None
            return payload

        def do_POST(self) -> None:  # noqa: N802
            parsed = urlsplit(self.path)
            product_routes = {
                "/api/product/paper/order", "/api/product/paper/auto", "/api/product/research/run",
                "/api/product/session", "/api/product/kill-switch",
            }
            if parsed.path not in product_routes:
                super().do_POST(); return
            if not self._authorized(): return
            if parsed.query:
                self._send(_json_error(HTTPStatus.BAD_REQUEST, "invalid_query", "product mutation does not accept query", active_config)); return
            payload = self._read_json_body()
            if payload is None: return
            try:
                if parsed.path == "/api/product/paper/order":
                    result = runtime.submit_paper_order(payload)
                elif parsed.path == "/api/product/research/run":
                    if set(payload) != {"symbol", "timeframe", "family", "limit"}:
                        raise ProductResearchError("research request schema mismatch")
                    if isinstance(payload["limit"], bool) or not isinstance(payload["limit"], int):
                        raise ProductResearchError("research limit must be integer")
                    result = research_runtime.run_research(symbol=str(payload["symbol"]), timeframe=str(payload["timeframe"]), family=str(payload["family"]), limit=payload["limit"])
                elif parsed.path == "/api/product/paper/auto":
                    if set(payload): raise ProductResearchError("auto-paper request must be an empty object")
                    result = research_runtime.auto_paper()
                elif parsed.path == "/api/product/session":
                    result = control_runtime.set_session(payload)
                else:
                    result = control_runtime.set_kill_switch(payload)
            except (ProductRuntimeError, ProductResearchError, ProductControlError) as exc:
                self._send(_json_error(HTTPStatus.BAD_REQUEST, "product_action_rejected", str(exc), active_config)); return
            except Exception as exc:
                self._send(_json_error(HTTPStatus.SERVICE_UNAVAILABLE, "product_action_unavailable", str(exc), active_config)); return
            self._send(ApiResponse(HTTPStatus.OK, result))

    return ProductHandler


def serve(host: str, port: int, data_root: Path, *, ui_root: Path = PRODUCT_UI_ROOT) -> None:
    config = validate_gateway_config(GatewayConfig(mode="local", host=host, port=port))
    server = ThreadingHTTPServer((host, port), build_handler(data_root, config=config, ui_root=ui_root))
    print(f"NEXUS product gateway listening on http://{host}:{port}", flush=True)
    server.serve_forever()


def main() -> None:
    parser = argparse.ArgumentParser(description="NEXUS canonical local product gateway")
    parser.add_argument("--host", default=os.environ.get("NEXUS_PRODUCT_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("NEXUS_PRODUCT_PORT", "8765")))
    parser.add_argument("--data-root", type=Path, default=DEFAULT_DATA_ROOT)
    parser.add_argument("--ui-root", type=Path, default=PRODUCT_UI_ROOT)
    args = parser.parse_args()
    serve(args.host, args.port, data_root=args.data_root, ui_root=args.ui_root)


if __name__ == "__main__": main()
