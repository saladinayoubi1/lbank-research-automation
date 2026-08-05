"""Deny-by-default authorization for bounded HTTPS egress.

This module authorizes requests but deliberately does not open sockets. A transport must
use the returned resolved addresses directly and must not follow redirects or re-resolve
without another authorization decision.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
import ipaddress
import socket
from typing import Callable, Iterable
from urllib.parse import urlsplit


class EgressError(RuntimeError):
    """Base egress policy failure."""


class EgressDenied(EgressError):
    """The request is not authorized."""


class HttpMethod(StrEnum):
    GET = "GET"
    HEAD = "HEAD"
    POST = "POST"


Resolver = Callable[[str, int], Iterable[str]]


@dataclass(frozen=True)
class EgressGrant:
    subject: str
    purpose: str
    host: str
    methods: frozenset[HttpMethod]
    content_types: frozenset[str]
    max_request_bytes: int
    max_response_bytes: int
    expires_at: datetime
    port: int = 443


@dataclass(frozen=True)
class AuthorizedRequest:
    url: str
    method: HttpMethod
    host: str
    port: int
    path_and_query: str
    resolved_ips: tuple[str, ...]
    content_type: str | None
    request_bytes: int
    max_response_bytes: int


class NetworkEgressAuthorizer:
    """Complete-mediation policy decision point for HTTPS requests."""

    def __init__(self, resolver: Resolver | None = None) -> None:
        self._resolver = resolver or self._system_resolver

    def authorize(
        self,
        grant: EgressGrant,
        *,
        subject: str,
        url: str,
        method: HttpMethod,
        request_bytes: int = 0,
        content_type: str | None = None,
    ) -> AuthorizedRequest:
        self._validate_grant(grant)
        if grant.subject != subject:
            raise EgressDenied("subject mismatch")
        if grant.expires_at <= datetime.now(timezone.utc):
            raise EgressDenied("expired grant")
        if method not in grant.methods:
            raise EgressDenied("HTTP method not allowed")
        if request_bytes < 0 or request_bytes > grant.max_request_bytes:
            raise EgressDenied("request byte limit exceeded")

        parsed = urlsplit(url)
        if parsed.scheme.lower() != "https":
            raise EgressDenied("only HTTPS is allowed")
        if parsed.username is not None or parsed.password is not None:
            raise EgressDenied("URL userinfo is prohibited")
        if parsed.fragment:
            raise EgressDenied("URL fragments are prohibited")
        if not parsed.hostname:
            raise EgressDenied("URL host is required")

        host = parsed.hostname.rstrip(".").lower()
        if host != grant.host.rstrip(".").lower():
            raise EgressDenied("host is not allowlisted")
        try:
            port = parsed.port or 443
        except ValueError as exc:
            raise EgressDenied("invalid port") from exc
        if port != grant.port:
            raise EgressDenied("port is not allowlisted")

        normalized_type = content_type.split(";", 1)[0].strip().lower() if content_type else None
        if request_bytes and not normalized_type:
            raise EgressDenied("content type required for non-empty body")
        if normalized_type and normalized_type not in grant.content_types:
            raise EgressDenied("content type not allowed")

        ips = tuple(sorted(set(self._resolver(host, port))))
        if not ips:
            raise EgressDenied("DNS resolution returned no addresses")
        for value in ips:
            self._validate_public_ip(value)

        path = parsed.path or "/"
        if parsed.query:
            path += "?" + parsed.query
        return AuthorizedRequest(
            url=url,
            method=method,
            host=host,
            port=port,
            path_and_query=path,
            resolved_ips=ips,
            content_type=normalized_type,
            request_bytes=request_bytes,
            max_response_bytes=grant.max_response_bytes,
        )

    @staticmethod
    def reject_redirect(status_code: int, location: str | None = None) -> None:
        if 300 <= status_code < 400:
            raise EgressDenied("redirect requires a new authorization decision")

    @staticmethod
    def verify_connected_peer(request: AuthorizedRequest, peer_ip: str) -> None:
        normalized = str(ipaddress.ip_address(peer_ip))
        if normalized not in request.resolved_ips:
            raise EgressDenied("connected peer was not authorized")

    @staticmethod
    def _validate_grant(grant: EgressGrant) -> None:
        if not grant.subject.strip() or not grant.purpose.strip() or not grant.host.strip():
            raise EgressDenied("subject, purpose, and host are required")
        if grant.expires_at.tzinfo is None:
            raise EgressDenied("expiry must be timezone-aware")
        if grant.port != 443:
            raise EgressDenied("only TCP port 443 is supported")
        if not grant.methods:
            raise EgressDenied("at least one method is required")
        if grant.max_request_bytes < 0 or grant.max_response_bytes < 1:
            raise EgressDenied("invalid byte limits")

    @staticmethod
    def _validate_public_ip(value: str) -> None:
        try:
            address = ipaddress.ip_address(value)
        except ValueError as exc:
            raise EgressDenied("resolver returned an invalid IP address") from exc
        if not address.is_global:
            raise EgressDenied("non-global destination address is prohibited")

    @staticmethod
    def _system_resolver(host: str, port: int) -> Iterable[str]:
        try:
            answers = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
        except OSError as exc:
            raise EgressDenied("DNS resolution failed") from exc
        return (answer[4][0] for answer in answers)
