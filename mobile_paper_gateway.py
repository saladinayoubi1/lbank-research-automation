"""Authenticated, read-only HTTPS projection of the owner's shared Paper terminal.

Reads the desktop's exported snapshot; never starts a second trading runtime or
accepts orders. Reuses the repository gateway's Host/Origin/auth/rate boundaries.
"""
from __future__ import annotations

import argparse
import ssl
from http import HTTPStatus
from http.server import ThreadingHTTPServer
from pathlib import Path

from product_shared_paper import load_snapshot
from web_dashboard import ApiResponse, GatewayConfig, build_handler as dashboard_handler, validate_gateway_config


def build_handler(data_root: Path, config: GatewayConfig):
    config = validate_gateway_config(config)
    parent = dashboard_handler(data_root, config=config)

    class MobilePaperHandler(parent):
        def _read(self, *, head_only=False):
            if not self._authorized():
                return
            if self.path != "/api/product/paper":
                self._send(ApiResponse(HTTPStatus.NOT_FOUND, {"error": "not_found"}), head_only=head_only)
                return
            snapshot = load_snapshot(data_root)
            self._send(ApiResponse(HTTPStatus.OK, {
                "contract_version": "nexus.mobile-paper.read.v1",
                "paper_only": True, "read_only": True,
                "live_trading_authority": False, "shared_portfolio": snapshot,
            }), head_only=head_only)

    return MobilePaperHandler


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, required=True,
                        help="Existing desktop product-data directory containing shared_paper/terminal.json")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8443)
    parser.add_argument("--allowed-host", action="append", required=True)
    parser.add_argument("--allowed-origin", action="append", required=True)
    parser.add_argument("--tls-cert", type=Path, required=True)
    parser.add_argument("--tls-key", type=Path, required=True)
    parser.add_argument("--token-file", type=Path, required=True)
    args = parser.parse_args()
    config = validate_gateway_config(GatewayConfig(
        mode="remote", host=args.host, port=args.port,
        allowed_hosts=tuple(args.allowed_host), allowed_origins=tuple(args.allowed_origin),
        access_token=args.token_file.read_text(encoding="utf-8").strip(),
        tls_cert=args.tls_cert, tls_key=args.tls_key, max_response_bytes=1_000_000,
    ))
    tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    tls.minimum_version = ssl.TLSVersion.TLSv1_2
    tls.load_cert_chain(str(args.tls_cert), str(args.tls_key))
    with ThreadingHTTPServer((args.host, args.port), build_handler(args.data_root, config)) as server:
        server.socket = tls.wrap_socket(server.socket, server_side=True)
        print("NEXUS mobile Paper gateway ready: HTTPS, authenticated, read-only", flush=True)
        server.serve_forever()


if __name__ == "__main__":
    main()
