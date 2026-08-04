from __future__ import annotations

import random
import time
from typing import Any
from urllib.parse import urlparse

import requests

_RETRYABLE = {403, 408, 425, 429, 500, 502, 503, 504}
_ORIGINAL_REQUEST = requests.sessions.Session.request
_INSTALLED = False


def _is_bybit_public(url: str) -> bool:
    return urlparse(url).netloc.lower() == "public.bybit.com"


def _request_with_resilience(
    self: requests.Session,
    method: str,
    url: str,
    **kwargs: Any,
) -> requests.Response:
    if not _is_bybit_public(url):
        return _ORIGINAL_REQUEST(self, method, url, **kwargs)

    headers = dict(kwargs.pop("headers", {}) or {})
    headers.setdefault(
        "User-Agent",
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/127.0 Safari/537.36",
    )
    headers.setdefault("Accept", "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8")
    headers.setdefault("Accept-Language", "en-US,en;q=0.9")
    headers.setdefault("Referer", "https://public.bybit.com/")
    headers.setdefault("Cache-Control", "no-cache")
    kwargs["headers"] = headers

    last_response: requests.Response | None = None
    for attempt in range(1, 7):
        response = _ORIGINAL_REQUEST(self, method, url, **kwargs)
        last_response = response
        if response.status_code not in _RETRYABLE:
            return response
        if attempt < 6:
            delay = min(45.0, 2.0 ** (attempt - 1)) + random.uniform(0.0, 1.5)
            time.sleep(delay)
    assert last_response is not None
    return last_response


def install() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    requests.sessions.Session.request = _request_with_resilience
    _INSTALLED = True


install()
