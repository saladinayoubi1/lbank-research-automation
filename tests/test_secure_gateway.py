from __future__ import annotations

import http.client
import json
import threading
from pathlib import Path

import pytest

from web_dashboard import (
    GatewayConfig,
    GatewayConfigurationError,
    RateLimiter,
    SECURITY_HEADERS,
    ThreadingHTTPServer,
    authorize_request,
    build_handler,
    effective_hosts,
    load_static_asset,
    validate_gateway_config,
)


def local_config(**changes):
    values = {
        "mode": "local",
        "host": "127.0.0.1",
        "port": 8000,
        "allowed_hosts": ("127.0.0.1",),
        "allowed_origins": ("http://127.0.0.1",),
        "rate_limit": 20,
        "rate_window_seconds": 60,
    }
    values.update(changes)
    return GatewayConfig(**values)


def remote_config(**changes):
    values = {
        "mode": "remote",
        "host": "0.0.0.0",
        "port": 8443,
        "allowed_hosts": ("nexus.example.test",),
        "allowed_origins": ("https://nexus.example.test",),
        "access_token": "t" * 40,
        "tls_cert": Path("cert.pem"),
        "tls_key": Path("key.pem"),
    }
    values.update(changes)
    return GatewayConfig(**values)


def test_local_mode_is_loopback_only_and_has_exact_hosts():
    assert validate_gateway_config(local_config()).mode == "local"
    with pytest.raises(GatewayConfigurationError, match="loopback"):
        validate_gateway_config(local_config(host="0.0.0.0"))
    hosts = effective_hosts(GatewayConfig())
    assert "127.0.0.1:8000" in hosts
    assert "localhost:8000" in hosts
    assert "[::1]:8000" in hosts
    assert not any("*" in host for host in hosts)


def test_remote_mode_requires_strong_token_tls_exact_host_and_exact_https_origin():
    assert validate_gateway_config(remote_config()).remote_access_enabled is True
    with pytest.raises(GatewayConfigurationError, match="strong runtime bearer token"):
        validate_gateway_config(remote_config(access_token="short"))
    with pytest.raises(GatewayConfigurationError, match="TLS"):
        validate_gateway_config(remote_config(tls_key=None))
    with pytest.raises(GatewayConfigurationError, match="exact allowed hosts"):
        validate_gateway_config(remote_config(allowed_hosts=()))
    with pytest.raises(GatewayConfigurationError, match="exact allowed origins"):
        validate_gateway_config(remote_config(allowed_origins=()))
    with pytest.raises(GatewayConfigurationError, match="wildcards"):
        validate_gateway_config(remote_config(allowed_hosts=("*.example.test",)))
    with pytest.raises(GatewayConfigurationError, match="HTTPS origins"):
        validate_gateway_config(remote_config(allowed_origins=("http://nexus.example.test",)))


def test_host_header_and_dns_rebinding_variants_are_denied():
    config = local_config()
    assert authorize_request(config, headers={"Host": "127.0.0.1"}, client_ip="127.0.0.1") is None
    for host in ("127.0.0.1.attacker.test", "attacker.test", "localhost.attacker.test", "evil@127.0.0.1"):
        denied = authorize_request(config, headers={"Host": host}, client_ip="127.0.0.1")
        assert denied is not None
        assert denied.payload["error"] == "invalid_host"


def test_local_non_loopback_client_and_cross_origin_are_denied():
    config = local_config()
    denied_client = authorize_request(config, headers={"Host": "127.0.0.1"}, client_ip="192.0.2.10")
    assert denied_client is not None
    assert denied_client.payload["error"] == "non_loopback_client"

    denied_origin = authorize_request(
        config,
        headers={"Host": "127.0.0.1", "Origin": "https://attacker.test"},
        client_ip="127.0.0.1",
    )
    assert denied_origin is not None
    assert denied_origin.payload["error"] == "origin_denied"

    allowed_origin = authorize_request(
        config,
        headers={"Host": "127.0.0.1", "Origin": "http://127.0.0.1"},
        client_ip="127.0.0.1",
    )
    assert allowed_origin is None


def test_remote_access_requires_exact_origin_host_and_constant_time_token_match():
    config = remote_config()
    base = {"Host": "nexus.example.test", "Origin": "https://nexus.example.test"}
    missing = authorize_request(config, headers=base, client_ip="203.0.113.7")
    assert missing is not None
    assert missing.status == 401
    assert missing.payload["error"] == "authentication_required"

    wrong = authorize_request(
        config, headers={**base, "Authorization": "Bearer " + "x" * 40}, client_ip="203.0.113.7"
    )
    assert wrong is not None
    assert wrong.payload["error"] == "authentication_required"

    assert authorize_request(
        config, headers={**base, "Authorization": "Bearer " + "t" * 40}, client_ip="203.0.113.7"
    ) is None


def test_rate_limiter_is_deterministic_and_bounded():
    limiter = RateLimiter(2, 10)
    assert limiter.allow("a", now=100.0) == (True, 0)
    assert limiter.allow("a", now=101.0) == (True, 0)
    allowed, retry = limiter.allow("a", now=102.0)
    assert allowed is False
    assert retry >= 1
    assert limiter.allow("a", now=111.0) == (True, 0)


def test_security_headers_are_fail_closed_and_csp_has_no_wildcard():
    required = {
        "Cache-Control", "Pragma", "X-Content-Type-Options", "X-Frame-Options",
        "Referrer-Policy", "Permissions-Policy", "Cross-Origin-Resource-Policy",
        "Content-Security-Policy",
    }
    assert required <= set(SECURITY_HEADERS)
    assert SECURITY_HEADERS["X-Content-Type-Options"] == "nosniff"
    assert SECURITY_HEADERS["X-Frame-Options"] == "DENY"
    assert "frame-ancestors 'none'" in SECURITY_HEADERS["Content-Security-Policy"]
    assert "*" not in SECURITY_HEADERS["Content-Security-Policy"]


def test_static_assets_are_exact_allowlist_and_symlink_free(tmp_path: Path):
    for name in ("index.html", "app.js", "styles.css", "phase4.css"):
        (tmp_path / name).write_text(f"safe-{name}", encoding="utf-8")
    assert load_static_asset("/ui/app.js", tmp_path).body == b"safe-app.js"
    assert load_static_asset("/ui/../secret", tmp_path) is None
    assert load_static_asset("/secret.txt", tmp_path) is None


def test_real_handler_enforces_headers_methods_rate_limit_and_never_echoes_auth(tmp_path: Path):
    data_root = tmp_path / "market"
    data_root.mkdir()
    ui_root = tmp_path / "ui"
    ui_root.mkdir()
    for name in ("index.html", "app.js", "styles.css", "phase4.css"):
        (ui_root / name).write_text("safe", encoding="utf-8")

    config = local_config(rate_limit=2)
    server = ThreadingHTTPServer(
        ("127.0.0.1", 0),
        build_handler(data_root, config=config, ui_root=ui_root, limiter=RateLimiter(2, 60)),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        connection.request("GET", "/health", headers={"Host": "127.0.0.1"})
        response = connection.getresponse()
        body = response.read().decode("utf-8")
        assert response.status == 200
        for header in SECURITY_HEADERS:
            assert response.getheader(header) is not None
        assert "Authorization" not in body

        connection.request("POST", "/health", body="{}", headers={"Host": "127.0.0.1"})
        response = connection.getresponse()
        payload = json.loads(response.read())
        assert response.status == 405
        assert payload["error"] == "method_not_allowed"
        assert response.getheader("Allow") == "GET, HEAD"

        connection.request("GET", "/health", headers={"Host": "127.0.0.1"})
        response = connection.getresponse()
        payload = json.loads(response.read())
        assert response.status == 429
        assert payload["error"] == "rate_limited"
        assert int(response.getheader("Retry-After")) >= 1
        connection.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_native_desktop_and_android_sources_have_no_direct_provider_network_path():
    root = Path(__file__).resolve().parents[1]
    desktop = (root / "desktop/lbank-monitor/main.js").read_text(encoding="utf-8")
    android = (root / "android/lbank-mobile/app/src/main/java/com/saladinayoubi/lbankmobile/MainActivity.java").read_text(encoding="utf-8")

    for forbidden in ("/chat/completions", "/v1/messages", ":generateContent", "/api/chat", "callProvider", "baseUrl"):
        assert forbidden not in desktop
        assert forbidden not in android
    assert "ALLOWED_PATHS" in desktop
    assert "method: 'GET'" in desktop
    assert "NEXUS_GATEWAY_URL" in android
    assert "HttpsURLConnection" in android
    assert 'setRequestMethod("GET")' in android


def test_static_frontend_has_no_embedded_secret_material():
    root = Path(__file__).resolve().parents[1] / "web_ui"
    combined = "\n".join(path.read_text(encoding="utf-8") for path in root.glob("*") if path.suffix in {".html", ".js", ".css"})
    assert "-----BEGIN PRIVATE KEY-----" not in combined
    assert "Authorization: Bearer " not in combined
    assert "ghp_" not in combined
    assert "api_key=" not in combined.casefold()
