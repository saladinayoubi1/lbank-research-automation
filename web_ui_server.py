"""Read-only local server for the browser dashboard and approved readiness APIs."""
from __future__ import annotations

import argparse
import mimetypes
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from web_dashboard import DEFAULT_DATA_ROOT, ApiResponse, dispatch_get

UI_ROOT = Path(__file__).with_name("web_ui")
STATIC_ROUTES = {
    "/": "index.html",
    "/ui/app.js": "app.js",
    "/ui/styles.css": "styles.css",
    "/ui/phase4.css": "phase4.css",
}

@dataclass(frozen=True)
class WebResponse:
    status: int
    body: bytes
    content_type: str


def dispatch(path_with_query: str, data_root: Path, ui_root: Path = UI_ROOT) -> WebResponse:
    path = urlsplit(path_with_query).path
    if path.startswith("/api/") or path == "/health":
        response: ApiResponse = dispatch_get(path_with_query, data_root)
        import json
        return WebResponse(int(response.status), json.dumps(response.payload, sort_keys=True).encode(), "application/json; charset=utf-8")
    filename = STATIC_ROUTES.get(path)
    if filename is None:
        return WebResponse(HTTPStatus.NOT_FOUND, b"Not found", "text/plain; charset=utf-8")
    try:
        body = (ui_root / filename).read_bytes()
    except OSError:
        return WebResponse(HTTPStatus.SERVICE_UNAVAILABLE, b"UI unavailable", "text/plain; charset=utf-8")
    return WebResponse(HTTPStatus.OK, body, mimetypes.guess_type(filename)[0] or "application/octet-stream")


def build_handler(data_root: Path, ui_root: Path = UI_ROOT):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            response = dispatch(self.path, data_root, ui_root)
            self.send_response(int(response.status))
            self.send_header("Content-Type", response.content_type)
            self.send_header("Content-Length", str(len(response.body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(response.body)
        def do_POST(self) -> None:  # noqa: N802
            self.send_error(HTTPStatus.METHOD_NOT_ALLOWED)
        def log_message(self, format: str, *args: object) -> None:
            return
    return Handler


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--data-root", type=Path, default=DEFAULT_DATA_ROOT)
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), build_handler(args.data_root))
    print(f"Dashboard available at http://{args.host}:{args.port}")
    server.serve_forever()

if __name__ == "__main__":
    main()
