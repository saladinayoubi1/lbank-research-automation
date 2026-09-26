import http.client
import json
import threading
from contextlib import contextmanager
from pathlib import Path

from http.server import ThreadingHTTPServer
from mobile_paper_gateway import build_handler
from web_dashboard import GatewayConfig


@contextmanager
def gateway(tmp_path):
    # Exercise HTTP handler authorization in-process; production main always wraps TLS.
    config = GatewayConfig(mode="remote", host="127.0.0.1", port=8443,
        allowed_hosts=("laptop.example",), allowed_origins=("https://laptop.example",),
        access_token="a"*40, tls_cert=Path("test-cert"), tls_key=Path("test-key"))
    server = ThreadingHTTPServer(("127.0.0.1", 0), build_handler(tmp_path, config))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    def request(path="/api/product/paper", method="GET", **headers):
        conn = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=3)
        conn.request(method, path, headers={"Host":"laptop.example", **headers})
        response = conn.getresponse()
        result = response.status, response.read(), dict(response.getheaders())
        conn.close()
        return result
    try:
        yield request
    finally:
        server.shutdown(); server.server_close(); thread.join(3)


def test_mobile_gateway_authentication_and_read_only_scope(tmp_path):
    with gateway(tmp_path) as request:
        assert request()[0] == 401
        assert request(Authorization="Bearer incorrect")[0] == 401
        auth = {"Authorization":"Bearer "+"a"*40}
        assert request(Host="laptop.example.evil", **auth)[0] == 400
        assert request(Origin="https://evil.example", **auth)[0] == 403
        assert request("/api/product/paper/order", method="POST", **auth)[0] == 405
        assert request("/api/product/live", **auth)[0] == 404
        assert request("/api/product/paper?path=/secrets", **auth)[0] == 404
        status, raw, headers = request(**auth)
        data = json.loads(raw)
        assert status == 200 and data["read_only"] and data["paper_only"]
        assert data["live_trading_authority"] is False
        assert data["shared_portfolio"]["available"] is False
        assert "account" not in data["shared_portfolio"]  # Never invent a zero balance.
        assert "no-store" in headers["Cache-Control"]
        assert "a"*40 not in raw.decode()


def test_mobile_gateway_reads_existing_snapshot_without_mutation(tmp_path):
    from product_shared_paper import seal
    root = tmp_path/"shared_paper";root.mkdir()
    path = root/"terminal.json"
    snapshot = seal({"schema":"nexus.shared-paper-terminal.v1", "mode":"internal_paper",
        "read_only":True,"live_trading_authority":False,"available":True,
        "checked_at":"2026-01-01T00:00:00Z", "account":{"equity":512.5}})
    original=json.dumps(snapshot).encode();path.write_bytes(original)
    with gateway(tmp_path) as request:
        status, raw, _ = request(Authorization="Bearer "+"a"*40)
        data=json.loads(raw)["shared_portfolio"]
        assert status==200 and data["account"]["equity"]==512.5 and data["stale"]
    assert path.read_bytes()==original
