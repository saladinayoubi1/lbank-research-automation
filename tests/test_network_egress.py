from datetime import datetime, timedelta, timezone

import pytest

from network_egress import (
    EgressDenied,
    EgressGrant,
    HttpMethod,
    NetworkEgressAuthorizer,
)


def grant(**overrides):
    values = {
        "subject": "collector",
        "purpose": "fetch public market data",
        "host": "api.lbkex.com",
        "methods": frozenset({HttpMethod.GET}),
        "content_types": frozenset({"application/json"}),
        "max_request_bytes": 0,
        "max_response_bytes": 1_000_000,
        "expires_at": datetime.now(timezone.utc) + timedelta(minutes=5),
    }
    values.update(overrides)
    return EgressGrant(**values)


def public_resolver(host, port):
    assert host == "api.lbkex.com"
    assert port == 443
    return ["1.1.1.1", "2606:4700:4700::1111"]


def test_authorizes_exact_https_destination():
    request = NetworkEgressAuthorizer(public_resolver).authorize(
        grant(), subject="collector", url="https://api.lbkex.com/v2/kline.do?symbol=btc_usdt", method=HttpMethod.GET
    )
    assert request.host == "api.lbkex.com"
    assert request.path_and_query.startswith("/v2/kline.do?")
    assert request.max_response_bytes == 1_000_000


@pytest.mark.parametrize(
    "url",
    [
        "http://api.lbkex.com/v2/kline.do",
        "https://api.lbkex.com.evil.example/v2/kline.do",
        "https://api.lbkex.com@evil.example/v2/kline.do",
        "https://api.lbkex.com:444/v2/kline.do",
        "https://api.lbkex.com/v2/kline.do#secret",
    ],
)
def test_rejects_scheme_host_userinfo_port_and_fragment_bypasses(url):
    with pytest.raises(EgressDenied):
        NetworkEgressAuthorizer(public_resolver).authorize(
            grant(), subject="collector", url=url, method=HttpMethod.GET
        )


def test_rejects_private_or_loopback_dns_answers():
    for address in ("127.0.0.1", "10.0.0.1", "169.254.169.254", "::1"):
        with pytest.raises(EgressDenied, match="non-global"):
            NetworkEgressAuthorizer(lambda host, port, a=address: [a]).authorize(
                grant(), subject="collector", url="https://api.lbkex.com/", method=HttpMethod.GET
            )


def test_rejects_mixed_public_and_private_dns_answers():
    with pytest.raises(EgressDenied, match="non-global"):
        NetworkEgressAuthorizer(lambda host, port: ["1.1.1.1", "10.0.0.1"]).authorize(
            grant(), subject="collector", url="https://api.lbkex.com/", method=HttpMethod.GET
        )


def test_enforces_subject_method_content_type_and_byte_limits():
    authorizer = NetworkEgressAuthorizer(public_resolver)
    with pytest.raises(EgressDenied, match="subject"):
        authorizer.authorize(grant(), subject="other", url="https://api.lbkex.com/", method=HttpMethod.GET)
    with pytest.raises(EgressDenied, match="method"):
        authorizer.authorize(grant(), subject="collector", url="https://api.lbkex.com/", method=HttpMethod.POST)
    with pytest.raises(EgressDenied, match="byte"):
        authorizer.authorize(
            grant(max_request_bytes=2), subject="collector", url="https://api.lbkex.com/", method=HttpMethod.GET,
            request_bytes=3, content_type="application/json"
        )
    with pytest.raises(EgressDenied, match="content type"):
        authorizer.authorize(
            grant(max_request_bytes=10), subject="collector", url="https://api.lbkex.com/", method=HttpMethod.GET,
            request_bytes=2, content_type="text/plain"
        )


def test_redirects_require_new_authorization():
    with pytest.raises(EgressDenied, match="redirect"):
        NetworkEgressAuthorizer.reject_redirect(302, "https://evil.example/")
    NetworkEgressAuthorizer.reject_redirect(200)


def test_connected_peer_must_match_authorized_resolution():
    request = NetworkEgressAuthorizer(public_resolver).authorize(
        grant(), subject="collector", url="https://api.lbkex.com/", method=HttpMethod.GET
    )
    NetworkEgressAuthorizer.verify_connected_peer(request, "1.1.1.1")
    with pytest.raises(EgressDenied, match="peer"):
        NetworkEgressAuthorizer.verify_connected_peer(request, "8.8.8.8")


def test_expired_and_naive_expiry_fail_closed():
    authorizer = NetworkEgressAuthorizer(public_resolver)
    with pytest.raises(EgressDenied, match="expired"):
        authorizer.authorize(
            grant(expires_at=datetime.now(timezone.utc) - timedelta(seconds=1)),
            subject="collector", url="https://api.lbkex.com/", method=HttpMethod.GET
        )
    with pytest.raises(EgressDenied, match="timezone"):
        authorizer.authorize(
            grant(expires_at=datetime.now()), subject="collector", url="https://api.lbkex.com/", method=HttpMethod.GET
        )
