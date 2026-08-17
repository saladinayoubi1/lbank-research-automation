"""Pinned, deny-by-default HTTPS transport for DeepSeek provider traffic."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import http.client
import socket
import ssl
from typing import Callable, Mapping

from network_egress import (
    AuthorizedRequest,
    EgressDenied,
    EgressGrant,
    HttpMethod,
    NetworkEgressAuthorizer,
)

DEEPSEEK_SUBJECT = "deepseek-provider"
DEEPSEEK_HOST = "api.deepseek.com"
DEEPSEEK_CHAT_URL = "https://api.deepseek.com/chat/completions"
JSON_CONTENT_TYPE = "application/json"
MAX_REQUEST_BYTES = 512_000
MAX_RESPONSE_BYTES = 2_000_000
GRANT_TTL = timedelta(minutes=2)


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    """HTTPS connection whose TCP destination comes only from an authorization decision."""

    def __init__(
        self,
        authorized: AuthorizedRequest,
        authorizer: NetworkEgressAuthorizer,
        *,
        timeout: float,
        ssl_context: ssl.SSLContext | None = None,
    ) -> None:
        super().__init__(
            authorized.host,
            port=authorized.port,
            timeout=timeout,
            context=ssl_context or ssl.create_default_context(),
        )
        self._authorized = authorized
        self._authorizer = authorizer

    def connect(self) -> None:
        last_error: Exception | None = None
        for destination_ip in self._authorized.resolved_ips:
            raw = None
            try:
                raw = socket.create_connection(
                    (destination_ip, self._authorized.port),
                    self.timeout,
                    self.source_address,
                )
                peer_ip = raw.getpeername()[0]
                self._authorizer.verify_connected_peer(self._authorized, peer_ip)
                # Certificate/hostname verification remains bound to the approved FQDN,
                # while the TCP socket is pinned to the already-authorized IP address.
                self.sock = self._context.wrap_socket(
                    raw,
                    server_hostname=self._authorized.host,
                )
                return
            except (OSError, ssl.SSLError, EgressDenied) as exc:
                last_error = exc
                if raw is not None:
                    try:
                        raw.close()
                    except OSError:
                        pass
        if last_error is None:
            raise EgressDenied("authorized destination set is empty")
        raise last_error


def authorize_deepseek_json(
    body: bytes,
    *,
    authorizer: NetworkEgressAuthorizer | None = None,
) -> tuple[NetworkEgressAuthorizer, AuthorizedRequest]:
    if not isinstance(body, bytes):
        raise EgressDenied("DeepSeek request body must be bytes")
    authz = authorizer or NetworkEgressAuthorizer()
    grant = EgressGrant(
        subject=DEEPSEEK_SUBJECT,
        purpose="bounded DeepSeek research assistance",
        host=DEEPSEEK_HOST,
        methods=frozenset({HttpMethod.POST}),
        content_types=frozenset({JSON_CONTENT_TYPE}),
        max_request_bytes=MAX_REQUEST_BYTES,
        max_response_bytes=MAX_RESPONSE_BYTES,
        expires_at=datetime.now(timezone.utc) + GRANT_TTL,
        port=443,
    )
    authorized = authz.authorize(
        grant,
        subject=DEEPSEEK_SUBJECT,
        url=DEEPSEEK_CHAT_URL,
        method=HttpMethod.POST,
        request_bytes=len(body),
        content_type=JSON_CONTENT_TYPE,
    )
    return authz, authorized


def post_authorized_json(
    *,
    body: bytes,
    headers: Mapping[str, str],
    authorized: AuthorizedRequest,
    authorizer: NetworkEgressAuthorizer,
    timeout: float,
    connection_factory: Callable[..., http.client.HTTPSConnection] = _PinnedHTTPSConnection,
) -> bytes:
    if not isinstance(body, bytes) or len(body) != authorized.request_bytes:
        raise EgressDenied("request body differs from authorized byte count")
    if authorized.method is not HttpMethod.POST:
        raise EgressDenied("authorized DeepSeek request is not POST")
    if authorized.host != DEEPSEEK_HOST or authorized.port != 443:
        raise EgressDenied("authorized DeepSeek destination changed")
    if authorized.path_and_query != "/chat/completions":
        raise EgressDenied("authorized DeepSeek path changed")

    conn = connection_factory(authorized, authorizer, timeout=timeout)
    try:
        conn.request(
            authorized.method.value,
            authorized.path_and_query,
            body=body,
            headers=dict(headers),
        )
        response = conn.getresponse()
        authorizer.reject_redirect(response.status, response.getheader("Location"))
        payload = response.read(authorized.max_response_bytes + 1)
        if len(payload) > authorized.max_response_bytes:
            raise EgressDenied("DeepSeek response byte limit exceeded")
        if response.status < 200 or response.status >= 300:
            raise EgressDenied(f"DeepSeek HTTP status denied: {response.status}")
        return payload
    finally:
        conn.close()
