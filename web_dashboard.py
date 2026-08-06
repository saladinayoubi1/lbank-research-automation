"""Read-only local HTTP API for generated research-readiness reports.

This module intentionally uses only the Python standard library. It exposes
pre-generated reports and never calls exchanges, Zotero, or write APIs.
"""
from __future__ import annotations

import argparse
import csv
import json
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

from dashboard_integrations import (
    IntegrationUnavailableError,
    load_research_summary,
    load_zotero_summary,
)

DEFAULT_DATA_ROOT = Path("data/market")
SUMMARY_FILENAME = "_data_readiness.json"
SERIES_FILENAME = "_data_readiness.csv"


class ReportUnavailableError(RuntimeError):
    """Raised when a generated dashboard report cannot be safely served."""


@dataclass(frozen=True)
class ApiResponse:
    status: int
    payload: dict[str, Any]


def _report_metadata(path: Path) -> dict[str, Any]:
    stat = path.stat()
    return {"source": path.name, "generated_report_mtime_ns": stat.st_mtime_ns, "stale_possible": True}


def load_summary(data_root: Path) -> dict[str, Any]:
    path = data_root / SUMMARY_FILENAME
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ReportUnavailableError(f"missing report: {SUMMARY_FILENAME}") from exc
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ReportUnavailableError(f"invalid report: {SUMMARY_FILENAME}") from exc
    if not isinstance(payload, dict):
        raise ReportUnavailableError(f"invalid report root: {SUMMARY_FILENAME}")
    return {"summary": payload, "metadata": _report_metadata(path)}


def load_series(data_root: Path, *, symbol: str | None = None, timeframe: str | None = None) -> dict[str, Any]:
    path = data_root / SERIES_FILENAME
    try:
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
    return {"series": rows, "count": len(rows), "filters": {"symbol": symbol, "timeframe": timeframe}, "metadata": _report_metadata(path)}


def dispatch_get(path_with_query: str, data_root: Path = DEFAULT_DATA_ROOT) -> ApiResponse:
    parsed = urlsplit(path_with_query)
    query = parse_qs(parsed.query, keep_blank_values=True)
    integration_root = data_root.parent / "integrations"

    if parsed.path == "/health":
        return ApiResponse(HTTPStatus.OK, {"status": "ok", "service": "lbank-research-readiness-dashboard", "mode": "read-only"})

    try:
        if parsed.path == "/api/readiness/summary":
            return ApiResponse(HTTPStatus.OK, load_summary(data_root))
        if parsed.path == "/api/readiness/series":
            return ApiResponse(HTTPStatus.OK, load_series(data_root, symbol=query.get("symbol", [None])[0], timeframe=query.get("timeframe", [None])[0]))
        if parsed.path == "/api/integrations/zotero":
            return ApiResponse(HTTPStatus.OK, {"summary": load_zotero_summary(integration_root)})
        if parsed.path == "/api/integrations/research":
            return ApiResponse(HTTPStatus.OK, {"summary": load_research_summary(integration_root)})
    except (ReportUnavailableError, IntegrationUnavailableError) as exc:
        return ApiResponse(HTTPStatus.SERVICE_UNAVAILABLE, {"error": "report_unavailable", "detail": str(exc)})

    return ApiResponse(HTTPStatus.NOT_FOUND, {"error": "not_found", "path": parsed.path})


def build_handler(data_root: Path):
    class DashboardHandler(BaseHTTPRequestHandler):
        def _send(self, response: ApiResponse) -> None:
            body = json.dumps(response.payload, sort_keys=True).encode("utf-8")
            self.send_response(int(response.status))
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
        def do_GET(self) -> None:  # noqa: N802
            self._send(dispatch_get(self.path, data_root))
        def do_POST(self) -> None:  # noqa: N802
            self._send(ApiResponse(HTTPStatus.METHOD_NOT_ALLOWED, {"error": "method_not_allowed", "allowed": ["GET"]}))
        def log_message(self, format: str, *args: object) -> None:
            return
    return DashboardHandler


def serve(host: str, port: int, data_root: Path) -> None:
    server = ThreadingHTTPServer((host, port), build_handler(data_root))
    print(f"Read-only dashboard API listening on http://{host}:{port}")
    print(f"Serving generated reports from {data_root.resolve()}")
    server.serve_forever()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--data-root", type=Path, default=DEFAULT_DATA_ROOT)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    serve(args.host, args.port, args.data_root)


if __name__ == "__main__":
    main()
